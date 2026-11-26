"""Regression cases for gaps found when testing the exported template."""
import io
import json
from pathlib import Path

from PIL import Image
import pytest

from test_core import project, upstream, client_for, configure, wait_job


def test_generated_files_include_root_and_deep_paths_with_safe_inline_previews(project):
    root = project / 'outputs/generated'
    (root / 'a/b').mkdir(parents=True)
    (root / 'root.txt').write_text('root result')
    (root / 'a/b/deep.txt').write_text('deep result')
    (root / '_private').mkdir(); (root / '_private/key.txt').write_text('private')
    Image.new('RGB', (10, 10), 'red').save(root / 'a/image.png')
    with client_for(project) as client:
        files = client.get('/api/artifacts').json()
        assert {row['path'] for row in files} == {'root.txt', 'a/b/deep.txt', 'a/image.png'}
        download = client.get('/api/artifacts/root.txt')
        assert 'attachment' in download.headers['content-disposition']
        assert 'root.txt' in download.headers['content-disposition']
        preview = client.get('/api/artifacts/a/image.png?preview=true')
        assert preview.status_code == 200 and 'inline' in preview.headers['content-disposition']
        assert preview.headers['content-type'].startswith('image/png')
        assert client.get('/api/artifacts/_private/key.txt').status_code == 404


def test_capabilities_distinguish_unconfigured_from_unimplemented(project):
    with client_for(project) as client:
        capabilities = client.get('/api/bootstrap').json()['capabilities']
        assert not capabilities['chat']['ready'] and capabilities['chat']['supported']
        assert not capabilities['video']['supported'] and not capabilities['video']['ready']
        configure(client, 'http://127.0.0.1:9999/v1')
        assert client.get('/api/bootstrap').json()['capabilities']['image']['ready']
        assert not client.get('/api/bootstrap').json()['capabilities']['image']['authentication_verified']


def test_business_module_preserves_origin_and_rejects_invalid_form(project, upstream):
    with client_for(project) as client:
        configure(client, upstream[0])
        assert client.post('/api/modules/brief/run', json=[]).status_code == 400
        job = client.post('/api/modules/brief/run', json={'requirements': '整理需求'}).json()
        completed = wait_job(client, job['id'])
        assert completed['state'] == 'completed' and completed['module_id'] == 'brief'
        assert completed['session_id'] == ''


def test_prompt_skill_is_persistent_readable_and_not_overwritten(project, upstream):
    with client_for(project) as client:
        skill = {'id': 'meeting-summary', 'text': '# 会议摘要\n列出决议和负责人。'}
        assert client.post('/api/skills', json=skill).status_code == 200
        assert client.get('/api/skills/meeting-summary').json()['text'] == skill['text']
        assert client.post('/api/skills', json=skill).status_code == 400
        assert client.post('/api/skills', json={'id': '../private', 'text': 'x'}).status_code == 400
        assert client.post('/api/skills', json={'id': None, 'text': 'x'}).status_code == 400
        configure(client, upstream[0])
        job = client.post('/api/jobs', json={'prompt': '会议记录', 'skill': 'meeting-summary'}).json()
        assert wait_job(client, job['id'])['state'] == 'completed'
        assert '列出决议和负责人' in json.loads(upstream[1][-1][1])['messages'][0]['content']
    with client_for(project) as client:
        assert 'meeting-summary' in {row['id'] for row in client.get('/api/bootstrap').json()['skills']}


def test_catalog_reports_installed_status_instead_of_claiming_all_ready(project):
    (project / 'docs').mkdir()
    (project / 'docs/easel-skill-catalog.json').write_text(json.dumps([
        {'id': 'summary', 'description': '已装载'}, {'id': 'other', 'description': '未装载'}]), encoding='utf-8')
    with client_for(project) as client:
        rows = client.get('/api/skill-catalog').json()
        assert [row['installed'] for row in rows] == [True, False]


def test_conversation_can_be_renamed_and_exported_without_calling_ai(project):
    with client_for(project) as client:
        session = client.post('/api/sessions').json()
        identifier = session['id']
        renamed = client.patch('/api/sessions/' + identifier, json={'title': '客户讨论'}).json()
        assert renamed['title'] == '客户讨论'
        assert client.patch('/api/sessions/' + identifier, json={'title': ' '}).status_code == 400
        exported = client.get('/api/sessions/' + identifier + '/export')
        assert exported.status_code == 200 and '# 客户讨论' in exported.text
        assert 'attachment' in exported.headers['content-disposition']
    with client_for(project) as client:
        assert client.get('/api/sessions').json()[0]['title'] == '客户讨论'


