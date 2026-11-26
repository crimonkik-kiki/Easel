"""Native Codex image generation. Authentication stays in the native CLI."""
from __future__ import annotations

import asyncio
import base64
import binascii
from io import BytesIO
import json
import os
from pathlib import Path
import time
from typing import Callable

from workbench import __version__
from workbench.harnesses.base import HarnessError, RunRequest
from workbench.harnesses.commands import base_command
from workbench.harnesses.rpc import RPC

MAX_IMAGE_BYTES = 40 * 1024 * 1024


def native_environment(env: dict[str, str]) -> dict[str, str]:
    # AI Workbench image/API credentials must not change the native Codex login mode.
    isolated = dict(env)
    for name in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'OPENAI_BASE_URL', 'OPENAI_API_BASE',
                 'IMG_API_KEY', 'IMG_BASE_URL', 'API_KEY', 'BASE_URL'):
        isolated.pop(name, None)
    return isolated


async def _reject(method, params):
    raise HarnessError('生图任务不接受额外工具或权限请求，请在 Codex 中处理登录或授权后重试')


async def _initialize(rpc):
    await rpc.call('initialize', {
        'clientInfo': {'name': 'ai_workbench_imagegen', 'version': __version__},
        'capabilities': {'experimentalApi': True}}, timeout=20)
    await rpc.send({'method': 'initialized'})


async def native_status(root: Path, env: dict[str, str]) -> dict:
    try:
        command = base_command('codex') + ['app-server']
    except HarnessError as error:
        return {'installed': False, 'ready': False, 'message': str(error)}
    request = RunRequest('', root, native_environment(env), sandbox='read-only')
    try:
        async with RPC(request, command, lambda method, params: None, _reject) as rpc:
            await _initialize(rpc)
            result = await rpc.call('account/read', {}, timeout=20)
        account = result.get('account') or {}
        ready = account.get('type') == 'chatgpt'
        return {'installed': True, 'ready': ready,
                'authMode': account.get('type', ''),
                'message': 'Codex 原生登录已就绪；生图是否可用以实际生成结果为准' if ready
                           else '请先执行 codex login 并使用 ChatGPT 登录；此通道不使用图片 API Key'}
    except (HarnessError, OSError) as error:
        return {'installed': True, 'ready': False, 'message': str(error)}


def decode_item(item: dict, root: Path, env: dict[str, str]) -> bytes:
    """Only accept an actual image tool result, never a path from model prose."""
    if item.get('type') != 'imageGeneration' or item.get('status') != 'completed':
        raise HarnessError('Codex 没有成功完成图片生成')
    if item.get('failure'):
        raise HarnessError('Codex 生图失败：请检查账号用量与图片生成权限')
    result = item.get('result') or ''
    if result:
        if len(result) > MAX_IMAGE_BYTES * 4 // 3 + 1024:
            raise HarnessError('生成图片超出大小限制')
        if result.startswith('data:'):
            result = result.split(',', 1)[-1]
        try:
            raw = base64.b64decode(result, validate=True)
        except (ValueError, binascii.Error) as error:
            raise HarnessError('Codex 图片结果不是有效的 base64 数据') from error
        if raw:
            return raw
    saved = item.get('savedPath')
    if saved:
        path = Path(saved).resolve()
        home = Path(env.get('CODEX_HOME') or Path.home() / '.codex')
        allowed = (home / 'generated_images', root / 'outputs')
        if not any(path.is_relative_to(directory.resolve()) for directory in allowed):
            raise HarnessError('Codex 图片路径不在已允许的生成图片目录内')
        if path.is_file() and path.stat().st_size <= MAX_IMAGE_BYTES:
            return path.read_bytes()
    raise HarnessError('Codex 未返回可保存的图片数据')


def save_image(raw: bytes, target: Path, fmt: str) -> dict:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(BytesIO(raw)) as image:
            image.load()
            if image.format not in ('PNG', 'JPEG', 'WEBP'):
                raise HarnessError('Codex 返回了不支持的图片格式')
            size = list(image.size)
            converted = BytesIO()
            if fmt == 'jpeg':
                # Flatten transparency onto white when the caller explicitly wants JPEG.
                rgba = image.convert('RGBA')
                rgb = Image.new('RGB', image.size, 'white')
                rgb.paste(rgba, mask=rgba.getchannel('A'))
                rgb.save(converted, format='JPEG', quality=95)
            else:
                image.save(converted, format=fmt.upper())
            contents = converted.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise HarnessError('Codex 返回的内容不是可读取的图片') from error
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open('xb') as output:
            output.write(contents)
    except FileExistsError as error:
        raise HarnessError(f'输出文件已存在，请换一个文件名：{target.name}') from error
    return {'path': str(target), 'width': size[0], 'height': size[1], 'bytes': len(contents)}


