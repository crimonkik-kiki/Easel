import asyncio
import io

import pytest
from fastapi import UploadFile
import web.app as web


def upload(name, data=b'media'):
    return UploadFile(filename=name, file=io.BytesIO(data))


def test_upload_is_visible_and_duplicate_names_do_not_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(web, 'OUTPUTS_DIR', tmp_path)
    result = asyncio.run(web._store_media_upload([upload('照片.png', b'first'), upload('照片.png', b'second'), upload('clip.mp4')], ''))
    assert len(result['files']) == 3
    assert len({file['path'] for file in result['files']}) == 3
    assert [(tmp_path / f['path']).read_bytes() for f in result['files']][:2] == [b'first', b'second']
    tree = web.get_output_tree()
    assert tree[0]['path'] == result['folder']
    assert {f['kind'] for f in tree[0]['children']} == {'image', 'video'}
    assert all(web._safe_output_path(f['path']).is_file() for f in result['files'])


def test_upload_to_existing_project_and_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(web, 'OUTPUTS_DIR', tmp_path)
    (tmp_path / '项目').mkdir()
    result = asyncio.run(web._store_media_upload([upload('audio.flac')], '项目'))
    assert result['folder'].startswith('项目/')
    assert web.get_output_tree()[0]['children'][0]['children'][0]['kind'] == 'audio'


@pytest.mark.parametrize('folder', ['../outside', '_login', '.private'])
def test_rejects_protected_or_outside_folders(tmp_path, monkeypatch, folder):
    monkeypatch.setattr(web, 'OUTPUTS_DIR', tmp_path)
    if '..' not in folder:
        (tmp_path / folder).mkdir()
    with pytest.raises(web.HTTPException):
        asyncio.run(web._store_media_upload([upload('x.png')], folder))


@pytest.mark.parametrize('name', ['script.exe', 'x.html', 'CON.png', 'x:bad.png', '.hidden.png'])
def test_rejects_invalid_files_before_writing(tmp_path, monkeypatch, name):
    monkeypatch.setattr(web, 'OUTPUTS_DIR', tmp_path)
    with pytest.raises(web.HTTPException):
        asyncio.run(web._store_media_upload([upload(name)], ''))
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('data,limit', [(b'', 10), (b'toolarge', 3)])
def test_failure_rolls_back_entire_batch(tmp_path, monkeypatch, data, limit):
    monkeypatch.setattr(web, 'OUTPUTS_DIR', tmp_path)
    monkeypatch.setattr(web, 'MAX_LIBRARY_FILE_BYTES', limit)
    with pytest.raises(web.HTTPException):
        asyncio.run(web._store_media_upload([upload('good.png', b'a'), upload('bad.mp4', data)], ''))
    assert not list(tmp_path.iterdir())


def test_local_publish_upload_is_hidden_but_usable_for_publishing(tmp_path, monkeypatch):
    monkeypatch.setattr(web, 'OUTPUTS_DIR', tmp_path)
    result = asyncio.run(web.api_publish_media_upload([upload('clip.mp4')]))
    file = result['files'][0]
    assert file['path'].startswith('_publish/media/')
    assert web.get_output_tree() == []
    assert web._safe_output_path(file['path']).read_bytes() == b'media'
    with pytest.raises(web.HTTPException):
        asyncio.run(web.api_publish_media_upload([upload('voice.wav')]))


def test_relocated_local_upload_remains_readable_by_old_reference(tmp_path, monkeypatch):
    monkeypatch.setattr(web, 'OUTPUTS_DIR', tmp_path)
    old = '本地素材-20261015-223915-b465e761/clip.mp4'
    moved = tmp_path / '_publish' / 'media' / old
    moved.parent.mkdir(parents=True)
    moved.write_bytes(b'preserved')
    assert web._safe_output_path(old) == moved
    assert web.get_output_tree() == []
