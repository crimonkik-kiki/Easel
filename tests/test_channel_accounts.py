import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import web.app as web
from web import channel_accounts


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(web, 'OUTPUTS_DIR', tmp_path)
    monkeypatch.setattr(web, 'LOGIN_DIR', tmp_path / '_login')
    monkeypatch.setattr(web, 'BROWSER_PROFILES', tmp_path / 'legacy-profiles')
    monkeypatch.setattr(web, 'LOGIN_RUNNERS', copy.deepcopy(web.LOGIN_RUNNERS))
    monkeypatch.setattr(web, 'LOGIN_PROCESSES', {})
    monkeypatch.setattr(web, '_WHOAMI_CACHE', {})
    monkeypatch.setattr(web, '_WHOAMI_TASKS', {})
    monkeypatch.setattr(web, '_LOGIN_START_LOCKS', {})
    monkeypatch.setattr(web, '_CHANNEL_PUBLISHING', set())
    return tmp_path


def create(label):
    return asyncio.run(web.api_channel_account_create(web.ChannelAccountRequest(label=label)))['platform']


def test_create_rename_select_survive_reload_preserving_default(state):
    web._write_login_marker('weixin-channels', 'success', 'Existing channel')
    original = (web.LOGIN_DIR / 'weixin-channels.json').read_bytes()
    first, second = create('品牌号'), create('个人号')
    assert first != second
    asyncio.run(web.api_channel_account_rename(first, web.ChannelAccountRequest(label='品牌主号')))
    asyncio.run(web.api_channel_account_select(first))
    data = channel_accounts.read(state)
    assert data['active'] == first
    assert next(item for item in data['accounts'] if item['key'] == first)['label'] == '品牌主号'
    web._sync_channel_accounts()
    assert web.LOGIN_RUNNERS[first]['active']
    assert 'profile_base' not in web.LOGIN_RUNNERS['weixin-channels']
    assert (web.LOGIN_DIR / 'weixin-channels.json').read_bytes() == original
    assert web.LOGIN_RUNNERS[first]['profile_base'] != web.LOGIN_RUNNERS[second]['profile_base']


def test_two_logins_have_separate_browser_and_status_paths(state, monkeypatch):
    first, second = create('A'), create('B')
    launch = Mock(side_effect=lambda *args, **kwargs: SimpleNamespace(poll=lambda: None))
    monkeypatch.setattr(web.subprocess, 'Popen', launch)
    for key in (first, second):
        asyncio.run(web.api_login_start(key))
    commands = [call.args[0] for call in launch.call_args_list]
    for key, command in zip((first, second), commands):
        assert command[command.index('--platform') + 1] == 'weixin-channels'
        assert command[command.index('--profile-base') + 1] == str(channel_accounts.profile_base(state, key))
        assert command[command.index('--status-file') + 1] == str(web.LOGIN_DIR / (key + '.json'))
    assert set(web.LOGIN_PROCESSES) == {first, second}


def test_whoami_uses_selected_identity_without_cross_account_cache(state, monkeypatch):
    first, second = create('A'), create('B')
    def run(command, **kwargs):
        base = command[command.index('--profile-base') + 1]
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            'loggedIn': True, 'name': 'A' if first in base else 'B', 'avatar': ''}))
    monkeypatch.setattr(web.subprocess, 'run', run)
    assert asyncio.run(web.api_account_whoami(first))['name'] == 'A'
    assert asyncio.run(web.api_account_whoami(second))['name'] == 'B'
    assert web._WHOAMI_CACHE[first][1]['name'] != web._WHOAMI_CACHE[second][1]['name']
    web._WHOAMI_CACHE.clear()
    rows = {a['platform']: a for a in asyncio.run(web.api_accounts())}
    assert rows[first]['nickname'] == 'A' and rows[second]['nickname'] == 'B'


def test_publish_targets_explicit_account_even_if_other_is_active(state, monkeypatch):
    first, second = create('A'), create('B')
    web._write_login_marker(first, 'success')
    (state / 'clip.mp4').write_bytes(b'test-media')
    launch = Mock(return_value=SimpleNamespace(returncode=0, stdout='', stderr=''))
    monkeypatch.setattr(web.subprocess, 'run', launch)
    monkeypatch.setattr(web, '_read_schedule', lambda: [])
    monkeypatch.setattr(web, '_write_schedule', lambda items: None)
    result = asyncio.run(web.api_publish(first, web.PublishRequest(title='Test', media=['clip.mp4'])))
    assert result['ok']
    command = launch.call_args.args[0]
    assert command[command.index('--platform') + 1] == 'weixin-channels'
    assert command[command.index('--profile-base') + 1] == str(channel_accounts.profile_base(state, first))
    assert second not in ' '.join(command)


