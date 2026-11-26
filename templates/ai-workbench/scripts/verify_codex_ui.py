"""Explicit real Codex smoke test: one tiny reply, read-only, no tools."""
from pathlib import Path
import importlib.util
import json
import os
import socket
import subprocess
import time
import uuid

import httpx
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def verify(tools=False):
    spec = importlib.util.spec_from_file_location('creator', ROOT / 'scripts/create_workbench.py')
    creator = importlib.util.module_from_spec(spec); spec.loader.exec_module(creator)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
    directory = ROOT.parent / '_verification' / ('codex-ui-' + uuid.uuid4().hex[:8])
    target = creator.create(directory / 'workbench', 'Codex 接入验收', port)
    log = (directory / 'server.log').open('w', encoding='utf-8')
    env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
    env.pop('PYTHONPATH', None)
    python = ROOT / '.venv/Scripts/python.exe'
    code = 'from pathlib import Path;import workbench;assert Path(workbench.__file__).resolve().is_relative_to(Path.cwd());from workbench.__main__ import main;main()'
    process = subprocess.Popen([str(python), '-c', code, '--port', str(port)], cwd=target, env=env,
        stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False, timeout=5) as client:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError('server exited; inspect ' + str(directory / 'server.log'))
                try:
                    if client.get('/api/health').status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
            with sync_playwright() as p:
                browser = p.chromium.launch(channel='msedge', headless=True)
                context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                errors = []; external = []
                def guard(route):
                    from urllib.parse import urlsplit
                    url = urlsplit(route.request.url)
                    if url.hostname not in ('127.0.0.1', 'localhost') or url.port != port:
                        external.append(route.request.url); route.abort()
                    else:
                        route.continue_()
                context.route('**/*', guard)
                page = context.new_page(); page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{port}/')
                nav = page.get_by_role('navigation', name='主导航')
                def go(name):
                    close = page.get_by_role('button', name='关闭设置', exact=True)
                    if close.is_visible(): close.click()
                    nav.get_by_role('button', name=name, exact=True).click()
                go('AI 设置')
                page.get_by_label('执行引擎', exact=True).select_option('codex')
                page.get_by_label('工具权限', exact=True).select_option('workspace-write' if tools else 'read-only')
                expect(page.get_by_label('原生模型覆盖', exact=True)).to_have_value('')
                page.get_by_role('button', name='保存 AI 配置', exact=True).click()
                expect(page.get_by_text('AI 配置已保存', exact=True)).to_be_visible()
                with page.expect_response(lambda response: response.url.endswith('/api/runtimes/codex/check')) as status:
                    page.get_by_role('button', name='检测所选引擎', exact=True).click()
                checked = status.value.json()
                if not checked.get('authenticated'):
                    raise RuntimeError(checked.get('message', 'Codex CLI auth unavailable'))
                go('对话')
                page.get_by_role('button', name='＋ 新对话', exact=True).click()
                # Fill immediately: the composer must wait for session creation,
                # rather than lose the typed content as its context changes.
                prompt='仅在工作区outputs/generated/template-check.txt中创建UTF-8文件，内容为：模板工具调用通过。不要读取其他文件，不使用网络。完成后只回复：模板工具调用通过。' if tools else '只回复“模板自检通过”。不读取、创建或修改任何文件，不调用任何工具。'
                expected='模板工具调用通过' if tools else '模板自检通过'
                page.get_by_label('任务内容', exact=True).fill(prompt)
                with page.expect_response(lambda response: response.url.endswith('/api/jobs') and response.request.method == 'POST') as submitted:
                    page.get_by_role('button', name='开始任务', exact=True).click()
                job_id = submitted.value.json()['id']
                expect(page.locator('.message.assistant').filter(has_text=expected).first).to_be_visible(timeout=120000)
                expect(page.locator('.job-result .badge')).to_have_text('已完成', timeout=15000)
                job = client.get('/api/jobs/' + job_id).json()
                assert job['state'] == 'completed' and job['runtime'] == 'codex' and job['model'] == ''
                assert job['sandbox'] == ('workspace-write' if tools else 'read-only') and not job['question']
                if tools:
                    file=target/'outputs/generated/template-check.txt'
                    assert file.is_file() and '模板工具调用通过' in file.read_text(encoding='utf-8-sig')
                    assert 'template-check.txt' in {row['path'] for row in client.get('/api/artifacts').json()}
                page.reload(); go('对话')
                expect(page.locator('.message.assistant').filter(has_text=expected).first).to_be_visible()
                assert not errors and not external, (errors, external)
                page.screenshot(path=str(ROOT / ('docs/evidence/codex-tools-ui.png' if tools else 'docs/evidence/codex-real-ui.png')), full_page=True, animations='disabled')
                context.close(); browser.close()
                result = {'real_codex_ui': 'passed', 'authenticated': True, 'native_model': 'default',
                          'sandbox': 'workspace-write' if tools else 'read-only', 'extra_permissions_approved': 0, 'generated_file_verified': tools, 'refresh_restores_reply': True,
                          'reply': job['text']}
                (ROOT / ('docs/evidence/codex-tools-ui.json' if tools else 'docs/evidence/codex-real-ui.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps(result, ensure_ascii=False))
    finally:
        try:
            httpx.post(f'http://127.0.0.1:{port}/api/admin/stop', trust_env=False, timeout=3)
            process.wait(timeout=15)
        except (httpx.HTTPError, subprocess.TimeoutExpired):
            if process.poll() is None:
                process.terminate(); process.wait(timeout=10)
        log.close()


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--tools',action='store_true')
    verify(parser.parse_args().tools)
