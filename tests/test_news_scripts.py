import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/builtin/skill-news-intelligence/scripts'))
fetch_news = importlib.import_module('fetch_news')
daily_briefing = importlib.import_module('daily_briefing')


def test_rss_group_is_not_silently_empty(monkeypatch, capsys):
    calls = []
    def source(limit, keyword):
        calls.append((limit, keyword))
        return [{'title':'模拟资讯','url':'https://example.invalid/'}]
    monkeypatch.setattr(fetch_news, 'build_sources_map', lambda: {'a':source,'b':source})
    monkeypatch.setattr(fetch_news, 'RSS_SOURCES', {'a':('A','u','d'),'b':('B','u','d')})
    monkeypatch.setattr(sys, 'argv', ['fetch_news.py','--source','rss','--limit','3','--no-save'])
    fetch_news.main()
    assert len(json.loads(capsys.readouterr().out)) == 2
    assert calls == [(3,None),(3,None)]


@pytest.mark.parametrize('args', [['--source','not-a-source'], ['--source',''], ['--limit','0'], ['--limit','101']])
def test_invalid_news_arguments_are_errors(monkeypatch, args):
    monkeypatch.setattr(sys, 'argv', ['fetch_news.py',*args])
    with pytest.raises(SystemExit) as error:
        fetch_news.main()
    assert error.value.code == 2


def test_briefing_no_save_never_creates_output_directory(tmp_path, monkeypatch, capsys):
    directory = tmp_path / 'should-not-exist'
    monkeypatch.setattr(daily_briefing, 'fetch_section', lambda *args: [])
    monkeypatch.setattr(sys, 'argv', ['daily_briefing.py','--profile','creator','--no-save','--outdir',str(directory)])
    daily_briefing.main()
    assert not directory.exists()
    assert isinstance(json.loads(capsys.readouterr().out), dict)


@pytest.mark.skipif(os.name != 'nt', reason='Windows launcher')
def test_news_launcher_does_not_use_path_python_and_preserves_single_argument():
    shell = shutil.which('powershell.exe')
    assert shell
    environment = {**os.environ, 'PATH':str(ROOT / 'tmp/nonexistent-python-path')}
    for args in (['check'], ['fetch','--list-sources']):
        result = subprocess.run([shell,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'scripts/news.ps1'),*args],
            cwd=ROOT, env=environment, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15)
        assert result.returncode == 0, result.stderr
        if args == ['check']:
            assert Path(json.loads(result.stdout)['python']).resolve() == (ROOT/'.venv/Scripts/python.exe').resolve()
        else:
            assert 'woshipm' in result.stdout
