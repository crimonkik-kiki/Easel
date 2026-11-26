import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
import pytest

from easel import clipify
from easel.clipify_media import atomic_json
from web.clipify_api import CaptionRevision, ClipifyTasks, NewClipifyTask, register_clipify


def saved(outputs, identifier='clipify-'+'a'*16, state='created'):
    folder=outputs/identifier
    (folder/'.work').mkdir(parents=True)
    atomic_json(folder/'manifest.json',{'id':identifier,'state':state,'message':'测试',
        'created_at':1,'source':'D:/模拟账号/课程.mp4','options':{'aspect':'source','count':1},'clips':[]})
    return folder


@pytest.mark.parametrize('identifier',['../outside','clipify-../a','_login','clipify-'+'a'*17])
def test_task_paths_cannot_escape_outputs(tmp_path,identifier):
    manager=ClipifyTasks(lambda:tmp_path)
    with pytest.raises(HTTPException) as error:manager.folder(identifier)
    assert error.value.status_code==400


def test_restart_does_not_drop_held_worker_lock_or_start_second_context(tmp_path):
    folder=saved(tmp_path,state='transcribing')
    restarted=ClipifyTasks(lambda:tmp_path)
    with clipify.exclusive(tmp_path/'_clipify.lock'):
        with pytest.raises(HTTPException) as error:restarted.start(folder,resume=True)
        assert error.value.status_code==409
        assert restarted.status(folder.name)['state']=='transcribing'


def test_dead_worker_can_be_resumed_after_web_restart(tmp_path):
    folder=saved(tmp_path,state='transcribing')
    restarted=ClipifyTasks(lambda:tmp_path)
    assert restarted.status(folder.name)['can_resume']
    with clipify.exclusive(folder/'.work/task.lock'):
        assert not restarted.status(folder.name).get('can_resume')


def test_cancel_marks_only_selected_job_and_does_not_mark_completed(tmp_path):
    first=saved(tmp_path,state='transcribing')
    second=saved(tmp_path,'clipify-'+'b'*16,state='completed')
    manager=ClipifyTasks(lambda:tmp_path)
    result=manager.cancel(first.name)
    assert result['cancel_requested'] and (first/'cancel.request').exists()
    assert manager.status(first.name)['cancel_requested']
    assert manager.cancel(second.name)['state']=='completed'
    assert not (second/'cancel.request').exists()


def test_completed_task_cannot_be_overwritten_by_changed_settings(tmp_path):
    folder=saved(tmp_path,state='completed')
    manager=ClipifyTasks(lambda:tmp_path)
    with pytest.raises(HTTPException) as error:manager.start(folder,resume=True)
    assert error.value.status_code==409


def test_library_only_shows_successfully_generated_clipify_projects(tmp_path,monkeypatch):
    import web.app as web
    monkeypatch.setattr(web,'OUTPUTS_DIR',tmp_path)
    folder=saved(tmp_path,state='no_speech')
    assert web.get_output_tree()==[]
    atomic_json(folder/'.easel.json',{'title':'已完成测试成片','kind':'video'})
    assert web.get_output_tree()[0]['name']==folder.name


def test_mounting_and_history_do_not_touch_source_accounts_or_start_workers(tmp_path,monkeypatch):
    app=FastAPI();manager=register_clipify(app,lambda:tmp_path)
    folder=saved(tmp_path,state='completed')
    monkeypatch.setattr(manager,'start',lambda *a,**k:pytest.fail('read should not launch a worker'))
    endpoint=next(r.endpoint for r in app.routes if r.path=='/api/clipify/tasks' and 'GET' in r.methods)
    assert endpoint()[0]['id']==folder.name
    assert not list(tmp_path.rglob('cancel.request'))


@pytest.mark.parametrize('body',[{'source':'x','count':True},{'source':'x','count':0},{'source':'x','minimum':float('nan')}])
def test_invalid_request_parameters_rejected(body):
    with pytest.raises(ValidationError):NewClipifyTask(**body)


def test_manual_selection_preserves_original_render_options(tmp_path):
    folder=saved(tmp_path,state='awaiting_selection')
    state=clipify.load(folder);state['media']={'duration':30};state['options'].update(minimum=5,maximum=30)
    atomic_json(folder/'manifest.json',state)
    atomic_json(folder/'transcript.json',{'segments':[{'start':0,'end':10,'text':'模拟教学内容'}]})
    clipify.manual_selection(folder,{'segments':[{'start':0,'end':10,'title':'教学'}]})
    assert clipify.load(folder)['options']==state['options']
    assert json.loads((folder/'selection.json').read_text(encoding='utf-8'))['origin']=='user'


def test_lock_in_cli_blocks_manual_update_until_worker_finishes(tmp_path):
    folder=saved(tmp_path,state='transcribing')
    with clipify.exclusive(folder/'.work/task.lock'):
        with pytest.raises(clipify.ClipifyError):clipify.manual_selection(folder,{'segments':[]})


def test_caption_revision_creates_new_task_and_keeps_original(tmp_path,monkeypatch):
    import hashlib
    source=tmp_path/'模拟原片.mp4';source.write_bytes(b'fixture')
    model=tmp_path/'model';model.mkdir();(model/'model.bin').write_bytes(b'model')
    folder=saved(tmp_path,state='completed')
    transcript={'source':str(source),'segments':[{'start':0,'end':10,'text':'课程文字'}]}
    atomic_json(folder/'transcript.json',transcript)
    state=clipify.load(folder)
    state.update(source=str(source),media={'duration':30},fingerprint={'sha256':'source'},asr_signature={'model':'fixture'},
        transcript_sha256=hashlib.sha256((folder/'transcript.json').read_bytes()).hexdigest(),
        clips=[{'start':0,'end':10,'title':'课堂','file':'clip-01/video.mp4'}])
    state['options'].update(minimum=5,maximum=30,model=str(model))
    atomic_json(folder/'manifest.json',state)
    before=(folder/'manifest.json').read_bytes()
    app=FastAPI();manager=register_clipify(app,lambda:tmp_path)
    monkeypatch.setattr(manager,'start',lambda target:clipify.load(target))
    endpoint=next(r.endpoint for r in app.routes if r.path.endswith('/captions/{index}') and 'POST' in r.methods)
    revised=endpoint(folder.name,1,CaptionRevision(cues=[{'start':0.,'end':10.,'text':'校对后的课程文字'}]))
    assert revised['id']!=folder.name and revised['parent_task']==folder.name
    assert (folder/'manifest.json').read_bytes()==before
    assert json.loads((tmp_path/revised['id']/'.work/subtitle-overrides.json').read_text(encoding='utf-8'))['1'][0]['text']=='校对后的课程文字'


@pytest.mark.parametrize('cue',[{'start':0.,'end':float('nan'),'text':'x'},
    {'start':True,'end':2.,'text':'x'},{'start':0.,'end':2.,'text':'x'*41}])
def test_caption_revision_rejects_bad_time_or_excess_text(cue):
    with pytest.raises(ValidationError):CaptionRevision(cues=[cue])
