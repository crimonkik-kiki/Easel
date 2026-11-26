import functools
import http.server
import os
from pathlib import Path
import threading

import pytest
from scripts import health_ui


@pytest.mark.skipif(os.environ.get('EASEL_LOCAL_BROWSER_TEST') != '1', reason='explicit local Edge opt-in')
def test_compiled_ui_health_gate_with_browser_only_synthetic_data():
    staging = Path(__file__).resolve().parents[1] / 'tmp' / 'frontend-staging'
    assert (staging / 'index.html').is_file()
    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(staging)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        checks = health_ui.check(f'http://127.0.0.1:{server.server_port}')
        assert checks['automatic_account_access'] == 0
        assert checks['production_rows_written'] == 0
        assert checks['receipt_source'] == 'manual_confirmation_explicit'
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_ui_probe_crash_requires_manual_judgement(monkeypatch, capsys):
    def broken(*args):
        raise RuntimeError('injected browser probe bug')
    monkeypatch.setattr(health_ui, 'check', broken)
    monkeypatch.setattr('sys.argv', ['health_ui.py'])
    assert health_ui.main() == 30
    assert 'PROBE_ERROR_MANUAL_REVIEW' in capsys.readouterr().out
