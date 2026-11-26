#!/usr/bin/env python3
"""faster-whisper 词级转录 → JSON（字幕 / 场景数据原料）。

用法:
  python transcribe.py --src video.mp4 --out transcript.json
  python transcribe.py --src video.mp4 --out t.json --model <模型目录> --device cuda

说明:
  - 口播建议 vad_filter=False：软语音被当静音切掉是常见事故源。
  - 模型本地路径或名称均可；可用 tools/fetch_whisper_model.py 拉取 large-v3。
  - HF_ENDPOINT 默认走国内镜像（hf-mirror.com），境外环境可删。
依赖: faster-whisper（见 deps/DEPS.md）
"""
import argparse
import json
import os
import shutil
import subprocess
import time

os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')
os.environ.setdefault('HF_HUB_DISABLE_XET', '1')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True, help='音/视频源')
    ap.add_argument('--out', required=True, help='输出 JSON')
    ap.add_argument('--model', default=os.environ.get('EASEL_WHISPER_MODEL', 'large-v3'), help='模型名或本地目录')
    ap.add_argument('--lang', default='zh')
    ap.add_argument('--device', default=os.environ.get('EASEL_WHISPER_DEVICE', 'cuda'))
    ap.add_argument('--compute', default=os.environ.get('EASEL_WHISPER_COMPUTE', 'float16'))
    args = ap.parse_args()

    cuda_dir = os.environ.get('EASEL_CUDA_LIBRARY_DIR', '')
    if args.device == 'cuda' and os.path.isdir(cuda_dir):
        os.environ['PATH'] = cuda_dir + os.pathsep + os.environ.get('PATH', '')
        dll_directory = os.add_dll_directory(cuda_dir) if os.name == 'nt' else None

    from faster_whisper import WhisperModel

    t0 = time.time()
    print('loading model...', flush=True)
    model = WhisperModel(args.model, device=args.device, compute_type=args.compute)
    print(f'model loaded {time.time() - t0:.1f}s', flush=True)

    t1 = time.time()
    try:
        segments, info = model.transcribe(
            args.src, language=args.lang, word_timestamps=True, vad_filter=False, beam_size=5)
    except TypeError as error:
        if 'metadata_errors' not in str(error):
            raise
        # PyAV 19 removed this argument used by faster-whisper 1.2.1.
        # Reuse the installed FFmpeg decoder without changing shared packages.
        import numpy as np
        decoded = subprocess.run([shutil.which('ffmpeg') or 'ffmpeg', '-v', 'error',
            '-i', args.src, '-f', 'f32le', '-ac', '1', '-ar', '16000', 'pipe:1'],
            capture_output=True, check=True)
        audio = np.frombuffer(decoded.stdout, dtype=np.float32)
        segments, info = model.transcribe(
            audio, language=args.lang, word_timestamps=True, vad_filter=False, beam_size=5)
    result = {'language': info.language, 'duration': info.duration, 'segments': []}
    for s in segments:
        result['segments'].append({
            'start': round(s.start, 3),
            'end': round(s.end, 3),
            'text': s.text.strip(),
            'words': [{'word': w.word, 'start': round(w.start, 3), 'end': round(w.end, 3)} for w in (s.words or [])],
        })

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f'DONE {len(result["segments"])} segments in {time.time() - t1:.1f}s → {args.out}', flush=True)


if __name__ == '__main__':
    main()
