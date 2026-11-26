"""一次性判定：默认配置目录下 WorkBuddy 内置 CLI 是否已有可用认证。

不复制、不打印任何凭据；只输出 stopReason 与错误类别。
"""
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = r'D:\Codexspace\Easel-runtime\node-v24.22.0-win-x64\node.exe'
CLI = r'D:\workbuddy\resources\app.asar.unpacked\cli\bin\codebuddy'


def free_port():
    import socket
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def run(label, env_extra, pop_keys=()):
    env = {**os.environ, 'NO_COLOR': '1', 'CODEBUDDY_FORCE_LITE_WB_BUNDLE': '1', **env_extra}
    for key in pop_keys:
        env.pop(key, None)
    folder = ROOT / 'tmp/workbuddy-auth-probe'
    folder.mkdir(parents=True, exist_ok=True)
    port = free_port()
    proc = subprocess.Popen(
        [NODE, CLI, '--acp', '--serve', '--host', '127.0.0.1'], cwd=str(folder), env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding='utf-8', errors='replace')
    lines, diag, chunks = queue.Queue(), [], []

    def reader():
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    def drain():
        for line in proc.stderr:
            if len(diag) < 30:
                diag.append(line[:200])

    threading.Thread(target=reader, daemon=True).start()
    threading.Thread(target=drain, daemon=True).start()

    def call(rid, method, params, timeout=40):
        proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': rid, 'method': method,
                                     'params': params}) + '\n')
        proc.stdin.flush()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = lines.get(timeout=max(.1, deadline - time.monotonic()))
            except queue.Empty:
                break
            if line is None:
                raise RuntimeError('进程提前退出')
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get('method') == 'session/update':
                upd = (msg.get('params') or {}).get('update') or {}
                if upd.get('sessionUpdate') == 'agent_message_chunk':
                    chunks.append(str((upd.get('content') or {}).get('text', '')))
            elif 'method' in msg and 'id' in msg:
                proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': msg['id'],
                                             'result': {'outcome': {'outcome': 'cancelled'}}}) + '\n')
                proc.stdin.flush()
            elif msg.get('id') == rid:
                return msg
        raise TimeoutError(method)

    out = {'方案': label}
    try:
        init = call(1, 'initialize', {'protocolVersion': 1,
                                      'clientInfo': {'name': 'easel-auth-probe', 'version': '0.1'},
                                      'clientCapabilities': {'fs': {'readTextFile': False,
                                                                    'writeTextFile': False},
                                                             'terminal': False}})
        out['authMethods'] = [m.get('id') for m in (init.get('result') or {}).get('authMethods', [])]
        sess = call(2, 'session/new', {'cwd': str(folder), 'mcpServers': []})
        sid = (sess.get('result') or {}).get('sessionId')
        out['sessionCreated'] = bool(sid)
        if sid:
            ans = call(3, 'session/prompt', {'sessionId': sid, 'prompt': [
                {'type': 'text', 'text': '只回复 AUTH_OK 四个字符，不要调用任何工具。'}]})
            res = ans.get('result') or {}
            meta = res.get('_meta') or {}
            out['stopReason'] = res.get('stopReason')
            raw = meta.get('codebuddy.ai/errorMessage', '')
            out['errorCategory'] = 'auth' if 'auth' in raw.lower() else ('none' if not raw else 'other')
            out['reply'] = ''.join(chunks)[:80]
    except Exception as error:
        out['probeError'] = str(error)
        out['stderrKinds'] = {
            'auth': any('auth' in s.lower() for s in diag),
            'network': any(('ENOTFOUND' in s or 'ECONN' in s) for s in diag)}
    finally:
        if proc.poll() is None:
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return out


results = []
results.append(run('默认配置目录（复用桌面登录态）', {}))
results.append(run('隔离空配置目录（对照）', {
    'CODEBUDDY_CONFIG_DIR': str(ROOT / 'tmp/workbuddy-auth-probe/isolated')}))
print(json.dumps(results, ensure_ascii=False, indent=2))
(ROOT / 'tmp/workbuddy-auth-probe/result.json').write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
