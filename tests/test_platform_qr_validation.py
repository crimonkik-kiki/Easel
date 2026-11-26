import io
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import segno
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/shared/scripts'))
import douyin_publish
import web_publisher


def png(qr=False):
    stream = io.BytesIO()
    if qr:
        segno.make('https://example.test/login-check', micro=False).save(stream, kind='png', scale=8)
    else:
        Image.new('RGB', (200, 200), 'white').save(stream, format='PNG')
    return stream.getvalue()


def test_douyin_rejects_placeholder_without_overwriting_previous_qr(tmp_path):
    target = tmp_path / 'qr.png'
    target.write_bytes(b'previous-good-image')
    element = SimpleNamespace(bounding_box=lambda: {'x': 0, 'y': 0, 'width': 200, 'height': 200},
                              screenshot=Mock(return_value=png()))
    page = SimpleNamespace(screenshot=Mock(return_value=png()))
    with pytest.raises(RuntimeError, match='尚未加载完成'):
        douyin_publish._shot_qr(page, element, target)
    assert target.read_bytes() == b'previous-good-image'


def test_douyin_accepts_real_qr_pixels(tmp_path):
    target = tmp_path / 'qr.png'
    element = SimpleNamespace(bounding_box=lambda: {'x': 0, 'y': 0, 'width': 200, 'height': 200})
    douyin_publish._shot_qr(SimpleNamespace(screenshot=Mock(return_value=png(True))), element, target)
    assert Image.open(target).width >= 360


def test_kuaishou_never_falls_back_to_full_page(tmp_path):
    element = SimpleNamespace(is_visible=lambda: True,
                              bounding_box=lambda: {'width': 200, 'height': 200},
                              screenshot=lambda **kwargs: png())
    page = SimpleNamespace(query_selector_all=lambda selector: [element],
                           wait_for_timeout=lambda duration: None, screenshot=Mock())
    with pytest.raises(RuntimeError, match='未找到可识别'):
        web_publisher._crop_qr(page, tmp_path / 'qr.png', web_publisher.PLATFORMS['kuaishou'])
    page.screenshot.assert_not_called()
    assert not (tmp_path / 'qr.png').exists()


@pytest.mark.parametrize('platform', ['zhihu', 'kuaishou'])
def test_configured_platform_uses_native_edge(monkeypatch, platform):
    monkeypatch.setenv(f'EASEL_{platform.upper()}_BROWSER_CHANNEL', 'msedge')
    assert web_publisher._browser_options(platform, headless=False) == {
        'channel': 'msedge', 'headless': False, 'args': []}


def test_douyin_native_edge_preserves_system_network(monkeypatch, tmp_path):
    monkeypatch.setenv('EASEL_DOUYIN_BROWSER_CHANNEL', 'msedge')
    monkeypatch.setattr(douyin_publish, '_profile_dir', lambda base: tmp_path)
    launch = Mock()
    douyin_publish._launch(SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch)),
                           True, None, None)
    options = launch.call_args.kwargs
    assert options['channel'] == 'msedge'
    assert options['args'] == []
    assert options['headless'] is False
    assert 'proxy' not in options


@pytest.mark.parametrize(('text', 'state'), [('二维码已过期，请刷新二维码', 'expired'),
                                           ('扫码成功，请在手机上确认', 'scanned')])
def test_kuaishou_reports_expiry_and_scan_confirmation(text, state):
    page = SimpleNamespace(inner_text=lambda *args, **kwargs: text)
    assert web_publisher._login_qr_state(page, web_publisher.PLATFORMS['kuaishou']) == state