def test_same_instance_id_in_different_directories_has_different_installation_fingerprint(project):
    with client_for(project) as client:
        first = client.get('/api/health').json()
    from workbench.app import create_app
    from fastapi.testclient import TestClient
    other = project / 'copy'; other.mkdir()
    (other / 'workbench.json').write_bytes((project / 'workbench.json').read_bytes())
    with TestClient(create_app(other), base_url='http://127.0.0.1:7870', client=('127.0.0.1', 123)) as client:
        second = client.get('/api/health').json()
        assert first['instance'] == second['instance']
        assert first['installation'] != second['installation']


def test_stop_refuses_active_tasks_and_stops_only_this_service_callback(project):
    with client_for(project) as client:
        called = []
        client.app.state.shutdown = lambda: called.append(True)
        client.app.state.store.put('job', {'id': 'active', 'state': 'running', 'created_at': 1})
        assert client.post('/api/admin/stop').status_code == 409 and not called
        client.app.state.store.put('job', {'id': 'active', 'state': 'completed', 'created_at': 1})
        assert client.post('/api/admin/stop').status_code == 200 and called == [True]


def test_transcription_requires_audio_and_custom_voice_is_sent(project, upstream):
    with client_for(project) as client:
        configure(client, upstream[0])
        assert client.post('/api/jobs', json={'kind': 'transcription'}).status_code == 400
        uploaded = client.post('/api/uploads', files={'file': ('text.txt', b'text', 'text/plain')}).json()
        job = client.post('/api/jobs', json={'kind': 'transcription', 'attachment': uploaded['id']}).json()
        assert wait_job(client, job['id'])['state'] == 'failed'
        assert client.put('/api/settings', json={'channels': {'speech': {'voice': 'custom-voice'}}}).status_code == 200
        job = client.post('/api/jobs', json={'kind': 'speech', 'prompt': '测试音色'}).json()
        assert wait_job(client, job['id'])['state'] == 'completed'
        assert json.loads(upstream[1][-1][1])['voice'] == 'custom-voice'


def test_image_format_can_follow_provider_default(project, upstream):
    with client_for(project) as client:
        configure(client, upstream[0])
        job = client.post('/api/jobs', json={'kind': 'image', 'prompt': '测试'}).json()
        assert wait_job(client, job['id'])['state'] == 'completed'
        assert 'response_format' not in json.loads(upstream[1][-1][1])
        assert client.put('/api/settings', json={'channels': {'speech': {'provider': 'codex'}}}).status_code == 400


def test_url_image_response_downloads_without_forwarding_api_key(project, upstream):
    with client_for(project) as client:
        configure(client, upstream[0])
        assert client.post('/api/models/api').json()==[{'id':'mock-model','label':'mock-model'}]
        client.put('/api/settings',json={'channels':{'image':{'response_format':'url'}}})
        job=client.post('/api/jobs',json={'kind':'image','prompt':'download test'}).json()
        completed=wait_job(client,job['id'])
        assert completed['state']=='completed',completed
        response=client.get('/api/artifacts/'+completed['artifacts'][0]+'?preview=true')
        assert response.status_code==200 and response.content.startswith(b'\x89PNG')


@pytest.mark.parametrize('authenticated', [True, False])
def test_codex_auth_check_reports_cli_auth_without_exposing_output(project, monkeypatch, authenticated):
    import sys
    from workbench import app as module, engine
    monkeypatch.setattr(engine, 'base_command', lambda _: [sys.executable])
    monkeypatch.setattr(module, 'base_command', lambda _: [sys.executable, '-c',
        f"import sys;print('private-status-detail');sys.exit({0 if authenticated else 1})"])
    with client_for(project) as client:
        response = client.post('/api/runtimes/codex/check')
        assert response.status_code == 200
        assert response.json()['authenticated'] is authenticated
        assert 'private-status-detail' not in response.text
        if not authenticated:
            assert 'codex login' in response.json()['message']


def test_branding_and_navigation_are_instance_local_public_presentation(project):
    brand_path = project / 'workbench.json'
    brand = json.loads(brand_path.read_text(encoding='utf-8'))
    brand.update(logo='/brand/custom.svg', welcome_title='开始今天的客户工作',
                 welcome_subtitle='按本团队的流程执行', port=7988,
                 navigation=[{'id': 'media', 'label': '素材工坊', 'icon': 'image'},
                             {'id': 'home', 'label': '项目总览', 'icon': 'dashboard'}])
    brand_path.write_text(json.dumps(brand), encoding='utf-8')
    with client_for(project) as client:
        response = client.get('/api/bootstrap').json()
        assert response['brand']['logo'] == '/brand/custom.svg'
        assert response['brand']['welcome_title'] == '开始今天的客户工作'
        assert [row['label'] for row in response['navigation']] == ['素材工坊', '项目总览']
        assert 'port' not in response['brand']
        assert len(response['modules']) == 1
        assert not client.get('/api/jobs').json()
