import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/shared/scripts'))
from account_network import browser_options


def test_fixed_proxy_removes_forced_direct_and_preserves_other_options(monkeypatch):
    monkeypatch.setenv('EASEL_ACCOUNT_PROXY_MODE', 'fixed')
    monkeypatch.setenv('EASEL_ACCOUNT_PROXY_URL', 'http://127.0.0.1:7890')
    original = {'channel': 'msedge', 'args': ['--no-proxy-server', '--start-maximized']}
    actual = browser_options(original)
    assert actual['proxy'] == {'server': 'http://127.0.0.1:7890'}
    assert actual['args'] == ['--start-maximized']
    assert original['args'][0] == '--no-proxy-server'


def test_system_and_direct_modes(monkeypatch):
    monkeypatch.setenv('EASEL_ACCOUNT_PROXY_MODE', 'system')
    assert browser_options({'args': ['--no-proxy-server'], 'proxy': {'server': 'old'}}) == {'args': []}
    monkeypatch.setenv('EASEL_ACCOUNT_PROXY_MODE', 'direct')
    assert browser_options({'proxy': {'server': 'old'}}) == {'args': ['--no-proxy-server']}
