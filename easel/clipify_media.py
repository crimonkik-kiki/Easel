"""Media primitives shared by Clipify and ASR; no shell or global PATH mutation."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time
import wave

ROOT = Path(__file__).resolve().parents[1]


class ClipifyError(RuntimeError):
    pass


class Cancelled(ClipifyError):
    pass


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.writing')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def ffmpeg() -> str:
    candidates = [os.environ.get('EASEL_FFMPEG', ''),
                  str(ROOT.parent / 'Easel-runtime/bin/ffmpeg.exe'),
                  shutil.which('ffmpeg') or '']
    for value in candidates:
        if value and Path(value).is_file():
            return str(Path(value).resolve())
    raise ClipifyError('未找到 FFmpeg，请配置 EASEL_FFMPEG 或项目运行工具。')


def probe(path: Path) -> dict:
    """Use the public PyAV API, not the incompatible metadata_errors keyword."""
    import av
    try:
        with av.open(str(path)) as container:
            videos = list(container.streams.video)
            video = videos[0] if videos else None
            duration = float(container.duration / av.time_base) if container.duration else 0.0
            if not duration:
                duration = max((float(s.duration * s.time_base) for s in container.streams
                                if s.duration and s.time_base), default=0.0)
            rate = (video.base_rate or video.average_rate) if video else None
            return {'duration': duration, 'width': video.width if video else 0,
                    'height': video.height if video else 0,
                    'fps': str(rate) if rate else '', 'has_audio': bool(container.streams.audio),
                    'probe_backend': 'pyav', 'probe_version': av.__version__}
    except Exception as error:
        raise ClipifyError(f'无法读取媒体文件：{path.name}（{type(error).__name__}）') from error


def check_cancel(folder: Path | None) -> None:
    if folder is not None and (folder / 'cancel.request').exists():
        raise Cancelled('任务已取消，可以恢复未完成阶段。')


def run_media(arguments: list[str], log: Path, *, cwd: Path | None = None,
              cancel: Path | None = None, timeout: float = 1800) -> None:
    check_cancel(cancel)
    with log.open('w', encoding='utf-8') as output:
        process = subprocess.Popen([ffmpeg(), '-hide_banner', '-nostdin', *arguments],
            cwd=cwd, stdout=output, stderr=output,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        started = time.monotonic()
        try:
            while process.poll() is None:
                check_cancel(cancel)
                if time.monotonic() - started > timeout:
                    raise ClipifyError('媒体处理超时，请检查处理日志。')
                time.sleep(.15)
            if process.returncode:
                raise ClipifyError(f'FFmpeg 执行失败，详见 {log.name}')
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)


def pcm_array(path: Path):
    import numpy as np
    with wave.open(str(path), 'rb') as audio:
        if audio.getframerate() != 16000 or audio.getnchannels() != 1 or audio.getsampwidth() != 2:
            raise ClipifyError('转录输入必须是16kHz单声道16位PCM。')
        return np.frombuffer(audio.readframes(audio.getnframes()), dtype='<i2').astype(np.float32) / 32768


def fingerprint(path: Path, cancel: Path | None = None) -> dict:
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as source:
        while block := source.read(4 * 1024 * 1024):
            check_cancel(cancel)
            digest.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ClipifyError('源文件正在变化，请等待录制完成后重试。')
    return {'path': str(path.resolve()), 'size': after.st_size,
            'mtime_ns': after.st_mtime_ns, 'sha256': digest.hexdigest()}


def dimensions(width: int, height: int, aspect: str) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        raise ClipifyError('视频尺寸无效。')
    if aspect == 'source':
        # H.264 yuv420 needs even dimensions; do not silently crop odd sources.
        if width % 2 or height % 2:
            raise ClipifyError('源视频尺寸为奇数，请选择横屏或竖屏填充输出。')
        return width, height
    if aspect not in ('16:9', '9:16'):
        raise ClipifyError('画幅仅支持 source、16:9、9:16。')
    if (aspect == '16:9' and width * 9 == height * 16) or (aspect == '9:16' and width * 16 == height * 9):
        return width, height
    return (1920, 1080) if aspect == '16:9' else (1080, 1920)


def video_filter(source: dict, aspect: str, subtitle: str = 'captions.ass') -> tuple[str, str, tuple[int, int]]:
    width, height = dimensions(source['width'], source['height'], aspect)
    if (width, height) == (source['width'], source['height']):
        return f"ass={subtitle}", '-vf', (width, height)
    graph = (f'[0:v]split=2[bg][fg];[bg]scale={width}:{height}:force_original_aspect_ratio=increase,'
             f'crop={width}:{height},boxblur=24:2[back];'
             f'[fg]scale={width}:{height}:force_original_aspect_ratio=decrease[front];'
             f'[back][front]overlay=(W-w)/2:(H-h)/2,setsar=1,ass={subtitle}[v]')
    return graph, '-filter_complex', (width, height)


def finite(value) -> float:
    if isinstance(value, bool):
        raise ClipifyError('时间值不能是布尔值。')
    try:
        number = float(value)
    except (ValueError, TypeError) as error:
        raise ClipifyError('时间值必须是数字。') from error
    if not math.isfinite(number):
        raise ClipifyError('时间值必须是有限数。')
    return number


def precise_cut_input(source: Path | str, start: float, end: float) -> list[str]:
    start,end=finite(start),finite(end)
    if not 0<=start<end:
        raise ClipifyError('裁切起止时间无效。')
    # Accurate seek remains enabled while transcoding; duration is explicit.
    return ['-ss',f'{start:.6f}','-i',str(source),'-t',f'{end-start:.6f}']
