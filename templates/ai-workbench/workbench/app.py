"""Portable FastAPI shell. No source Easel routes, accounts or login state."""
import asyncio
import hashlib
import os
from contextlib import asynccontextmanager
import importlib
import ipaddress
import json
from pathlib import Path
import re
import time
import uuid
from urllib.parse import urlsplit

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Config
from .engine import Engine, TERMINAL
from .harnesses.base import RunRequest
from .harnesses.commands import base_command
from .storage import Store, instance_lock


class JobInput(BaseModel):
    kind: str = 'chat'
    prompt: str = Field(default='', max_length=32000)
    session_id: str = ''
    skill: str = ''
    attachment: str = ''


def create_app(root=None):
    root = Path(root or Path(__file__).resolve().parents[1]).resolve()
    installation = hashlib.sha256(root.as_posix().casefold().encode('utf-8')).hexdigest()[:16]
    config = Config(root)
    modules = {}
    for name in config.brand.get('modules', []):
        if not re.fullmatch(r'workbench\.modules\.[a-z][a-z0-9_]*', name):
            raise ValueError('业务模块必须是本项目内受信任的Python模块')
        module = importlib.import_module(name)
        modules[module.DESCRIPTOR['id']] = module

    @asynccontextmanager
    async def lifespan(app):
        with instance_lock(root / 'outputs/_system/service.lock'):
            store = Store(root / 'outputs/_system/workbench.sqlite3')
            engine = Engine(config, store)
            for module in modules.values():
                if hasattr(module, 'register'):
                    module.register(engine)
            app.state.engine = engine; app.state.store = store
            engine.recover()
            try:
                yield
            finally:
                await engine.close(); store.close()

    app = FastAPI(title=config.brand.get('name', 'AI Workbench'), lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', '[::1]'])

    @app.middleware('http')
    async def local_guard(request, next_handler):
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            from fastapi.responses import JSONResponse
            try:
                peer = ipaddress.ip_address(request.client.host).is_loopback
            except ValueError:
                peer = False
            origin = request.headers.get('origin')
            expected = f'{request.url.scheme}://{request.url.netloc}'
            if not peer or (origin and origin not in (expected, 'http://127.0.0.1:5174', 'http://localhost:5174')):
                return JSONResponse({'detail': '只允许从本机工作台发起修改'}, status_code=403)
        return await next_handler(request)

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail': config.redact(str(error))}, status_code=400)

    @app.exception_handler(KeyError)
    async def missing(request, error):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail': '记录不存在'}, status_code=404)

    @app.get('/api/health')
    def health():
        return {'ok': True, 'instance': config.brand.get('id'), 'installation': installation,
                'pid': os.getpid(), 'version': '0.3.0'}

    @app.get('/api/bootstrap')
    def bootstrap():
        engine = app.state.engine
        return {'brand': {key: config.brand.get(key) for key in ('id', 'name', 'subtitle', 'logo', 'welcome_title', 'welcome_subtitle')},
                'navigation': config.brand.get('navigation', []),
                'runtimes': engine.runtimes(), 'skills': engine.skills.list(),
                'modules': [m.DESCRIPTOR for m in modules.values()], 'settings': config.public(),
                'capabilities': engine.capabilities()}

    @app.post('/api/admin/stop')
    async def stop():
        if any(job['state'] not in TERMINAL for job in app.state.store.list('job')):
            raise HTTPException(409, '仍有任务正在执行，请先停止任务再关闭工作台')
        callback = getattr(app.state, 'shutdown', None)
        if callback is None:
            raise HTTPException(501, '请使用 python -m workbench 启动，才能通过此入口停止')
        callback()
        return {'stopping': True}

    @app.get('/api/settings')
    def settings():
        return config.public()

    @app.put('/api/settings')
    async def save_settings(request: Request):
        if any(j['state'] not in TERMINAL for j in app.state.store.list('job')):
            raise HTTPException(409, '请先结束运行中的任务，再修改AI配置')
        return config.save(await request.json())

    @app.get('/api/sessions')
    def sessions():
        return app.state.store.list('session')

    @app.post('/api/models/{runtime}')
    async def models(runtime: str):
        if runtime == 'api':
            import httpx
            channel = config.read()['channels']['chat']
            if not channel['base_url']:
                raise ValueError('请先保存聊天API服务地址')
            headers = {'Authorization': 'Bearer ' + channel['key']} if channel['key'] else {}
            try:
                async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=15) as client:
                    response = await client.get(channel['base_url'].rstrip('/') + '/models', headers=headers)
                if response.status_code != 200:
                    raise ValueError(f'模型列表请求返回HTTP {response.status_code}；请核对地址、鉴权或手动填写模型名')
                rows = response.json()['data']
                return [{'id': row['id'], 'label': row['id']} for row in rows
                        if isinstance(row, dict) and isinstance(row.get('id'), str) and len(row['id']) < 240]
            except (httpx.HTTPError, KeyError, TypeError):
                raise ValueError('模型列表读取失败；部分服务不提供此接口，可手动填写模型名') from None
        if runtime not in ('codex', 'opencode'):
            raise ValueError('仅Codex与OpenCode支持原生模型读取；其他通道按服务商提供的名称填写')
        from .harnesses.models import available_models
        try:
            return await available_models(runtime, RunRequest('', root, config.environment(), sandbox='read-only'))
        except Exception:
            raise ValueError('模型列表读取失败，请检查原生CLI安装与认证；不会改动原生配置') from None

    @app.post('/api/runtimes/{runtime}/check')
    async def check_runtime(runtime: str):
        record = next((row for row in app.state.engine.runtimes() if row['id'] == runtime), None)
        if record is None:
            raise ValueError('执行引擎不存在')
        if not record['available']:
            return {'installed': False, 'authenticated': None,
                    'message': '未检测到可用安装或配置，请在当前Windows账户下安装CLI并配置；桌面App登录不等于CLI已认证。'}
        if runtime != 'codex':
            return {'installed': True, 'authenticated': None, 'message': '已检测到引擎配置；认证由对应Agent管理，此检查未发起AI任务。'}
        process = await asyncio.create_subprocess_exec(*base_command('codex'), 'login', 'status', cwd=root,
            env=config.environment(), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            creationflags=getattr(__import__('subprocess'), 'CREATE_NO_WINDOW', 0))
        try:
            await asyncio.wait_for(process.communicate(), 15)
        except asyncio.TimeoutError:
            if process.returncode is None:
                if os.name == 'nt':
                    cleanup = await asyncio.create_subprocess_exec('taskkill', '/PID', str(process.pid), '/T', '/F',
                        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                        creationflags=getattr(__import__('subprocess'), 'CREATE_NO_WINDOW', 0))
                    await cleanup.wait()
                else:
                    process.kill()
                await process.wait()
            raise ValueError('Codex登录状态检测超时；可在终端运行 codex login status 核对') from None
        authenticated = process.returncode == 0
        return {'installed': True, 'authenticated': authenticated,
                'message': 'Codex CLI已认证。保存设置后新建对话，模型覆盖留空可使用原生默认模型。' if authenticated else
                           'Codex CLI尚未认证。请在同一Windows账户的终端运行 codex login；完成后重新检测。不会自动复制桌面App凭据。'}

    @app.post('/api/sessions')
    def new_session():
        return app.state.engine.new_session()

    @app.patch('/api/sessions/{identifier}')
    async def rename_session(identifier: str, request: Request):
        body = await request.json()
        title = body.get('title') if isinstance(body, dict) else None
        if not isinstance(title, str) or not title.strip() or len(title) > 80:
            raise ValueError('对话名称需为1–80字')
        with app.state.store.mutex:
            session = app.state.store.get('session', identifier)
            session['title'] = title.strip()
            return app.state.store.put('session', session)

    @app.get('/api/sessions/{identifier}/export')
    def export_session(identifier: str):
        from fastapi.responses import Response
        session = app.state.store.get('session', identifier)
        text = '# ' + session['title'] + '\n\n' + '\n\n'.join(
            f"## {'用户' if row['role'] == 'user' else 'AI'}\n\n{row['content']}" for row in session['messages'])
        return Response(text, media_type='text/markdown', headers={'Content-Disposition': 'attachment; filename="conversation.md"'})

    @app.get('/api/skill-catalog')
    def skill_catalog():
        return app.state.engine.skills.catalog()

    @app.post('/api/skills')
    async def create_skill(request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError('技能内容必须是对象')
        return app.state.engine.skills.create(body.get('id', ''), body.get('text', ''))

    @app.get('/api/skills/{identifier}')
    def read_skill(identifier: str):
        return {'text': app.state.engine.skills.read(identifier)}

    @app.get('/api/jobs')
    def jobs():
        return app.state.store.list('job')[:100]

    @app.post('/api/jobs')
    async def submit(body: JobInput):
        return app.state.engine.submit(**body.model_dump())

    @app.get('/api/jobs/{identifier}')
    def job(identifier: str):
        return app.state.store.get('job', identifier)

    @app.post('/api/jobs/{identifier}/cancel')
    async def cancel(identifier: str):
        return app.state.engine.cancel(identifier)

    @app.post('/api/jobs/{identifier}/answer')
    async def answer(identifier: str, request: Request):
        body = await request.json()
        return app.state.engine.answer(identifier, body.get('question_id'), body.get('answers'))

    @app.get('/api/jobs/{identifier}/events')
    async def events(identifier: str, request: Request, after: int = 0):
        app.state.store.get('job', identifier)
        try:
            cursor = max(after, int(request.headers.get('last-event-id') or 0))
        except ValueError:
            raise HTTPException(400, '事件序号无效')

        async def stream():
            nonlocal cursor
            while not await request.is_disconnected():
                rows = app.state.store.events(identifier, cursor)
                for row in rows:
                    cursor = row['seq']
                    yield f'id: {cursor}\ndata: {json.dumps(row, ensure_ascii=False)}\n\n'
                if app.state.store.get('job', identifier)['state'] in TERMINAL and len(rows) < 500:
                    break
                if not rows:
                    yield ': heartbeat\n\n'
                await asyncio.sleep(.2)
        return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-store'})

    @app.post('/api/modules/{identifier}/run')
    async def run_module(identifier: str, request: Request):
        if identifier not in modules:
            raise HTTPException(404, '业务模块不存在')
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError('表单内容必须是对象')
        return app.state.engine.submit(prompt=modules[identifier].prompt(body), module_id=identifier)

    @app.post('/api/uploads')
    async def upload(file: UploadFile = File(...)):
        suffix = Path(file.filename or '').suffix.lower()
        if suffix not in ('.txt', '.md', '.csv', '.json', '.pdf', '.docx', '.xlsx', '.png', '.jpg', '.jpeg', '.webp', '.mp3', '.wav', '.m4a', '.mp4', '.webm', '.ogg', '.flac'):
            raise HTTPException(400, '文件格式不受支持')
        identifier = uuid.uuid4().hex
        folder = root / 'outputs/_uploads'; folder.mkdir(parents=True, exist_ok=True)
        target = folder / (identifier + suffix)
        size = 0
        try:
            with target.open('xb') as stream:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > 32 * 1024 * 1024:
                        raise HTTPException(413, '附件最大32MB')
                    stream.write(chunk)
            if not size:
                raise HTTPException(400, '附件为空')
            record = {'id': identifier, 'file': target.name, 'name': Path(file.filename).name, 'size': size}
            app.state.store.put('upload', record)
            return record
        except BaseException:
            target.unlink(missing_ok=True); raise
        finally:
            await file.close()

    @app.get('/api/artifacts')
    def artifacts():
        folder = root / 'outputs/generated'
        return [{'path': file.relative_to(folder).as_posix(), 'name': file.name,
                 'size': file.stat().st_size} for file in folder.rglob('*') if file.is_file()
                and file.resolve().is_relative_to(folder.resolve())
                and not any(part.startswith(('.', '_')) for part in file.relative_to(folder).parts)]

    @app.get('/api/artifacts/{name:path}')
    def artifact(name: str, preview: bool = False):
        folder = (root / 'outputs/generated').resolve(); target = (folder / name).resolve()
        if not target.is_relative_to(folder) or not target.is_file() or any(
                part.startswith(('.', '_')) for part in target.relative_to(folder).parts):
            raise HTTPException(404, '产物不存在')
        inline = preview and target.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.mp3', '.wav', '.m4a', '.mp4', '.webm')
        return FileResponse(target, filename=target.name, content_disposition_type='inline' if inline else 'attachment',
                            headers={'X-Content-Type-Options': 'nosniff'})

    dist = root / 'frontend/dist'
    if dist.is_dir():
        app.mount('/', StaticFiles(directory=dist, html=True), name='frontend')
    else:
        @app.get('/')
        def no_build():
            return {'message': '请运行 setup.ps1 构建前端，或使用含frontend/dist的发布包'}
    return app