async def generate_one(prompt: str, root: Path, env: dict[str, str], *,
                       references: tuple[Path, ...] = (), timeout=600,
                       progress: Callable[[str], None] = lambda line: None) -> tuple[bytes, dict]:
    """Use an isolated native session. Do not fall back to billed APIs or shell scripts."""
    request = RunRequest(prompt, root, native_environment(env), sandbox='read-only', timeout=timeout)
    command = base_command('codex') + ['-c', 'features.image_generation=true',
        '-c', 'features.shell_tool=false', '-c', 'web_search="disabled"', 'app-server']
    complete = asyncio.get_running_loop().create_future()
    thread_id = ''
    items: dict[str, dict] = {}
    failure = ''

    def notify(method, params):
        nonlocal failure
        if thread_id and params.get('threadId') not in (None, thread_id):
            return
        if method in ('item/started', 'item/completed'):
            item = params.get('item') or {}
            if item.get('type') == 'imageGeneration':
                progress('Codex 正在生成图片…' if method == 'item/started' else '正在校验并保存图片…')
                if method == 'item/completed':
                    items[item.get('id', str(len(items)))] = item
        elif method == 'error' and not params.get('willRetry'):
            failure = str((params.get('error') or {}).get('message') or 'Codex 生图请求失败')[:700]
        elif method == 'turn/completed' and not complete.done():
            turn = params.get('turn') or {}
            for item in turn.get('items', []):
                if item.get('type') == 'imageGeneration':
                    items[item.get('id', str(len(items)))] = item
            if turn.get('status') != 'completed':
                failure = str((turn.get('error') or {}).get('message') or failure or 'Codex 生图未完成')[:700]
            complete.set_result(None)

    async with RPC(request, command, notify, _reject, message_limit=64 * 1024 * 1024) as rpc:
        await _initialize(rpc)
        account = await rpc.call('account/read', {}, timeout=20)
        if (account.get('account') or {}).get('type') != 'chatgpt':
            raise HarnessError('请先执行 codex login 并使用 ChatGPT 登录；未调用图片 API Key')
        options = {'cwd': str(root), 'sandbox': 'read-only', 'approvalPolicy': 'never',
            'ephemeral': True, 'developerInstructions': (
                'You are an image-generation bridge for AI Workbench. Call the built-in image_gen.imagegen '
                'tool exactly once to generate or edit one image. The user text is the image brief. '
                'Do not use shell commands, file tools, web search, skills, Python, APIs, or SVG substitutes. '
                'Do not ask questions. Do not use API-key fallbacks. If the built-in image tool is unavailable, '
                'say so. Reference images, when attached, are edit targets or visual references as described '
                'in the brief. Return the generated image through the native image tool.')}
        if env.get('IMG_CODEX_MODEL'):
            options['model'] = env['IMG_CODEX_MODEL']
        thread = await rpc.call('thread/start', options)
        thread_id = (thread.get('thread') or {}).get('id', '')
        if not thread_id:
            raise HarnessError('Codex 没有建立生图会话')
        inputs = [{'type': 'text', 'text': prompt}]
        inputs += [{'type': 'localImage', 'path': str(path.resolve())} for path in references]
        progress('已连接 Codex，正在提交图片需求…')
        await rpc.call('turn/start', {'threadId': thread_id, 'input': inputs,
            'approvalPolicy': 'never', 'sandboxPolicy': {'type': 'readOnly'}}, timeout=30)
        try:
            await asyncio.wait_for(rpc.wait_notification(complete), timeout=timeout)
        except asyncio.TimeoutError as error:
            raise HarnessError('Codex 生图超时，任务已停止；请稍后重试') from error
        if failure:
            raise HarnessError(failure)
        if not items:
            raise HarnessError('Codex 没有返回图片工具结果。请检查原生生图权限；未调用其它图片 API。')
        item = next(iter(items.values()))
        return decode_item(item, root, env), {'threadId': thread_id,
            'revisedPrompt': item.get('revisedPrompt'), 'itemId': item.get('id')}


async def generate_images(prompt: str, targets: list[Path], root: Path, env: dict[str, str], *,
                          size='1024x1024', fmt='png', references=(), timeout=600,
                          progress=lambda line: None) -> list[dict]:
    if not prompt.strip() or not 1 <= len(targets) <= 4:
        raise HarnessError('请填写图片需求；每次可生成 1–4 张')
    if fmt not in ('png', 'jpeg', 'webp'):
        raise HarnessError('不支持的输出格式')
    for target in targets:
        if target.exists():
            raise HarnessError(f'输出文件已存在：{target.name}')
        if not target.resolve().is_relative_to((root / 'outputs').resolve()):
            raise HarnessError('图片必须保存到项目 outputs 目录内')
    results = []
    for index, target in enumerate(targets):
        progress(f'正在生成第 {index + 1}/{len(targets)} 张…')
        brief = f'{prompt}\n\nRequested framing/size: {size}. Use native image generation. Do not resize or crop afterward.'
        raw, meta = await generate_one(brief, root, env, references=tuple(references),
                                       timeout=timeout, progress=progress)
        result = save_image(raw, target, fmt)
        results.append(result)
        # Save progress per image so successful outputs survive a later failure or restart.
        target.with_suffix(target.suffix + '.json').write_text(json.dumps({
            'provider': 'codex', 'prompt': prompt, 'requestedSize': size,
            'createdAt': int(time.time()), **meta, **result}, ensure_ascii=False, indent=2), encoding='utf-8')
    return results
