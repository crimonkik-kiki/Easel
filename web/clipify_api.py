"""Clipify API: isolated subprocesses, disk progress and restart-safe OS locks."""
from __future__ import annotations

import os
import json
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import threading
import uuid

from fastapi import File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from easel import clipify


MAX_CLIPIFY_UPLOAD_BYTES = 20 * 1024 ** 3
VIDEO_SUFFIXES = {'.mp4', '.mkv', '.mov', '.webm', '.avi', '.m4v'}


def store_clipify_upload(file: UploadFile, outputs: Path) -> dict:
    """Stream private source media without adding it to the content library."""
    folder = None
    try:
        name = (file.filename or '').replace('\\', '/').split('/')[-1]
        suffix = Path(name).suffix.lower()
        if suffix not in VIDEO_SUFFIXES:
            raise HTTPException(400, '请选择 MP4、MKV、MOV、WebM、AVI 或 M4V 视频文件')
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', Path(name).stem)[:150].strip(' .') or '视频素材'
        if re.match(r'^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)', name, re.I):
            name = '_' + name
        root = outputs.resolve()
        candidate = root / '_clipify_uploads' / uuid.uuid4().hex
        if not candidate.resolve().is_relative_to(root):
            raise HTTPException(403, '素材保存路径无效')
        candidate.mkdir(parents=True)
        folder = candidate
        target = folder / (name + suffix)
        temporary = folder / '.uploading'
        size = 0
        with temporary.open('xb') as stream:
            while chunk := file.file.read(4 * 1024 * 1024):
                size += len(chunk)
                if size > MAX_CLIPIFY_UPLOAD_BYTES:
                    raise HTTPException(413, '视频超过 20GB，请直接填写本地视频路径')
                stream.write(chunk)
        if not size:
            raise HTTPException(400, '视频文件为空')
        from easel.clipify_media import probe
        try:
            info = probe(temporary)
        except Exception as error:
            raise HTTPException(400, '无法读取视频，请确认文件完整且格式受支持') from error
        if not info.get('width') or not info.get('height') or not info.get('has_audio') or info.get('duration', 0) <= 0:
            raise HTTPException(400, '请选择含有效画面和音轨的视频素材')
        os.replace(temporary, target)
        return {'source': str(target), 'name': target.name, 'size': size,
                'duration': info['duration'], 'width': info['width'], 'height': info['height']}
    except BaseException:
        if folder is not None:
            for item in folder.iterdir():
                item.unlink(missing_ok=True)
            folder.rmdir()
        raise
    finally:
        file.file.close()


class NewClipifyTask(BaseModel):
    source: str = Field(min_length=1, max_length=2048)
    aspect: str = 'source'
    count: int = Field(default=3, ge=1, le=8, strict=True)
    minimum: float = Field(default=20, ge=5, le=180)
    maximum: float = Field(default=60, ge=5, le=180)


class Selection(BaseModel):
    segments: list[dict] = Field(min_length=1, max_length=8)


class Cue(BaseModel):
    start: float = Field(ge=0, allow_inf_nan=False, strict=True)
    end: float = Field(gt=0, allow_inf_nan=False, strict=True)
    text: str = Field(min_length=1,max_length=40,strict=True)


class CaptionRevision(BaseModel):
    cues: list[Cue] = Field(min_length=1,max_length=300)


