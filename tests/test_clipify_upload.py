import io
import subprocess
from pathlib import Path

from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.testclient import TestClient
import pytest

from web import clipify_api as api
from easel import clipify_media as media


@pytest.fixture(scope='module')
def video(tmp_path_factory):
    path=tmp_path_factory.mktemp('clipify-upload')/'拖拽素材.mp4'
    proc=subprocess.run([media.ffmpeg(),'-v','error','-nostdin','-y','-f','lavfi','-i','testsrc=size=320x180:rate=10:duration=1',
        '-f','lavfi','-i','sine=frequency=300:sample_rate=16000:duration=1','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(path)],capture_output=True,timeout=30)
    assert proc.returncode==0,proc.stderr
    return path


def test_real_multipart_video_upload_is_private_and_does_not_start_jobs(tmp_path,video,monkeypatch):
    app=FastAPI();tasks=api.register_clipify(app,lambda:tmp_path)
    monkeypatch.setattr(tasks,'start',lambda *a,**k:pytest.fail('upload must not start a job'))
    with TestClient(app) as client:
        with video.open('rb') as stream:
            response=client.post('/api/clipify/upload',files={'file':('中文课程.mp4',stream,'video/mp4')})
        assert response.status_code==200,response.text
        uploaded=response.json();target=Path(uploaded['source'])
        assert target.is_relative_to(tmp_path/'_clipify_uploads') and target.name=='中文课程.mp4'
        assert uploaded['width']==320 and uploaded['height']==180 and uploaded['size']==video.stat().st_size
        assert target.read_bytes()==video.read_bytes()
        assert client.get('/api/clipify/tasks').json()==[]
    import web.app as web
    monkeypatch.setattr(web,'OUTPUTS_DIR',tmp_path)
    assert web.get_output_tree()==[],'source uploads must not become library projects'


@pytest.mark.parametrize('name,data,status',[('bad.txt',b'a',400),('empty.mp4',b'',400),('fake.mp4',b'not video',400)])
def test_invalid_upload_removes_staging_files(tmp_path,name,data,status):
    file=UploadFile(filename=name,file=io.BytesIO(data))
    with pytest.raises(HTTPException) as error:api.store_clipify_upload(file,tmp_path)
    assert error.value.status_code==status and file.file.closed
    assert not list(tmp_path.rglob('*.*'))


def test_oversized_upload_stops_and_removes_staging_files(tmp_path,monkeypatch):
    monkeypatch.setattr(api,'MAX_CLIPIFY_UPLOAD_BYTES',4)
    with pytest.raises(HTTPException) as error:
        api.store_clipify_upload(UploadFile(filename='large.mp4',file=io.BytesIO(b'12345')),tmp_path)
    assert error.value.status_code==413
    assert not list(tmp_path.rglob('.uploading'))
    assert not list(tmp_path.rglob('*.mp4'))


def test_duplicate_names_never_overwrite_and_windows_paths_are_sanitized(tmp_path,video):
    results=[]
    for _ in range(2):
        results.append(api.store_clipify_upload(UploadFile(filename=r'C:\fakepath\..\课程.mp4',file=io.BytesIO(video.read_bytes())),tmp_path))
    first,second=map(lambda d:Path(d['source']),results)
    assert first.name==second.name=='课程.mp4' and first!=second
    assert first.is_relative_to(tmp_path) and first.read_bytes()==second.read_bytes()==video.read_bytes()


def test_streaming_does_not_read_whole_video_into_memory(tmp_path,monkeypatch):
    class Bounded(io.BytesIO):
        def read(self,size=-1):
            assert 0<size<=4*1024*1024
            return super().read(size)
    monkeypatch.setattr(media,'probe',lambda _:dict(width=320,height=180,has_audio=True,duration=1))
    data=b'x'*(5*1024*1024)
    result=api.store_clipify_upload(UploadFile(filename='stream.mp4',file=Bounded(data)),tmp_path)
    assert Path(result['source']).read_bytes()==data


def test_probe_rejects_no_audio_without_leaving_a_source(tmp_path,monkeypatch):
    monkeypatch.setattr(media,'probe',lambda _:dict(width=320,height=180,has_audio=False,duration=1))
    with pytest.raises(HTTPException):
        api.store_clipify_upload(UploadFile(filename='silent.mp4',file=io.BytesIO(b'mock')),tmp_path)
    assert not list(tmp_path.rglob('*.mp4'))
