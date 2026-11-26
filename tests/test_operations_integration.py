import asyncio
import json
import subprocess
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
import web.app as web


@pytest.fixture
def account(monkeypatch, tmp_path):
    cfg = {'name': '模拟视频号', 'backend': 'web', 'basePlatform': 'weixin-channels',
           'profile_base': str(tmp_path / 'fake-profile'), 'registered': True}
    monkeypatch.setattr(web, 'OUTPUTS_DIR', tmp_path)
    monkeypatch.setattr(web, 'LOGIN_RUNNERS', {'fake-one': cfg, 'fake-two': {**cfg, 'profile_base': str(tmp_path/'second')}})
    monkeypatch.setattr(web, '_sync_managed_accounts', lambda: {
        'metadata': {key: {'registered': True} for key in ('fake-one', 'fake-two')}, 'accounts': [], 'active': {}})
    monkeypatch.setattr(web, '_account_logged_in', lambda *args: True)
    monkeypatch.setattr(web, '_ANALYTICS_BUSY', set())
    monkeypatch.setattr(web, '_analytics_inflight', {})
    return tmp_path


def test_collector_uses_selected_profile_and_separate_cache(account, monkeypatch):
    calls = []
    def collect(cmd, env, timeout):
        calls.append((cmd, env))
        return subprocess.CompletedProcess(cmd, 0, json.dumps({'loggedIn': True, 'followers': 0}), '')
    monkeypatch.setattr(web, '_run_analytics_command', collect)
    for key in ['fake-one', 'fake-two']:
        asyncio.run(web._fetch_analytics(key))
    for cmd, env in calls:
        assert cmd[cmd.index('--platform')+1] == 'weixin-channels'
        assert '--profile-base' in cmd and env['EASEL_ANALYTICS_NO_HISTORY'] == '1'
    assert calls[0][0][-1] != calls[1][0][-1]
    assert calls[0][1]['EASEL_ANALYTICS_DIR'] != calls[1][1]['EASEL_ANALYTICS_DIR']


@pytest.mark.parametrize('action', ['api_account_whoami', 'api_logout', '_start_login'])
def test_account_actions_block_while_collecting(account, action):
    web._ANALYTICS_BUSY.add('fake-one')
    with pytest.raises(HTTPException) as error:
        asyncio.run(getattr(web, action)('fake-one'))
    assert error.value.status_code == 409


def test_removed_operations_routes_are_unavailable(account, monkeypatch):
    monkeypatch.setattr(web, '_run_analytics_command', lambda *args: pytest.fail('GET must not collect'))
    with TestClient(web.app, base_url='http://127.0.0.1') as client:
        for url in ('/api/operations/accounts', '/api/operations/report?account=fake-one',
                    '/api/operations/export?account=fake-one&kind=report'):
            assert client.get(url).status_code == 404
        assert client.post('/api/operations/fake-one/refresh', headers={'Origin': 'http://127.0.0.1:7860'}).status_code == 404


def test_collectors_no_history_mode_does_not_write_platform_history(monkeypatch, capsys):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'skills/shared/scripts'))
    import account_stats
    monkeypatch.setenv('EASEL_ANALYTICS_NO_HISTORY', '1')
    monkeypatch.setattr(account_stats, '_scrape', lambda *args: {'logged_in': True, 'followers': 0, 'likes': None,
        'following': None, 'posts': None, 'metrics': [], 'notes': [], 'nickname': '模拟'})
    monkeypatch.setattr(account_stats, 'load_history', lambda *args: pytest.fail('legacy read'))
    monkeypatch.setattr(account_stats, 'record_snapshot', lambda *args: pytest.fail('legacy write'))
    assert account_stats.cmd_fetch(SimpleNamespace(platform='weixin-channels', no_proxy=True, proxy=None,
        headed=False, profile_base='fake')) == 0
    assert json.loads(capsys.readouterr().out)['followers'] == 0