class ClipifyTasks:
    def __init__(self, outputs):
        self.outputs = outputs
        self.processes: dict[str, subprocess.Popen] = {}
        self.lock = threading.RLock()

    def folder(self, identifier: str) -> Path:
        if not re.fullmatch(r'clipify-[a-f0-9]{16}', identifier):
            raise HTTPException(400, '任务ID无效')
        path = self.outputs() / identifier
        if not (path / 'manifest.json').is_file():
            raise HTTPException(404, '切片任务不存在')
        return path

    def status(self, identifier: str) -> dict:
        folder = self.folder(identifier)
        task = clipify.load(folder)
        if task['state'] in clipify.ACTIVE and (folder/'cancel.request').exists():
            task['cancel_requested'] = True
        # Do not infer that a subprocess died just because the web server restarted.
        # Resuming always has to acquire the worker's OS lock.
        if task['state'] in clipify.ACTIVE and identifier not in self.processes:
            try:
                with clipify.exclusive(folder/'.work/task.lock'):
                    task['can_resume']=True
                task['message']='处理占用已释放，可以恢复未完成阶段'
            except clipify.ClipifyError:
                task['message']+='（已有处理进程继续执行中）'
        return task

    def start(self, folder: Path, *, resume=False) -> dict:
        with self.lock:
            identifier = folder.name
            if identifier in self.processes and self.processes[identifier].poll() is None:
                raise HTTPException(409, '此任务仍在处理或取消中')
            for process in self.processes.values():
                if process.poll() is None:
                    raise HTTPException(409, '另一个视频正在处理，请稍后再试')
            # Probe the exact same cross-process lock held by CLI workers.
            try:
                with clipify.exclusive(self.outputs() / '_clipify.lock'):
                    pass
            except clipify.ClipifyError as error:
                raise HTTPException(409, str(error)) from error
            state = clipify.load(folder)
            if state['state'] == 'completed':
                raise HTTPException(409, '任务已完成；修改画幅请新建任务，已完成结果不会被覆盖')
            clipify.save(folder, state, state='starting', message='正在启动本地切片任务', error='')
            log = (folder / '.work/worker.log').open('a', encoding='utf-8')
            env = {**os.environ, 'PYTHONUTF8':'1', 'PYTHONIOENCODING':'utf-8', 'HF_HUB_OFFLINE':'1'}
            try:
                process = subprocess.Popen([sys.executable, '-m', 'easel.clipify',
                    'resume' if resume else 'run', '--job', identifier], cwd=clipify.ROOT,
                    env=env, stdout=log, stderr=log, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            except OSError as error:
                clipify.save(folder, state, state='failed', message='无法启动处理进程', error=type(error).__name__)
                raise HTTPException(500, '无法启动本地处理进程') from error
            finally:
                log.close()
            self.processes[identifier] = process

            def monitor():
                process.wait()
                with self.lock:
                    if self.processes.get(identifier) is not process:
                        return
                    self.processes.pop(identifier, None)
                    latest = clipify.load(folder)
                    if latest['state'] in clipify.ACTIVE:
                        clipify.save(folder, latest, state='interrupted', pid=None,
                            message='处理进程已停止，可恢复任务', error='进程退出；详见本任务处理日志')
            threading.Thread(target=monitor, daemon=True).start()
            return clipify.load(folder)

    def cancel(self, identifier: str) -> dict:
        folder = self.folder(identifier)
        state = clipify.load(folder)
        if state['state'] not in clipify.ACTIVE:
            return state
        # Cooperative cancellation is checked by ASR, the model call and FFmpeg.
        # Never kill all Python/FFmpeg processes or another task's PID.
        (folder / 'cancel.request').write_text('cancel', encoding='utf-8')
        return {**state, 'cancel_requested':True, 'message':'正在取消，等待本任务释放资源…'}


def register_clipify(app, outputs):
    tasks = ClipifyTasks(outputs)

    @app.post('/api/clipify/upload')
    def upload(file: UploadFile = File(...)):
        return store_clipify_upload(file, outputs())

    @app.get('/api/clipify/check')
    def check():
        try:
            return clipify.preflight()
        except Exception as error:
            return {'ready':False, 'error':str(error), 'aspects':list(clipify.ASPECTS)}

    @app.get('/api/clipify/tasks')
    def listing():
        result = []
        for folder in outputs().glob('clipify-*'):
            try:
                result.append(tasks.status(folder.name))
            except (ValueError, OSError, HTTPException, clipify.ClipifyError):
                continue
        return sorted(result,key=lambda t:t['created_at'],reverse=True)[:30]

    @app.post('/api/clipify/tasks')
    def create(request: NewClipifyTask):
        try:
            clipify.preflight()
            # Do not create discarded project folders when another job is active.
            with tasks.lock:
                with clipify.exclusive(outputs() / '_clipify.lock'):
                    folder = clipify.create(outputs(), request.source, aspect=request.aspect,
                        count=request.count,minimum=request.minimum,maximum=request.maximum)
                return tasks.start(folder)
        except clipify.ClipifyError as error:
            raise HTTPException(400,str(error)) from error

    @app.get('/api/clipify/tasks/{identifier}')
    def status(identifier: str):
        return tasks.status(identifier)

    @app.post('/api/clipify/tasks/{identifier}/cancel')
    def cancel(identifier: str):
        return tasks.cancel(identifier)

    @app.post('/api/clipify/tasks/{identifier}/resume')
    def resume(identifier: str):
        return tasks.start(tasks.folder(identifier),resume=True)

    @app.post('/api/clipify/tasks/{identifier}/selection')
    def selection(identifier: str, request: Selection):
        try:
            clipify.manual_selection(tasks.folder(identifier),request.model_dump())
            return tasks.status(identifier)
        except (clipify.ClipifyError, OSError, ValueError) as error:
            raise HTTPException(400,str(error)) from error

    @app.get('/api/clipify/tasks/{identifier}/captions/{index}')
    def captions(identifier: str,index: int):
        folder=tasks.folder(identifier);state=clipify.load(folder)
        if not 1<=index<=len(state['clips']):raise HTTPException(404,'片段不存在')
        path=folder/f'clip-{index:02d}/cues.json'
        if not path.exists():raise HTTPException(404,'没有可编辑字幕')
        return json.loads(path.read_text(encoding='utf-8'))

    @app.post('/api/clipify/tasks/{identifier}/captions/{index}')
    def revise(identifier: str,index: int,request: CaptionRevision):
        folder=tasks.folder(identifier);original=clipify.load(folder)
        if original['state']!='completed':raise HTTPException(409,'请等待成片完成后生成字幕修订版')
        if not 1<=index<=len(original['clips']):raise HTTPException(404,'片段不存在')
        clip=original['clips'][index-1];previous=0.
        for cue in request.cues:
            if not cue.text.strip() or not previous<=cue.start<cue.end<=clip['end']-clip['start']+.01:
                raise HTTPException(400,'字幕文字为空、时间重叠或超出片段时长')
            previous=cue.end
        transcript=folder/'transcript.json'
        if hashlib.sha256(transcript.read_bytes()).hexdigest()!=original['transcript_sha256']:
            raise HTTPException(409,'原始转录发生变化，请重新生成任务')
        try:
            with tasks.lock:
                with clipify.exclusive(outputs()/'_clipify.lock'):
                    options=original['options']
                    child=clipify.create(outputs(),original['source'],aspect=options['aspect'],count=1,
                        minimum=options['minimum'],maximum=options['maximum'],model=options['model'])
                    state=clipify.load(child)
                    clipify.save(child,state,media=original['media'],fingerprint=original['fingerprint'],
                        parent_task=identifier,asr_signature=original['asr_signature'])
                    clipify.atomic_json(child/'transcript.json',json.loads(transcript.read_text(encoding='utf-8')))
                    clipify.manual_selection(child,{'segments':[clip]})
                    clipify.atomic_json(child/'.work/subtitle-overrides.json',{'1':request.model_dump()['cues']})
                return tasks.start(child)
        except clipify.ClipifyError as error:
            raise HTTPException(400,str(error)) from error

    return tasks
