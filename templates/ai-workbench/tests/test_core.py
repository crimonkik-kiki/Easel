import asyncio
import base64
from dataclasses import replace
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from workbench.app import create_app
from workbench.config import Config
from workbench.harnesses import store as bindings
from workbench.harnesses.acp import ACPAdapter
from workbench.harnesses.base import HarnessError, RunRequest
from workbench.harnesses.codex import CodexAdapter
from workbench.harnesses.rpc import close_sessions
from workbench.storage import Store, instance_lock

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def project(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.startswith(('WORKBENCH_', 'WORKBUDDY_')):
            monkeypatch.delenv(key)
    (tmp_path / 'workbench.json').write_text(json.dumps({'id': 'test-instance', 'name': '测试工作台', 'modules': ['workbench.modules.brief']}), encoding='utf-8')
    (tmp_path / 'agents/workspace').mkdir(parents=True)
    (tmp_path / 'agents/workspace/AGENTS.md').write_text('只处理测试目录内的任务。', encoding='utf-8')
    (tmp_path / 'skills/builtin/summary').mkdir(parents=True)
    (tmp_path / 'skills/builtin/summary/SKILL.md').write_text('# 摘要\n输出核心结论。', encoding='utf-8')
    return tmp_path


@pytest.fixture
def upstream():
    image = io.BytesIO(); Image.new('RGB', (8, 8), 'blue').save(image, format='PNG')
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            if self.path.endswith('/models'):
                content=json.dumps({'data':[{'id':'mock-model'}]}).encode();mime='application/json'
            else:
                assert not self.headers.get('Authorization'), 'API key must not be sent to image download'
                content=image.getvalue();mime='image/png'
            self.send_header('Content-Type',mime);self.end_headers();self.wfile.write(content)

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            calls.append((self.path, body))
            if self.path.endswith('/chat/completions'):
                self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
                for word in ['独立工作台', '测试回复']:
                    item = {'choices': [{'delta': {'content': word}, 'finish_reason': None}]}
                    self.wfile.write(('data: ' + json.dumps(item) + '\n\n').encode())
                self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
                return
            if self.path.endswith('/images/generations'):
                content = json.dumps({'data': [{'url': f'http://127.0.0.1:{self.server.server_port}/image.png'}] if json.loads(body).get('response_format')=='url' else [{'b64_json': base64.b64encode(image.getvalue()).decode()}]}).encode()
            elif self.path.endswith('/audio/transcriptions'):
                content = json.dumps({'text': '这是测试转写文字。'}).encode()
            else:
                content = b'test-audio-payload'
            self.send_response(200)
            self.send_header('Content-Type', 'audio/mpeg' if self.path.endswith('/audio/speech') else 'application/json')
            self.end_headers(); self.wfile.write(content)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    yield f'http://127.0.0.1:{server.server_port}/v1', calls
    server.shutdown(); thread.join(timeout=3); server.server_close()


def client_for(project):
    return TestClient(create_app(project), base_url='http://127.0.0.1:7870', client=('127.0.0.1', 12345))


def wait_job(client, identifier, state=None):
    for _ in range(300):
        job = client.get('/api/jobs/' + identifier).json()
        if job['state'] == state if state else job['state'] in ('completed', 'failed', 'cancelled', 'interrupted'):
            return job
        time.sleep(.01)
    pytest.fail('job did not reach expected state')


def configure(client, base, runtime='api'):
    response = client.put('/api/settings', json={'runtime': runtime, 'channels': {
        name: {'base_url': base, 'model': 'mock-model', 'key': 'unit-test-secret'}
        for name in ('chat', 'image', 'transcription', 'speech')}})
    assert response.status_code == 200, response.text


def test_empty_bootstrap_never_calls_agents_or_loads_easel_data(project, monkeypatch):
    from workbench import engine
    monkeypatch.setattr(engine, 'adapter', lambda *args: pytest.fail('no automatic execution'))
    with client_for(project) as client:
        data = client.get('/api/bootstrap').json()
        assert data['brand']['id'] == 'test-instance'
        assert data['settings']['runtime'] == 'api'
        assert [s['id'] for s in data['skills']] == ['summary']
        assert client.get('/api/sessions').json() == client.get('/api/jobs').json() == []
        assert not list(project.glob('outputs/_harness/*'))


def test_settings_mask_keys_preserve_blank_and_explicitly_clear(project):
    with client_for(project) as client:
        configure(client, 'http://127.0.0.1:9001/v1')
        assert 'unit-test-secret' not in client.get('/api/settings').text
        response = client.put('/api/settings', json={'channels': {'chat': {'key': ''}}})
        assert response.json()['channels']['chat']['key_configured']
        response = client.put('/api/settings', json={'channels': {'chat': {'clear_key': True}}})
        assert not response.json()['channels']['chat']['key_configured']
        assert client.put('/api/settings', json={'channels': {'chat': {'base_url': 'http://user:secret@host/v1'}}}).status_code == 400


def test_native_models_do_not_inherit_api_model_and_are_saved_per_runtime(project, monkeypatch):
    from workbench import engine
    seen = []
    class Fake:
        async def run(self, request, emit, ask, bind):
            seen.append(request.model); emit('token', 'native model test'); bind('native-model-test')
    monkeypatch.setattr(engine, 'adapter', lambda _: Fake())
    with client_for(project) as client:
        configure(client, 'http://127.0.0.1:9001/v1', runtime='codex')
        job = client.post('/api/jobs', json={'prompt': 'native default'}).json()
        assert wait_job(client, job['id'])['state'] == 'completed'
        assert seen == ['']
        assert client.put('/api/settings', json={'models': {'codex': 'native-selected', 'opencode': 'provider/other'}}).status_code == 200
        job = client.post('/api/jobs', json={'prompt': 'native override'}).json()
        assert wait_job(client, job['id'])['state'] == 'completed'
        assert seen == ['', 'native-selected']
        assert client.put('/api/settings', json={'models': {'workbuddy': 'unsupported'}}).status_code == 400


def test_streaming_skill_attachment_history_replay_and_restart(project, upstream):
    base, calls = upstream
    with client_for(project) as client:
        configure(client, base)
        session = client.post('/api/sessions').json()
        upload = client.post('/api/uploads', files={'file': ('素材.md', '附件素材', 'text/markdown')}).json()
        job = client.post('/api/jobs', json={'prompt': '整理一下', 'session_id': session['id'], 'skill': 'summary', 'attachment': upload['id']}).json()
        final = wait_job(client, job['id'])
        assert final['state'] == 'completed' and final['text'] == '独立工作台测试回复'
        body = json.loads(calls[0][1]); assert '输出核心结论' in body['messages'][0]['content']
        assert '附件素材' in body['messages'][0]['content']
        response = client.get('/api/jobs/' + job['id'] + '/events')
        assert '独立工作台' in response.text and 'id:' in response.text
        assert 'unit-test-secret' not in client.get('/api/jobs').text
    with client_for(project) as client:
        assert len(client.get('/api/sessions').json()[0]['messages']) == 2
        next_job = client.post('/api/jobs', json={'prompt': '继续', 'session_id': session['id']}).json()
        assert wait_job(client, next_job['id'])['state'] == 'completed'
        assert len(json.loads(calls[-1][1])['messages']) == 4


def test_permission_waits_for_matching_confirmation_and_refuses_invalid_grant(project, monkeypatch):
    from workbench import engine

    class Fake:
        async def run(self, request, emit, ask, bind):
            values = await ask([{'questionId': 'permission', 'question': '执行测试工具？', 'options': [{'label': '允许本次'}, {'label': '拒绝'}]}])
            emit('token', values['permission'][0]); bind('native-test')
    monkeypatch.setattr(engine, 'adapter', lambda _: Fake())
    with client_for(project) as client:
        configure(client, 'http://127.0.0.1:9001/v1', runtime='codex')
        session = client.post('/api/sessions').json()
        job = client.post('/api/jobs', json={'prompt': '测试权限', 'session_id': session['id']}).json()
        pending = wait_job(client, job['id'], 'waiting')
        assert pending['text'] == ''
        assert client.post('/api/jobs', json={'prompt': '重复', 'session_id': session['id']}).status_code == 400
        assert client.put('/api/settings', json={'runtime': 'api'}).status_code == 409
        endpoint = '/api/jobs/' + job['id'] + '/answer'
        assert client.post(endpoint, json={'question_id': 'stale', 'answers': {'permission': ['允许本次']}}).status_code == 400
        assert client.post(endpoint, json={'question_id': pending['question']['id'], 'answers': {'permission': ['随便授权']}}).status_code == 400
        assert client.post(endpoint, json={'question_id': pending['question']['id'], 'answers': {'permission': ['拒绝']}}).status_code == 200
        final = wait_job(client, job['id']); assert final['text'] == '拒绝'
        assert bindings.binding(project / 'outputs/_sessions', session['id'])['native_id'] == 'native-test'


def test_cancel_pending_job_and_runtime_pin(project, monkeypatch):
    from workbench import engine

    class Slow:
        async def run(self, *args):
            await asyncio.sleep(60)
    monkeypatch.setattr(engine, 'adapter', lambda _: Slow())
    with client_for(project) as client:
        configure(client, 'http://127.0.0.1:9001/v1', runtime='codex')
        session = client.post('/api/sessions').json()
        job = client.post('/api/jobs', json={'prompt': 'wait', 'session_id': session['id']}).json()
        client.post('/api/jobs/' + job['id'] + '/cancel')
        assert wait_job(client, job['id'])['state'] == 'cancelled'
        client.put('/api/settings', json={'runtime': 'api'})
        assert client.post('/api/jobs', json={'prompt': 'new runtime', 'session_id': session['id']}).status_code == 400


@pytest.mark.parametrize('kind,filename', [('image', 'image.png'), ('speech', 'speech.mp3'), ('transcription', 'transcript.txt')])
def test_media_provider_contract_and_private_source_isolation(project, upstream, kind, filename):
    with client_for(project) as client:
        configure(client, upstream[0])
        uploaded = client.post('/api/uploads', files={'file': ('语音.wav', b'fixture-audio', 'audio/wav')}).json()
        job = client.post('/api/jobs', json={'kind': kind, 'prompt': 'test', 'attachment': uploaded['id']}).json()
        final = wait_job(client, job['id'])
        assert final['state'] == 'completed', final
        artifacts = client.get('/api/artifacts').json()
        assert len(artifacts) == 1 and artifacts[0]['name'] == filename
        assert client.get('/api/artifacts/' + final['artifacts'][0]).status_code == 200
        assert client.get('/api/artifacts/../_config/settings.json').status_code == 404
        assert client.get('/api/artifacts/%2e%2e/_config/settings.json').status_code == 404


def test_unconfigured_provider_fails_honestly_without_retry(project):
    with client_for(project) as client:
        job = client.post('/api/jobs', json={'kind': 'video', 'prompt': 'test'}).json()
        final = wait_job(client, job['id'])
        assert final['state'] == 'failed' and '适配器' in final['error']
        assert client.get('/api/artifacts').json() == []


def test_interrupted_jobs_are_not_retried_on_restart(project):
    with client_for(project) as client:
        client.app.state.store.put('job', {'id': 'previous', 'state': 'running', 'created_at': 1})
    with client_for(project) as client:
        final = client.get('/api/jobs/previous').json()
        assert final['state'] == 'interrupted' and not client.app.state.engine.running


def test_cross_origin_write_blocked_and_traversal_skill_rejected(project):
    with client_for(project) as client:
        assert client.post('/api/sessions', headers={'Origin': 'https://untrusted.example'}).status_code == 403
        assert client.get('/api/skills/%2e%2e%2fsecret').status_code == 404
        assert client.post('/api/jobs', json={'prompt': 'x', 'skill': '../private'}).status_code == 400
    remote = TestClient(create_app(project), base_url='http://127.0.0.1:7870', client=('192.0.2.1', 12345))
    with remote:
        assert remote.post('/api/sessions').status_code == 403


def test_only_one_service_owns_instance_data(project):
    with instance_lock(project / 'outputs/_system/service.lock'):
        with pytest.raises(OSError):
            with instance_lock(project / 'outputs/_system/service.lock'):
                pytest.fail('second instance should not acquire data lock')


@pytest.mark.parametrize('runtime,adapter_type', [('codex', CodexAdapter), ('acp', ACPAdapter)])
def test_extracted_rpc_adapters_resume_and_reuse_without_real_agent(project, runtime, adapter_type):
    fixture = ROOT / 'tests/fixtures/harness_rpc.py'
    audit = project / 'audit.jsonl'
    env = {**os.environ, 'FAKE_HARNESS_AUDIT': str(audit), 'FAKE_HARNESS_MODE': 'stable-resume'}
    request = RunRequest('offline test', project, env, command=(sys.executable, str(fixture), runtime), session_key='offline')

    async def scenario():
        nonlocal request
        ids, events = [], []
        async def reject(questions):
            raise AssertionError('unexpected request')
        try:
            for _ in range(2):
                await adapter_type().run(request, lambda *args: events.append(args), reject, ids.append)
                request = replace(request, native_id=ids[-1])
            await close_sessions('offline')
            await adapter_type().run(request, lambda *args: events.append(args), reject, ids.append)
            assert len(set(ids)) == 1
            assert any(kind == 'token' for kind, text in events)
        finally:
            await close_sessions()
    asyncio.run(scenario())
    methods = [json.loads(line).get('method') for line in audit.read_text().splitlines()]
    assert methods.count('initialize') == 2
    assert methods.count('thread/start' if runtime == 'codex' else 'session/new') == 1


def test_clone_has_new_identity_and_excludes_secrets_and_runtime_data(project, monkeypatch):
    spec = importlib.util.spec_from_file_location('scaffold', ROOT / 'scripts/create_workbench.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    source = project / 'source'; source.mkdir()
    (source / 'workbench.json').write_text('{"id":"old","name":"old"}')
    for name in ('.env', 'outputs', '.venv', 'node_modules'):
        if name == '.env': (source / name).write_text('SECRET=not-for-export')
        else: (source / name).mkdir(); (source / name / 'private').write_text('private')
    monkeypatch.setattr(module, 'ROOT', source)
    target = module.create(project / 'new', '新工作台', 7991)
    assert json.loads((target / 'workbench.json').read_text(encoding='utf-8'))['id'] != 'old'
    assert not any((target / name).exists() for name in ('.env', 'outputs', '.venv', 'node_modules'))
    with pytest.raises(ValueError): module.create(target, '重复', 7992)


def test_release_zip_excludes_credentials_history_and_dependencies(project, monkeypatch):
    import zipfile
    spec = importlib.util.spec_from_file_location('release_pack', ROOT / 'scripts/package_template.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    source = project / 'export'; (source / 'frontend/dist').mkdir(parents=True)
    (source / 'frontend/dist/index.html').write_text('<html>workbench</html>')
    (source / '.env.example').write_text('WORKBENCH_DIRECT_API_KEY=')
    (source / '.env').write_text('PRIVATE_KEY=never-ship-this')
    for name in ['outputs', '.codex', '.venv', 'frontend/node_modules', 'ai_workbench_template.egg-info']:
        directory = source / name; directory.mkdir(parents=True)
        (directory / 'private.json').write_text('never-ship-this')
    monkeypatch.setattr(module, 'ROOT', source)
    target = module.package(project / 'template.zip')
    with zipfile.ZipFile(target) as archive:
        assert sorted(archive.namelist()) == ['ai-workbench/.env.example', 'ai-workbench/frontend/dist/index.html']
        assert all(b'never-ship-this' not in archive.read(name) for name in archive.namelist())
