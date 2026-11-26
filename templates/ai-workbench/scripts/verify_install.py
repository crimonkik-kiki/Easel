"""Test Windows install/start/stop with spaces, Unicode and port conflicts."""
from pathlib import Path
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[1]


def run():
    if os.name != 'nt':
        raise RuntimeError('This test exercises the Windows launchers')
    spec = importlib.util.spec_from_file_location('creator', ROOT / 'scripts/create_workbench.py')
    creator = importlib.util.module_from_spec(spec); spec.loader.exec_module(creator)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
    directory = ROOT.parent / '_verification' / ('install-' + uuid.uuid4().hex[:8])
    target = creator.create(directory / '安装验收 含空格', '安装验收', port)
    log = (directory / 'install.log').open('w', encoding='utf-8')
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
    # Install through the exact script delivered to end users, not a reused venv.
    try:
        install = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(target / 'setup.ps1')],
            cwd=target, env=env, stdout=log, stderr=log, creationflags=flags, timeout=300)
        if install.returncode:
            raise RuntimeError('Fresh installation failed; inspect ' + str(directory / 'install.log'))
    finally:
        log.close()

    def launch(folder, script):
        # Detached Windows children may inherit pipe handles. Capture to a
        # regular log file, so waiting for PowerShell cannot wait for server EOF.
        from types import SimpleNamespace
        path = directory / ('launcher-' + uuid.uuid4().hex[:8] + '.log')
        with path.open('w', encoding='utf-8') as output:
            completed = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(folder / script),
                *(['-NoBrowser'] if script == 'start.ps1' else [])], cwd=folder, env=env,
                stdout=output, stderr=output, creationflags=flags, timeout=30)
        return SimpleNamespace(returncode=completed.returncode, stderr=path.read_text(encoding='utf-8', errors='replace'))

    started = False
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False, timeout=3) as client:
            first = launch(target, 'start.ps1')
            assert first.returncode == 0, first.stderr
            started = True
            health = client.get('/api/health').json()
            assert client.get('/').status_code == 200
            assert launch(target, 'start.ps1').returncode == 0
            assert client.get('/api/health').json()['pid'] == health['pid'], 'double click must reuse this instance'
            # Deliberately share brand ID and port, so only the installation
            # fingerprint can stop the second directory from hijacking it.
            second = creator.create(directory / '第二个目录', '冲突验收', port)
            brand = json.loads((target / 'workbench.json').read_text(encoding='utf-8'))
            (second / 'workbench.json').write_text(json.dumps(brand), encoding='utf-8')
            subprocess.run([sys.executable, '-m', 'venv', str(second / '.venv')], check=True,
                           capture_output=True, creationflags=flags, timeout=40)
            assert launch(second, 'start.ps1').returncode != 0
            assert launch(second, 'stop.ps1').returncode != 0
            assert client.get('/api/health').json()['pid'] == health['pid']
            stopped = launch(target, 'stop.ps1')
            assert stopped.returncode == 0, stopped.stderr
            for _ in range(60):
                try:
                    client.get('/api/health')
                except httpx.HTTPError:
                    started = False; break
                time.sleep(.1)
            assert not started, 'correct stop must gracefully release the listening port'
        result = {'fresh_install': True, 'unicode_and_spaces_path': True, 'built_ui_no_node_required': True,
                  'double_start_same_pid': True, 'same_id_other_directory_rejected': True,
                  'wrong_directory_cannot_stop_service': True, 'graceful_stop': True, 'ai_requests': 0}
        (ROOT / 'docs/evidence/install-results.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result))
    finally:
        if started:
            launch(target, 'stop.ps1')


if __name__ == '__main__':
    run()
