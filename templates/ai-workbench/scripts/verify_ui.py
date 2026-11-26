"""Relocate the template and exercise its real UI with offline providers only."""
import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import uuid

import httpx
from PIL import Image
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def verify(python):
    spec = importlib.util.spec_from_file_location('scaffold', ROOT / 'scripts/create_workbench.py')
    scaffold = importlib.util.module_from_spec(spec); spec.loader.exec_module(scaffold)
    directory = ROOT.parent / '_verification' / uuid.uuid4().hex[:10]
    port = free_port()
    clone = scaffold.create(directory / 'relocated-workbench', '独立工作台验收', port)
    evidence = ROOT / 'docs/evidence'; evidence.mkdir(exist_ok=True)
    png = io.BytesIO(); Image.new('RGB', (64, 64), '#3f56a8').save(png, format='PNG')
    calls = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
            self.wfile.write(json.dumps({'data':[{'id':'offline-test-model'}]}).encode())

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            calls.append(self.path)
            self.send_response(200)
            if self.path.endswith('/chat/completions'):
                self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
                for text in ['已完成离线', '界面验证。']:
                    self.wfile.write(('data: ' + json.dumps({'choices': [{'delta': {'content': text}, 'finish_reason': None}]}) + '\n\n').encode()); self.wfile.flush()
                self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
            else:
                self.send_header('Content-Type', 'application/json'); self.end_headers()
                self.wfile.write(json.dumps({'data': [{'b64_json': base64.b64encode(png.getvalue()).decode()}]}).encode())

    provider = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    thread = threading.Thread(target=provider.serve_forever, daemon=True); thread.start()
    config_dir = clone / 'outputs/_harness'; config_dir.mkdir(parents=True)
    (config_dir / 'acp.json').write_text(json.dumps({'command': [str(python), str(clone / 'tests/fixtures/harness_rpc.py'), 'acp']}), encoding='utf-8')
    env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8',
           'FAKE_HARNESS_AUDIT': str(clone / 'outputs/_harness/offline-audit.jsonl'), 'FAKE_HARNESS_MODE': 'permission'}
    # Ensure the process imports code from the relocated clone, not an editable
    # install or the original Easel application. No PYTHONPATH back-reference.
    env.pop('PYTHONPATH', None)
    code = "from pathlib import Path;import workbench;assert Path(workbench.__file__).resolve().is_relative_to(Path.cwd());from workbench.__main__ import main;main()"
    log = (directory / 'server.log').open('w', encoding='utf-8')
    process = subprocess.Popen([str(python), '-c', code, '--port', str(port)], cwd=clone, env=env,
                               stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    results = []
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False, timeout=5) as client:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError('Relocated server exited; see ' + str(directory / 'server.log'))
                try:
                    if client.get('/api/health').status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
            else:
                raise RuntimeError('Relocated server unavailable')
            response = client.put('/api/settings', json={'channels': {
                name: {'base_url': f'http://127.0.0.1:{provider.server_port}/v1', 'model': 'offline-test-model', 'key': 'offline-test-only'}
                for name in ('chat', 'image')}})
            response.raise_for_status()
            with sync_playwright() as p:
                browser = p.chromium.launch(channel='msedge', headless=True)
                for run in range(3):
                    context = browser.new_context(viewport={'width':1440, 'height':1000})
                    errors, external = [], []
                    def guard(route):
                        from urllib.parse import urlsplit
                        parsed = urlsplit(route.request.url)
                        if parsed.hostname not in ('127.0.0.1', 'localhost') or parsed.port != port:
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
                    expect(page.get_by_text('独立工作台验收', exact=True)).to_be_visible()
                    if run == 0:
                        page.screenshot(path=str(evidence / 'desktop.png'), full_page=True, animations='disabled')
                    go('AI 设置')
                    page.get_by_label('执行引擎', exact=True).select_option('api')
                    page.get_by_label('助手指令').fill('保持独立工作台的配置与上下文。')
                    page.get_by_role('button', name='保存 AI 配置', exact=True).click()
                    expect(page.get_by_text('AI 配置已保存', exact=True)).to_be_visible()
                    expect(page.get_by_label('对话与脚本 key', exact=True)).to_have_value('')
                    page.reload(); go('AI 设置')
                    expect(page.get_by_label('助手指令')).to_have_value('保持独立工作台的配置与上下文。')
                    page.get_by_role('button',name='读取 API 模型',exact=True).click()
                    expect(page.get_by_text('已读取可用模型，可在聊天模型输入框中选择',exact=True)).to_be_visible()
                    go('技能库')
                    page.get_by_text('新增或导入提示词技能',exact=True).click()
                    page.get_by_label('新技能标识',exact=True).fill(f'ui-test-{run}')
                    page.get_by_label('导入技能文档',exact=True).set_input_files({'name':'SKILL.md','mimeType':'text/markdown','buffer':'# 测试工作流\n提取行动项。'.encode()})
                    expect(page.get_by_label('新技能规范',exact=True)).to_have_value('# 测试工作流\n提取行动项。')
                    page.get_by_role('button',name='保存新技能',exact=True).click()
                    expect(page.get_by_role('heading',name='测试工作流',exact=True).first).to_be_visible()
                    page.get_by_text('Easel 技能目录（114）',exact=True).click()
                    page.get_by_label('搜索技能目录',exact=True).fill('text-polisher')
                    expect(page.locator('.job-row').filter(has=page.locator('strong',has_text=__import__('re').compile('^text-polisher$'))).get_by_text('已装载',exact=True)).to_be_visible()
                    go('对话')
                    page.get_by_label('使用技能', exact=True).select_option('text-condenser')
                    page.get_by_label('任务内容', exact=True).fill(f'第{run + 1}轮：总结一下任务目标。')
                    page.get_by_role('button', name='开始任务', exact=True).click()
                    expect(page.get_by_text('已完成离线界面验证。', exact=True).first).to_be_visible()
                    page.reload(); go('对话')
                    expect(page.get_by_text('已完成离线界面验证。', exact=True).first).to_be_visible()
                    page.get_by_label('对话名称',exact=True).fill(f'验收对话{run}')
                    page.get_by_role('button',name='重命名',exact=True).click()
                    expect(page.get_by_role('button',name=f'验收对话{run} api',exact=True)).to_be_visible()
                    with page.expect_download() as download_info:page.get_by_role('link',name='导出对话',exact=True).click()
                    assert download_info.value.suggested_filename=='conversation.md'
                    page.get_by_label('任务内容',exact=True).fill('聊天页未提交草稿')
                    go('AI 媒体')
                    expect(page.get_by_label('任务内容',exact=True)).to_have_value('')
                    page.get_by_label('任务内容',exact=True).fill('媒体页未提交草稿')
                    go('对话')
                    expect(page.get_by_label('任务内容',exact=True)).to_have_value('聊天页未提交草稿')
                    go('AI 媒体')
                    expect(page.get_by_label('任务内容',exact=True)).to_have_value('媒体页未提交草稿')
                    page.get_by_role('button',name='视频',exact=True).click()
                    expect(page.get_by_role('button',name='开始任务',exact=True)).to_be_disabled()
                    page.get_by_role('button',name='图片生成',exact=True).click()
                    page.get_by_label('任务内容', exact=True).fill('创建一张测试图片')
                    with page.expect_response(lambda response: response.url.endswith('/api/jobs') and response.request.method=='POST') as submitted:
                        page.get_by_role('button', name='开始任务', exact=True).click()
                    new_image_id=submitted.value.json()['id']
                    expect(page.locator('.job-result')).to_have_attribute('data-job-id',new_image_id)
                    expect(page.get_by_role('link', name='下载 image.png', exact=True)).to_be_visible()
                    page.wait_for_function("document.querySelector('.artifact-preview img')?.naturalWidth===64")
                    go('任务简报')
                    page.get_by_label('需求内容', exact=True).fill('整理客户资料，输出一份摘要。')
                    page.get_by_role('button', name='生成简报', exact=True).click()
                    expect(page.get_by_text('已完成离线界面验证。', exact=True).first).to_be_visible()
                    go('任务记录')
                    page.locator('.job-row').filter(has_text='将下列需求整理为可执行的工作简报').first.click()
                    expect(page.get_by_role('heading',name='任务详情',exact=True)).to_be_visible()
                    expect(page.get_by_text('已完成离线界面验证。',exact=True).first).to_be_visible()
                    page.reload()
                    expect(page.get_by_role('heading',name='任务详情',exact=True)).to_be_visible()
                    expect(page.get_by_text('已完成离线界面验证。',exact=True).first).to_be_visible()
                    go('AI 设置')
                    page.get_by_label('执行引擎', exact=True).select_option('acp')
                    page.get_by_role('button', name='保存 AI 配置', exact=True).click()
                    expect(page.get_by_text('AI 配置已保存', exact=True)).to_be_visible()
                    go('对话')
                    page.get_by_role('button', name='＋ 新对话', exact=True).click()
                    page.get_by_label('任务内容', exact=True).fill('执行一次离线权限确认测试')
                    page.get_by_role('button', name='开始任务', exact=True).click()
                    confirmation = page.locator('.confirmation')
                    expect(confirmation.get_by_text('需要你的确认', exact=True)).to_be_visible()
                    confirmation.locator('select').select_option(label='1. Allow')
                    with page.expect_response(lambda response: response.url.endswith('/api/jobs') and response.request.method=='GET'):
                        pass
                    expect(confirmation.locator('select')).to_have_value('1. Allow')
                    confirmation.get_by_role('button', name='提交确认', exact=True).click()
                    expect(page.get_by_text('你好', exact=True).first).to_be_visible()
                    if run == 0:
                        page.screenshot(path=str(evidence / 'conversation.png'), full_page=True, animations='disabled')
                        page.set_viewport_size({'width': 390, 'height': 844})
                        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 2')
                        page.screenshot(path=str(evidence / 'mobile.png'), full_page=True, animations='disabled')
                    assert not errors and not external, (errors, external)
                    results.append({'run': run + 1, 'passed': True, 'external_browser_requests': 0,
                                    'real_ai_requests': 0, 'relocated_instance': True})
                    context.close()
                browser.close()
        (evidence / 'ui-results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        print(json.dumps({'results': results, 'relocated_root': str(clone), 'server_python': str(python), 'provider_calls': len(calls)}))
    finally:
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=15)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        log.close(); provider.shutdown(); thread.join(timeout=3); provider.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', default=str(ROOT / '.venv/Scripts/python.exe'))
    args = parser.parse_args()
    verify(Path(args.python).resolve())
