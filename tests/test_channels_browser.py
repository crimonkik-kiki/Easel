import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/shared/scripts'))
import web_publisher
import xhs_publish
from types import SimpleNamespace


def test_channels_edge_keeps_system_network_and_visible_login(monkeypatch):
    monkeypatch.setenv('EASEL_CHANNELS_BROWSER_CHANNEL', 'msedge')
    options = web_publisher._browser_options('weixin-channels', headless=False)
    assert options == {'channel': 'msedge', 'headless': False, 'args': []}
    context = Mock()
    transport = Mock()
    monkeypatch.setattr(web_publisher.login_transport, 'install', transport)
    web_publisher._block_heavy(context, 'weixin-channels')
    transport.assert_not_called()
    context.route.assert_called_once()


def test_other_platforms_and_unconfigured_channels_keep_existing_network(monkeypatch):
    monkeypatch.setenv('EASEL_CHANNELS_BROWSER_CHANNEL', 'msedge')
    assert '--no-proxy-server' in web_publisher._browser_options('zhihu')['args']
    monkeypatch.delenv('EASEL_CHANNELS_BROWSER_CHANNEL')
    assert '--no-proxy-server' in web_publisher._browser_options('weixin-channels')['args']
    context = Mock()
    transport = Mock()
    monkeypatch.setattr(web_publisher.login_transport, 'install', transport)
    web_publisher._block_heavy(context, 'weixin-channels')
    transport.assert_called_once_with(context, 'weixin-channels')


def test_xhs_native_edge_keeps_system_network_without_asset_relay(monkeypatch, tmp_path):
    monkeypatch.setenv('EASEL_XHS_BROWSER_CHANNEL', 'msedge')
    monkeypatch.setattr(xhs_publish, '_profile_dir', lambda base: tmp_path)
    monkeypatch.setattr(xhs_publish, '_cloak_executable', Mock(side_effect=AssertionError('native Edge requested')))
    transport = Mock()
    monkeypatch.setattr(xhs_publish.login_transport, 'install', transport)
    context = Mock()
    launch = Mock(return_value=context)
    playwright = SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch))
    assert xhs_publish._launch(playwright, True, None, None) is context
    options = launch.call_args.kwargs
    assert options['channel'] == 'msedge'
    assert options['headless'] is False
    assert options['args'] == []
    assert 'proxy' not in options
    transport.assert_not_called()