def test_alias_publish_requires_video_and_own_login(state, monkeypatch):
    key = create('A')
    launch = Mock()
    monkeypatch.setattr(web.subprocess, 'run', launch)
    with pytest.raises(web.HTTPException):
        asyncio.run(web.api_publish(key, web.PublishRequest(title='Test')))
    web._write_login_marker(key, 'success')
    with pytest.raises(web.HTTPException, match='视频'):
        asyncio.run(web.api_publish(key, web.PublishRequest(title='Test')))
    launch.assert_not_called()


def test_logout_clears_only_one_profile(state):
    first, second = create('A'), create('B')
    for key in (first, second):
        directory = Path(web.LOGIN_RUNNERS[key]['profile_base']) / 'ChannelsProfile'
        directory.mkdir(parents=True)
        (directory / 'cookies-test').write_text(key)
        web._write_login_marker(key, 'success')
    asyncio.run(web.api_logout(first))
    assert not (Path(web.LOGIN_RUNNERS[first]['profile_base']) / 'ChannelsProfile').exists()
    assert (Path(web.LOGIN_RUNNERS[second]['profile_base']) / 'ChannelsProfile' / 'cookies-test').exists()
    assert (web.LOGIN_DIR / (second + '.json')).exists()


@pytest.mark.parametrize('key', ['../escape', 'weixin-channels--../x', 'weixin-channels--not-a-valid-id'])
def test_profile_path_rejects_traversal(state, key):
    with pytest.raises(ValueError):
        channel_accounts.profile_base(state, key)


def test_publish_busy_blocks_login_and_logout_per_account(state):
    first, second = create('A'), create('B')
    web._CHANNEL_PUBLISHING.add(first)
    for action in (web.api_login_start, web.api_logout, web.api_account_whoami):
        with pytest.raises(web.HTTPException) as error:
            asyncio.run(action(first))
        assert error.value.status_code == 409
    assert second not in web._CHANNEL_PUBLISHING


@pytest.mark.parametrize('base', ['xiaohongshu', 'douyin', 'kuaishou', 'weixin-channels', 'zhihu'])
def test_managed_account_isolation_metadata_and_publisher(state, monkeypatch, base):
    monkeypatch.setattr(web, 'PUBLISH_DIR', state / '_publish')
    def add(label):
        return asyncio.run(web.api_managed_create(web.ManagedAccountCreate(
            platform=base, label=label, group='品牌组', remark='运营备注')))['platform']
    first, second = add('主号'), add('副号')
    asyncio.run(web.api_managed_edit(first, web.ManagedAccountEdit(label='改名主号', group='品牌组', remark='新备注')))
    asyncio.run(web.api_managed_select(first))
    rows = asyncio.run(web.api_accounts())
    assert next(row for row in rows if row['platform'] == first)['active']
    assert not next(row for row in rows if row['platform'] == second)['active']
    assert web.LOGIN_RUNNERS[first]['group'] == '品牌组'
    assert web.LOGIN_RUNNERS[first]['accountLabel'] == '改名主号'
    assert web.LOGIN_RUNNERS[first]['profile_base'] != web.LOGIN_RUNNERS[second]['profile_base']
    assert 'profile_base' not in web.LOGIN_RUNNERS[base]
    launch = Mock(return_value=SimpleNamespace(poll=lambda: None))
    monkeypatch.setattr(web.subprocess, 'Popen', launch)
    asyncio.run(web.api_login_start(first))
    login_cmd = launch.call_args.args[0]
    assert login_cmd[login_cmd.index('--profile-base') + 1] == web.LOGIN_RUNNERS[first]['profile_base']
    assert first in login_cmd[login_cmd.index('--status-file') + 1]
    web.LOGIN_PROCESSES.clear()
    web._write_login_marker(first, 'success')
    web._write_login_marker(second, 'success')
    (state / 'clip.mp4').write_bytes(b'test-media')
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout='', stderr=''))
    monkeypatch.setattr(web.subprocess, 'run', run)
    monkeypatch.setattr(web, '_read_schedule', lambda: [])
    monkeypatch.setattr(web, '_write_schedule', lambda items: None)
    async_start = Mock(return_value={'async': True})
    monkeypatch.setattr(web, '_start_async_publish', async_start)
    asyncio.run(web.api_publish(second, web.PublishRequest(title='Test', media=['clip.mp4'])))
    if base == 'douyin':
        cmd = async_start.call_args.args[1]
        assert second in cmd[cmd.index('--status-file') + 1]
        assert second in cmd[cmd.index('--sms-code-file') + 1]
    else:
        cmd = run.call_args.args[0]
    assert cmd[cmd.index('--profile-base') + 1] == web.LOGIN_RUNNERS[second]['profile_base']
    assert first not in ' '.join(cmd)
    if base in ('xiaohongshu', 'douyin'):
        assert base.replace('xiaohongshu', 'xhs') + '_publish.py' in cmd[1]
    else:
        assert cmd[cmd.index('--platform') + 1] == base


