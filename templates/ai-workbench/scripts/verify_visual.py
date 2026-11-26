"""Exercise Easel shell states in an isolated copy, without invoking AI."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import uuid

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def verify():
    spec = importlib.util.spec_from_file_location('creator', ROOT / 'scripts/create_workbench.py')
    creator = importlib.util.module_from_spec(spec); spec.loader.exec_module(creator)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
    directory = ROOT.parent / '_verification' / ('visual-' + uuid.uuid4().hex[:8])
    target = creator.create(directory / 'workbench', 'Easel', port)
    from PIL import Image
    generated = target / 'outputs/generated'; generated.mkdir(parents=True)
    Image.new('RGB', (640, 360), '#eaf3fd').save(generated / 'visual-check.png')
    (generated / 'visual-check.md').write_text('# 界面验收产物\n这是隔离测试文件。', encoding='utf-8')
    evidence = ROOT / 'docs/evidence'; evidence.mkdir(exist_ok=True)
    env = {**os.environ, 'PYTHONUTF8': '1'}; env.pop('PYTHONPATH', None)
    log = (directory / 'server.log').open('w', encoding='utf-8')
    code = 'from pathlib import Path;import workbench;assert Path(workbench.__file__).resolve().is_relative_to(Path.cwd());from workbench.__main__ import main;main()'
    process = subprocess.Popen([str(ROOT / '.venv/Scripts/python.exe'), '-c', code, '--port', str(port)], cwd=target, env=env,
                               stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False, timeout=5) as client:
            for _ in range(100):
                assert process.poll() is None, 'isolated server exited'
                try:
                    if client.get('/api/health').is_success: break
                except httpx.HTTPError: pass
                time.sleep(.1)
            with sync_playwright() as p:
                browser = p.chromium.launch(channel='msedge', headless=True)
                context = browser.new_context(viewport={'width': 1440, 'height': 1000}, color_scheme='light')
                page = context.new_page(); errors = []; external = []
                page.on('pageerror', lambda e: errors.append(str(e)))

                def guard(route):
                    from urllib.parse import urlsplit
                    url = urlsplit(route.request.url)
                    if url.hostname != '127.0.0.1' or url.port != port:
                        external.append(route.request.url); route.abort()
                    else: route.continue_()

                context.route('**/*', guard)
                page.goto(f'http://127.0.0.1:{port}/')
                expect(page.get_by_role('heading', name='Easel', exact=True)).to_be_visible()
                expect(page.get_by_role('navigation', name='主导航').get_by_role('button', name='任务简报', exact=True)).to_be_visible()
                page.wait_for_function("document.querySelector('.sidebar-logo-icon')?.naturalWidth > 0")
                baseline = page.evaluate("""() => ({sidebarWidth: getComputedStyle(document.querySelector('.sidebar')).width, font: getComputedStyle(document.body).fontFamily, text: getComputedStyle(document.body).color, radius: getComputedStyle(document.documentElement).getPropertyValue('--radius'), accent: getComputedStyle(document.documentElement).getPropertyValue('--accent-start')})""")
                assert baseline['sidebarWidth'] == '264px'
                assert baseline['accent'].strip() == '#158f9a'
                page.screenshot(path=str(evidence / 'easel-home.png'), full_page=True, animations='disabled')
                nav = page.get_by_role('navigation', name='主导航')
                nav.get_by_role('button', name='对话', exact=True).click()
                expect(page.get_by_role('heading', name='今天，想一起完成什么？')).to_be_visible()
                page.screenshot(path=str(evidence / 'easel-chat-empty.png'), full_page=True, animations='disabled')
                page.get_by_label('任务内容', exact=True).fill('不提交的界面验收草稿')
                nav.get_by_role('button', name='AI 设置', exact=True).click()
                dialog = page.get_by_role('dialog', name='设置', exact=True)
                expect(dialog).to_be_visible()
                for tab in ['对话与脚本', '语音转写', '语音合成', '图片生成', '视频', '音乐']:
                    dialog.get_by_role('tab', name=tab, exact=True).click()
                    expect(dialog.get_by_role('tabpanel', name=tab, exact=True)).to_be_visible()
                dialog.get_by_role('tab', name='语音合成', exact=True).click()
                dialog.get_by_label('语音音色', exact=True).fill('visual-test-voice')
                dialog.get_by_role('button', name='保存 AI 配置', exact=True).click()
                expect(dialog.get_by_text('AI 配置已保存', exact=True)).to_be_visible()
                assert client.get('/api/settings').json()['channels']['speech']['voice'] == 'visual-test-voice'
                dialog.get_by_role('tab', name='对话与脚本', exact=True).click()
                dialog.get_by_label('执行引擎', exact=True).select_option('codex')
                expect(dialog.get_by_label('原生模型覆盖', exact=True)).to_be_visible()
                page.screenshot(path=str(evidence / 'easel-settings.png'), full_page=True, animations='disabled')
                page.keyboard.press('Escape'); expect(dialog).not_to_be_visible()
                expect(page.get_by_label('任务内容', exact=True)).to_have_value('不提交的界面验收草稿')
                nav.get_by_role('button', name='技能库', exact=True).click()
                expect(page.get_by_text('Easel 技能目录（114）', exact=True)).to_be_visible()
                page.screenshot(path=str(evidence / 'easel-skills.png'), full_page=True, animations='disabled')
                page.get_by_role('button', name='查看规范', exact=True).first.click()
                expect(page.get_by_role('dialog', name='技能规范', exact=True)).to_be_visible()
                page.keyboard.press('Escape')
                nav.get_by_role('button', name='内容库', exact=True).click()
                expect(page.locator('.gallery-grid .gcard')).to_have_count(2)
                page.wait_for_function("document.querySelector('.gcard-thumb img')?.naturalWidth === 640")
                page.screenshot(path=str(evidence / 'easel-files.png'), full_page=True, animations='disabled')
                with page.expect_download() as downloaded:
                    page.get_by_role('link', name='下载文件', exact=True).first.click()
                assert downloaded.value.suggested_filename.startswith('visual-check.')
                nav.get_by_role('button', name='工作台', exact=True).click()
                page.get_by_role('button', name='切换主题', exact=True).click()
                expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
                page.reload()
                expect(page.get_by_role('navigation', name='主导航').get_by_role('button', name='任务简报', exact=True)).to_be_visible()
                expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
                page.screenshot(path=str(evidence / 'easel-dark.png'), full_page=True, animations='disabled')
                nav.get_by_role('button', name='AI 设置', exact=True).click()
                expect(dialog).to_be_visible()
                page.screenshot(path=str(evidence / 'easel-settings-dark.png'), full_page=True, animations='disabled')
                page.get_by_role('button', name='关闭设置', exact=True).click()
                page.get_by_role('button', name='切换主题', exact=True).click()
                page.set_viewport_size({'width': 390, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                nav.get_by_role('button', name='对话', exact=True).click()
                page.screenshot(path=str(evidence / 'easel-mobile.png'), full_page=True, animations='disabled')
                nav.get_by_role('button', name='AI 设置', exact=True).click()
                expect(dialog).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                page.screenshot(path=str(evidence / 'easel-settings-mobile.png'), full_page=True, animations='disabled')
                assert not errors and not external, (errors, external)
                browser.close()
            assert client.get('/api/jobs').json() == []
            result = {'version': '0.3.0', 'passed': True, 'easel_tokens': baseline, 'six_channel_tabs': True,
                      'settings_save_and_readback': True, 'modal_escape_and_draft': True, 'skill_drawer': True,
                      'theme_refresh_restore': True, 'generated_gallery_and_download': True,
                      'mobile_overflow': False, 'ai_jobs': 0, 'external_browser_requests': 0}
            (evidence / 'visual-results-v03.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(result, ensure_ascii=False))
            client.post('/api/admin/stop').raise_for_status(); process.wait(timeout=15)
    finally:
        if process.poll() is None: process.terminate(); process.wait(timeout=10)
        log.close()


if __name__ == '__main__': verify()
