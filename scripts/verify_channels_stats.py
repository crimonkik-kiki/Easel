"""Exercise real Edge + stats parser + persistence against local synthetic HTML only."""
from contextlib import contextmanager, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'skills/shared/scripts')]
import account_stats
from playwright import sync_api
from web.operations import OperationsStore
from web.operations_api import collector_payload

folder = Path(tempfile.mkdtemp(prefix='channels-stats-', dir=ROOT / 'tmp'))
fixture = folder / 'fixture.html'
fixture.write_text('''<!doctype html><meta charset="utf-8">
<div class="finder-info"><div class="finder-nickname">模拟视频号</div></div>
<div class="finder-ui-desktop-menu">管理</div>
<p>关注者128</p><p>视频3</p><p>净增关注</p><p>2</p><p>新增播放</p><p>500</p>
<p>新增评论</p><p>6</p>''', encoding='utf-8')
account_stats.PLATFORMS['weixin-channels']['url'] = fixture.as_uri()
os.environ['EASEL_CHANNELS_BROWSER_CHANNEL'] = 'msedge'
os.environ['EASEL_ACCOUNT_PROXY_MODE'] = 'inherit'
os.environ['EASEL_ANALYTICS_NO_HISTORY'] = '1'
original = sync_api.sync_playwright
launches = []
blocked = []


@contextmanager
def local_playwright():
    with original() as playwright:
        def launch(profile, **options):
            launches.append(options)
            browser = playwright.chromium.launch_persistent_context(profile, **options)
            def guard(route):
                blocked.append(route.request.url.split(':', 1)[0])
                route.abort()
            browser.route('https://**/*', guard)
            browser.route('http://**/*', guard)
            return browser
        yield SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch))


sync_api.sync_playwright = local_playwright
with redirect_stdout(io.StringIO()) as output:
    code = account_stats.cmd_fetch(SimpleNamespace(platform='weixin-channels', headed=False,
        profile_base=str(folder / 'profiles'), no_proxy=False, proxy=None))
result = json.loads(output.getvalue())
assert code == 0 and result['loggedIn'] is True
assert result['followers'] == 128 and result['posts'] == 3
assert result['nickname'] == '模拟视频号'
assert launches == [{'channel':'msedge', 'headless':True, 'args':[]}]
payload, skipped = collector_payload(result)
store = OperationsStore(folder / 'outputs')
store.ingest('fake-video-account', payload, source='platform_readback')
report = store.report({'fake-video-account': {'name':'模拟视频号','platform':'weixin-channels'}})
assert report['summary']['followers'] == 128
evidence = {'result':'passed','browser':'msedge','followers':128,'posts':3,
            'account':'fake-video-account','platform_network_requests':0,'blocked_requests':len(blocked),
            'production_profile_accesses':0,'isolated_data':str(folder)}
(folder / 'result.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(evidence, ensure_ascii=False))
