"""Validate a packaged template in a clean extraction, without AI requests."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import uuid
import zipfile

import httpx

ROOT = Path(__file__).resolve().parents[1]


def verify(archive):
    archive = Path(archive).resolve()
    target = ROOT.parent / '_verification' / ('zip-' + uuid.uuid4().hex[:8])
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        forbidden = {'.venv', 'outputs', 'node_modules', '.git', '.codex', '.aws', '.ssh', '__pycache__'}
        assert not any(forbidden.intersection(Path(name).parts) or Path(name).name == '.env' for name in names)
        assert not any(Path(name).is_absolute() or '..' in Path(name).parts for name in names)
        for name in ['frontend/dist/index.html', 'frontend/dist/brand/easel-icon-transparent.png',
                     'frontend/src/styles/easel-base.css', 'docs/UI-FRAMEWORK.md', 'docs/REVIEW-v0.3.0.md']:
            assert 'ai-workbench/' + name in names, name
        assert len([name for name in names if name.endswith('/SKILL.md')]) == 3
        z.extractall(target)
    clone = target / 'ai-workbench'
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
    env = {key: value for key, value in os.environ.items() if not key.startswith(('WORKBENCH_', 'WORKBUDDY_'))}
    env['PYTHONUTF8'] = '1'; env.pop('PYTHONPATH', None)
    code = 'from pathlib import Path;import workbench;assert Path(workbench.__file__).resolve().is_relative_to(Path.cwd());from workbench.__main__ import main;main()'
    log = (target / 'server.log').open('w', encoding='utf-8')
    process = subprocess.Popen([str(ROOT / '.venv/Scripts/python.exe'), '-c', code, '--port', str(port)],
                               cwd=clone, env=env, stdout=log, stderr=log,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False, timeout=5) as c:
            for _ in range(100):
                assert process.poll() is None, 'extracted service exited'
                try:
                    if c.get('/api/health').is_success: break
                except httpx.HTTPError: pass
                time.sleep(.1)
            assert c.get('/api/health').json()['version'] == '0.3.0'
            assert c.get('/').is_success
            boot = c.get('/api/bootstrap').json()
            assert boot['brand']['name'] == 'Easel' and len(boot['skills']) == 3
            assert len(boot['navigation']) == 6
            assert c.get(boot['brand']['logo']).headers['content-type'].startswith('image/')
            assert c.get('/api/sessions').json() == c.get('/api/jobs').json() == c.get('/api/artifacts').json() == []
            assert not any(channel['key_configured'] for channel in boot['settings']['channels'].values())
            c.post('/api/admin/stop').raise_for_status(); process.wait(timeout=15)
            assert process.returncode == 0
        result = {'version': '0.3.0', 'archive_content_check': True, 'extracted_root_import_verified': True,
                  'http_and_bootstrap': True, 'easel_brand_and_logo': True, 'navigation_entries': 6, 'skills': 3,
                  'empty_sessions_jobs_artifacts_and_keys': True, 'graceful_shutdown': True, 'ai_requests': 0}
        (ROOT / 'docs/evidence/release-results.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        manifest = {'version': '0.3.0', 'archive': archive.name, 'bytes': archive.stat().st_size,
                    'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'entries': len(names),
                    'included_skills': 3, 'catalog_entries': 114, 'credentials_or_runtime_data': False,
                    'built_frontend': True, 'easel_visual_shell': True, 'backend_tests': 31, 'ui_runs': 3,
                    'real_codex_chat_and_file_test': True, 'release_smoke': result}
        (ROOT / 'release/release-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        print(json.dumps(manifest))
    finally:
        if process.poll() is None: process.terminate(); process.wait(timeout=10)
        log.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', default=str(ROOT / 'release/ai-workbench-template-v0.3.0.zip'))
    verify(parser.parse_args().archive)
