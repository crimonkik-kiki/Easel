import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/shared/scripts'))
import account_stats
from web.analytics_errors import collector_failure, safe_detail


def test_channels_stats_uses_login_edge_without_identity_or_legacy_proxy_overrides(monkeypatch):
    monkeypatch.setenv('EASEL_CHANNELS_BROWSER_CHANNEL', 'msedge')
    monkeypatch.setenv('EASEL_ACCOUNT_PROXY_MODE', 'inherit')
    options = account_stats._browser_options('weixin-channels', False, 'http://legacy.invalid:9999')
    assert options == {'channel': 'msedge', 'headless': True, 'args': []}
    assert account_stats._browser_options('weixin-channels', True, None)['headless'] is False


def test_channels_stats_has_native_default_and_rejects_invalid_channel(monkeypatch):
    monkeypatch.delenv('EASEL_CHANNELS_BROWSER_CHANNEL', raising=False)
    monkeypatch.setenv('EASEL_ACCOUNT_PROXY_MODE', 'inherit')
    assert account_stats._browser_options('weixin-channels', False, None)['channel'] == 'msedge'
    monkeypatch.setenv('EASEL_CHANNELS_BROWSER_CHANNEL', 'unknown-browser')
    with pytest.raises(ValueError, match='Unsupported'):
        account_stats._browser_options('weixin-channels', False, None)


def test_channels_stats_respects_account_network_choice(monkeypatch):
    monkeypatch.setenv('EASEL_ACCOUNT_PROXY_MODE', 'system')
    options = account_stats._browser_options('weixin-channels', False, 'http://legacy.invalid:9999')
    assert 'proxy' not in options
    assert options['args'] == []


@pytest.mark.parametrize('error, code', [
    ("ERROR: BrowserType.launch: Executable doesn't exist at C:/private/path\n╚═══╝", 'BROWSER_MISSING'),
    ('ERROR: Target page, context or browser has been closed\n[pid=99] exit', 'BROWSER_CLOSED'),
    ('ERROR: ProcessSingleton failed\n[pid=99] cleanup complete', 'PROFILE_BUSY'),
    ('ERROR: Page.goto: net::ERR_PROXY_CONNECTION_FAILED', 'NETWORK_ERROR'),
    ('ERROR: Page.goto: Timeout 12000ms exceeded', 'PAGE_TIMEOUT'),
])
def test_error_classification_reads_whole_trace_not_last_log_line(error, code):
    assert f'[{code}]' in collector_failure(error)


def test_collection_diagnostics_do_not_retain_credentials():
    detail = safe_detail('token=private-secret https://creator.invalid/?token=another Bearer hidden-auth')
    assert 'private-secret' not in detail and 'another' not in detail
    assert 'hidden-auth' not in detail
    assert '小红书登录目录正被占用' in collector_failure('ERROR: 小红书登录目录正被占用')
