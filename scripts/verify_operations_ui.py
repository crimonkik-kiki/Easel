"""End-to-end analytics UI on a disposable local server and simulated accounts only."""
from __future__ import annotations
import argparse
import asyncio
import json
from pathlib import Path
import socket
import sys
import threading
import time
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi import FastAPI
from fastapi.responses import FileResponse
import uvicorn
from web.operations import OperationsStore
from web.operations_api import register_operations


def run(dist, baseline=False):
    work = ROOT / 'tmp' / 'operations-ui'
    work.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix='isolated-', dir=work))
    app = FastAPI()
    rows = [{'platform': key, 'basePlatform': 'weixin-channels', 'name': name, 'nickname': name,
             'platformName': '微信视频号', 'loggedIn': True, 'registered': True}
            for key, name in [('fake-a', '模拟知识分享号'), ('fake-b', '模拟活动记录号')]]
    fetches = []
    async def accounts(): return rows
    async def collector(key):
        fetches.append(key)
        await asyncio.sleep(.05)
        if len(fetches) > 1:
            return {'loggedIn': False}
        return {'loggedIn': True, 'followers': 140, 'likes': 300, 'following': 10, 'posts': 2, 'notes': []}
    state = {'OUTPUTS_DIR': folder, 'api_accounts': accounts, 'ANALYTICS_PLATFORMS': {'weixin-channels'},
             '_assert_account_idle': lambda key: None, '_analytics_inflight': {}, '_ANALYTICS_BUSY': set(),
             '_fetch_analytics': collector}
    register_operations(app, lambda: state)
    store = OperationsStore(folder)
    now = int(time.time())
    for key, current, base in [('fake-a', 120, 100), ('fake-b', 350, 300)]:
        snapshots = [{'observed_at': now-32*86400, 'followers': base}]
        snapshots += [{'observed_at': now-days*86400-3600, 'followers': round(base+(current-base)*(1-days/30))}
                      for days in [25, 20, 15, 10, 5, 0]]
        works = [{'id': f'work-{i}', 'title': title, 'observed_at': now-3600,
                  'published_at': now-(i+1)*86400, 'views': 1000*(i+1), 'likes': 20*(i+1),
                  'comments': 5*(i+1), 'topics': [topic], 'url': f'https://example.invalid/{key}/{i}'}
                 for i, (title, topic) in enumerate([('AI 工具实战方法', 'AI实战'), ('本地社群活动回顾', '社群活动'), ('从问题到解决方案', 'AI实战')])]
        store.ingest(key, {'snapshots': snapshots, 'works': works})

    @app.get('/api/{path:path}')
    async def stub(path: str):
        if path == 'analytics/platforms': return []
        if 'whoami' in path or path.startswith(('analytics/', 'login/')):
            # Baseline can request legacy checks, but they are always synthetic.
            return {'loggedIn': False}
        if path == 'status': return {'gateway': True, 'transport': 'native', 'runtime': 'codex', 'personas': []}
        if path == 'settings/bootstrap': return {'modelConfigured': True}
        if path == 'accounts': return rows
        if path == 'trends': return {'trends': []}
        return []

    @app.get('/assets/{path:path}')
    async def asset(path: str):
        target = (dist / 'assets' / path).resolve()
        if (dist / 'assets').resolve() not in target.parents:
            raise ValueError('bad asset')
        return FileResponse(target)

    @app.get('/static/{path:path}')
    async def static_file(path: str):
        directory = (ROOT / 'web' / 'static').resolve()
        target = (directory / path).resolve()
        if directory not in target.parents or not target.is_file():
            from fastapi import HTTPException
            raise HTTPException(404)
        return FileResponse(target)

    @app.get('/')
    async def home(): return FileResponse(dist / 'index.html')

    listener = socket.socket(); listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='off'))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True);thread.start()
    deadline = time.monotonic()+15
    while not server.started:
        if time.monotonic()>deadline: raise TimeoutError('isolated server did not start')
        time.sleep(.02)
    from playwright.sync_api import sync_playwright, expect
    errors, violations = [], []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1080}, accept_downloads=True)
            context.add_init_script("localStorage.setItem('easel_onboarding_seen','1')")
            def guard(route):
                url = urlsplit(route.request.url)
                if url.hostname not in {'127.0.0.1', 'localhost'} or url.port != port:
                    if url.hostname not in {'fonts.googleapis.com', 'fonts.gstatic.com'}:
                        violations.append('external request blocked')
                    return route.abort()
                return route.continue_()
            context.route('**/*', guard)
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{port}/')
            if baseline:
                page.get_by_text('创作数据', exact=True).wait_for()
                page.screenshot(path=str(work/'baseline.png'), full_page=True)
                return {'baseline': 'captured', 'platform_visits': 0}
            panel = page.get_by_role('region', name='运营分析')
            expect(panel.get_by_role('heading', name='运营分析', exact=True)).to_be_visible()
            expect(panel.locator('.ops-kpis strong').first).to_have_text('470')
            assert fetches == []
            panel.scroll_into_view_if_needed()
            panel.screenshot(path=str(work/'overview.png'))
            panel.get_by_role('button', name='作品表现', exact=True).click()
            expect(panel.locator('tbody tr')).to_have_count(6)
            panel.get_by_label('搜索作品').fill('本地社群')
            expect(panel.locator('tbody tr')).to_have_count(2)
            panel.get_by_label('搜索作品').fill('')
            with page.expect_download() as download:
                panel.get_by_role('link', name='导出 CSV', exact=True).click()
            download.value.save_as(str(folder/'works.csv'))
            assert 'manual_import' in (folder/'works.csv').read_text(encoding='utf-8-sig')
            panel.screenshot(path=str(work/'works.png'))
            panel.get_by_role('button', name='复盘与洞察').click()
            expect(panel.get_by_role('heading', name='话题表现')).to_be_visible()
            panel.screenshot(path=str(work/'insights.png'))
            panel.get_by_label('分析账号').select_option('fake-a')
            expect(panel.locator('.ops-kpis strong').first).to_have_text('120')
            panel.get_by_role('button', name='导入数据', exact=True).click()
            content = f'kind,observed_at,followers\nsnapshot,{now-1800},130\n'
            panel.get_by_label('选择运营数据文件').set_input_files({'name':'fixture.csv','mimeType':'text/csv','buffer':content.encode()})
            panel.get_by_role('button', name='确认导入并保存').click()
            expect(panel.locator('.ops-kpis strong').first).to_have_text('130')
            page.reload()
            panel = page.get_by_role('region', name='运营分析')
            expect(panel.locator('.ops-kpis strong').first).to_have_text('480')
            assert fetches == []
            panel.get_by_label('分析账号').select_option('fake-a')
            expect(panel.locator('.ops-kpis strong').first).to_have_text('130')
            panel.get_by_role('button', name='导入数据', exact=True).click()
            invalid = f'kind,observed_at,followers\nsnapshot,{now-1000},-1\n'
            panel.get_by_label('选择运营数据文件').set_input_files({'name':'invalid.csv','mimeType':'text/csv','buffer':invalid.encode()})
            panel.get_by_role('button', name='确认导入并保存').click()
            expect(panel.get_by_role('alert')).to_be_visible()
            expect(panel.locator('.ops-kpis strong').first).to_have_text('130')
            expect(panel.get_by_text('已选 invalid.csv · 目标：模拟知识分享号')).to_be_visible()
            panel.get_by_role('button', name='同步此账号', exact=True).click()
            expect(panel.locator('.ops-kpis strong').first).to_have_text('140')
            assert fetches == ['fake-a']
            panel.get_by_role('button', name='同步此账号', exact=True).click()
            expect(panel.get_by_role('alert')).to_contain_text('登录态失效')
            expect(panel.locator('.ops-kpis strong').first).to_have_text('140')
            panel.get_by_role('button', name='重新读取本地报表').click()
            expect(panel.get_by_role('alert')).to_have_count(0)
            assert fetches == ['fake-a', 'fake-a']
            panel.get_by_role('button', name='导入数据', exact=True).click()
            page.set_viewport_size({'width': 390, 'height': 844})
            panel.evaluate("el => el.scrollIntoView({block:'start'})")
            expect(panel.get_by_role('heading', name='运营分析', exact=True)).to_be_visible()
            page.screenshot(path=str(work/'mobile.png'))
            panel.locator('.ops-definitions summary').click()
            expect(panel.get_by_text('粉丝合计未对不同账号的同一用户去重。')).to_be_visible()
            panel.locator('.ops-definitions').scroll_into_view_if_needed()
            page.screenshot(path=str(work/'mobile-bottom.png'))
            panel.locator('.ops-definitions summary').click()
            # Enlarge content without changing browser identity or device parameters.
            page.set_viewport_size({'width': 1440, 'height': 1080})
            page.locator('html').evaluate("el => el.style.zoom = '2'")
            panel.evaluate("el => el.scrollIntoView({block:'start'})")
            page.screenshot(path=str(work/'zoom-200.png'))
            page.locator('html').evaluate("el => el.style.zoom = ''")
            page.evaluate("document.documentElement.dataset.theme='dark'")
            panel.evaluate("el => el.scrollIntoView({block:'start'})")
            page.screenshot(path=str(work/'dark.png'))
            # Empty-account and real application failure states are also reachable.
            page.evaluate("document.documentElement.dataset.theme='light'")
            rows.append({'platform':'fake-empty','basePlatform':'weixin-channels','name':'模拟空账号',
                         'nickname':'模拟空账号','platformName':'微信视频号','loggedIn':False,'registered':True})
            page.reload()
            panel=page.get_by_role('region', name='运营分析')
            panel.get_by_label('分析账号').select_option('fake-empty')
            expect(panel.locator('.ops-kpis strong').first).to_have_text('—')
            panel.evaluate("el => el.scrollIntoView({block:'start'})")
            page.screenshot(path=str(work/'empty.png'))
            page.route('**/api/operations/report?account=fake-empty**', lambda route: route.fulfill(status=503, json={'detail':'模拟本地报表读取失败'}))
            panel.get_by_label('分析区间').select_option('7')
            expect(panel.get_by_role('alert')).to_contain_text('模拟本地报表读取失败')
            panel.evaluate("el => el.scrollIntoView({block:'start'})")
            page.screenshot(path=str(work/'error.png'))
            assert not errors and not violations, {'errors':errors,'violations':violations}
            context.close();browser.close()
        result = {'ui': 'passed', 'save_reload': 'passed', 'failed_import_preserves_data_and_file': 'passed',
                  'search_export': 'passed', 'manual_refresh_only': 'passed', 'simulated_collections': len(fetches),
                  'real_platform_visits': 0, 'production_data_writes': 0, 'isolated_data': str(folder)}
        (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        return result
    finally:
        server.should_exit=True;thread.join(timeout=10)


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--dist',type=Path,default=ROOT/'tmp/operations-ui-dist');parser.add_argument('--baseline',action='store_true')
    args=parser.parse_args();print(json.dumps(run(args.dist.resolve(),args.baseline),ensure_ascii=False))