def test_account_metadata_does_not_clear_existing_login(state):
    web._write_login_marker('xiaohongshu', 'success', 'Existing')
    marker = (web.LOGIN_DIR / 'xiaohongshu.json').read_bytes()
    asyncio.run(web.api_managed_edit('xiaohongshu', web.ManagedAccountEdit(label='原小红书', group='原有账号')))
    assert (web.LOGIN_DIR / 'xiaohongshu.json').read_bytes() == marker
    assert 'profile_base' not in web.LOGIN_RUNNERS['xiaohongshu']
    assert web.LOGIN_RUNNERS['xiaohongshu']['accountLabel'] == '原小红书'


def test_async_publish_reserves_and_releases_only_its_account(state, monkeypatch):
    monkeypatch.setattr(web, 'PUBLISH_DIR', state / '_publish')
    key = asyncio.run(web.api_managed_create(web.ManagedAccountCreate(platform='douyin', label='A')))['platform']
    thread = Mock()
    monkeypatch.setattr(web.threading, 'Thread', Mock(return_value=thread))
    status, code = web.PUBLISH_DIR / (key + '.json'), web.PUBLISH_DIR / (key + '.code')
    result = web._start_async_publish(key, ['runner'], 'Test', '', web.LOGIN_RUNNERS[key], status, code)
    assert result['async'] and key in web._CHANNEL_PUBLISHING
    for action in (web.api_login_start, web.api_logout, web.api_account_whoami):
        with pytest.raises(web.HTTPException) as error:
            asyncio.run(action(key))
        assert error.value.status_code == 409
    monkeypatch.setattr(web.subprocess, 'run', Mock(return_value=SimpleNamespace(returncode=1, stdout='', stderr='Test failure')))
    web._run_publish_bg(key, ['runner'], 'Test', '', web.LOGIN_RUNNERS[key], status, code)
    assert key not in web._CHANNEL_PUBLISHING
    assert web._read_publish_status(key)['state'] == 'error'


def test_open_backend_uses_account_profile_and_blocks_conflicting_work(state, monkeypatch):
    key = asyncio.run(web.api_managed_create(web.ManagedAccountCreate(platform='xiaohongshu', label='A')))['platform']
    with pytest.raises(web.HTTPException):
        asyncio.run(web.api_managed_open(key))
    web._write_login_marker(key, 'success')
    launch = Mock(return_value=SimpleNamespace(poll=lambda: None))
    monkeypatch.setattr(web.subprocess, 'Popen', launch)
    result = asyncio.run(web.api_managed_open(key))
    assert result['ok']
    cmd = launch.call_args.args[0]
    assert cmd[cmd.index('--platform') + 1] == 'xiaohongshu'
    assert cmd[cmd.index('--profile') + 1] == str((Path(web.LOGIN_RUNNERS[key]['profile_base']) / 'XiaohongshuProfile').resolve())
    assert key in web.LOGIN_PROCESSES
    with pytest.raises(web.HTTPException) as error:
        asyncio.run(web.api_managed_open(key))
    assert error.value.status_code == 409
    with pytest.raises(web.HTTPException):
        asyncio.run(web.api_logout(key))


def test_existing_account_stays_registered_after_login_expires(state):
    web._write_login_marker('xiaohongshu', 'success', 'Existing')
    asyncio.run(web.api_accounts())
    (web.LOGIN_DIR / 'xiaohongshu.json').unlink()
    row = next(row for row in asyncio.run(web.api_accounts()) if row['platform'] == 'xiaohongshu')
    assert row['registered'] and not row['loggedIn']



def test_card_settings_persist_rename_and_apply_to_publish(state, monkeypatch):
    key = create('A')
    monkeypatch.setattr(web, 'list_personas', lambda: [{'name': '品牌定位'}])
    settings = web.AccountCardSettings(persona='品牌定位', default_tags='AI,学习', content_suffix='品牌署名', proxy_mode='fixed', proxy_url='http://127.0.0.1:7890')
    asyncio.run(web.api_managed_settings(key, settings))
    asyncio.run(web.api_managed_edit(key, web.ManagedAccountEdit(label='新名称', group='品牌组')))
    row = next(row for row in asyncio.run(web.api_accounts()) if row['platform'] == key)
    assert row['persona'] == '品牌定位' and row['publishSettings']['content_suffix'] == '品牌署名'
    assert row['network']['mode'] == 'fixed' and row['group'] == '品牌组'
    web._write_login_marker(key, 'success')
    (state / 'clip.mp4').write_bytes(b'media')
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout='', stderr=''))
    monkeypatch.setattr(web.subprocess, 'run', run)
    monkeypatch.setattr(web, '_read_schedule', lambda: [])
    monkeypatch.setattr(web, '_write_schedule', lambda items: None)
    asyncio.run(web.api_publish(key, web.PublishRequest(title='Test', body='正文', media=['clip.mp4'])))
    cmd = run.call_args.args[0]
    assert cmd[cmd.index('--desc') + 1] == '正文\n\n品牌署名'
    assert cmd[cmd.index('--tags') + 1] == 'AI,学习'
    assert run.call_args.kwargs['env']['EASEL_ACCOUNT_PROXY_URL'] == 'http://127.0.0.1:7890'
    asyncio.run(web.api_publish(key, web.PublishRequest(title='Test', tags='自定义', media=['clip.mp4'])))
    cmd = run.call_args.args[0]
    assert cmd[cmd.index('--tags') + 1] == '自定义'


@pytest.mark.parametrize('url', ['invalid', 'http://localhost', 'http://user:password@localhost:7890', 'http://[broken', 'file:///abc', 'http://localhost:70000'])
def test_card_settings_reject_invalid_proxies(state, url):
    key = create('A')
    with pytest.raises(web.HTTPException) as error:
        asyncio.run(web.api_managed_settings(key, web.AccountCardSettings(proxy_mode='fixed', proxy_url=url)))
    assert error.value.status_code == 400


def test_account_network_is_isolated_for_login_whoami_and_open(state, monkeypatch):
    first, second = create('A'), create('B')
    asyncio.run(web.api_managed_settings(first, web.AccountCardSettings(proxy_mode='fixed', proxy_url='http://127.0.0.1:7890')))
    launch = Mock(return_value=SimpleNamespace(poll=lambda: None))
    monkeypatch.setattr(web.subprocess, 'Popen', launch)
    asyncio.run(web.api_login_start(first))
    assert launch.call_args.kwargs['env']['EASEL_ACCOUNT_PROXY_MODE'] == 'fixed'
    assert web._account_env(second, {})['EASEL_ACCOUNT_PROXY_MODE'] == 'inherit'
    web.LOGIN_PROCESSES.clear()
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout='{"loggedIn":true,"name":"A","avatar":""}'))
    monkeypatch.setattr(web.subprocess, 'run', run)
    asyncio.run(web.api_account_whoami(first))
    assert run.call_args.kwargs['env']['EASEL_ACCOUNT_PROXY_MODE'] == 'fixed'
    asyncio.run(web.api_managed_open(first))
    assert launch.call_args.kwargs['env']['EASEL_ACCOUNT_PROXY_MODE'] == 'fixed'
    with pytest.raises(web.HTTPException):
        asyncio.run(web.api_managed_settings(first, web.AccountCardSettings()))
    with pytest.raises(web.HTTPException):
        asyncio.run(web.api_managed_delete(first))


def test_delete_account_only_removes_its_own_profile_and_registry(state):
    first, second = create('A'), create('B')
    for key in (first, second):
        profile = Path(web.LOGIN_RUNNERS[key]['profile_base']) / 'ChannelsProfile'
        profile.mkdir(parents=True)
        (profile / 'cookies-test').write_bytes(b'cookies')
        web._write_login_marker(key, 'success')
    first_profile = Path(web.LOGIN_RUNNERS[first]['profile_base']) / 'ChannelsProfile'
    second_profile = Path(web.LOGIN_RUNNERS[second]['profile_base']) / 'ChannelsProfile'
    asyncio.run(web.api_managed_delete(first))
    assert first not in web.LOGIN_RUNNERS and second in web.LOGIN_RUNNERS
    assert not first_profile.exists() and second_profile.is_dir()
    assert web._account_logged_in(second, web.LOGIN_RUNNERS[second])
    assert first not in {a['key'] for a in channel_accounts.read(state)['accounts']}


def test_delete_original_account_retains_other_accounts(state):
    other = create('Other')
    web._write_login_marker('weixin-channels', 'success')
    web._write_login_marker(other, 'success')
    asyncio.run(web.api_accounts())
    asyncio.run(web.api_managed_delete('weixin-channels'))
    row = next(row for row in asyncio.run(web.api_accounts()) if row['platform'] == 'weixin-channels')
    assert not row['registered'] and not row['loggedIn']
    assert web._account_logged_in(other, web.LOGIN_RUNNERS[other])
