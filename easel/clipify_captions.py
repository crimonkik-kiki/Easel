"""Chinese/English subtitle grouping using actual word timestamps."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from easel.clipify_media import ClipifyError, finite


# Normalize at delivery as well as grouping: cached ASR/imported/revised cues
# must obey the same script policy without changing their timing evidence.
SUBTITLE_POLICY = 'zh-Hans-t2s-v1'

@lru_cache(maxsize=1)
def _converter():
    from opencc import OpenCC
    return OpenCC('t2s')


def simplified(text: str) -> str:
    return _converter().convert(text)


def simplified_cues(cues: list[dict]) -> list[dict]:
    return [{**cue, 'text': simplified(cue['text'])} for cue in cues]


def text_join(words: list[dict]) -> str:
    text = ''.join(w['word'] for w in words).strip()
    text = re.sub(r'(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])', '', text)
    return simplified(re.sub(r'\s+([，。！？、；：,.!?;:])', r'\1', text))


def validate_transcript(data: dict, duration: float) -> list[dict]:
    rows = data.get('segments')
    if not isinstance(rows, list):
        raise ClipifyError('转录必须含 segments 数组。')
    last = -1.0
    seen = set()
    for index, row in enumerate(rows):
        if not isinstance(row,dict):raise ClipifyError('转录段必须是对象。')
        start, end = finite(row.get('start')), finite(row.get('end'))
        if not 0 <= start < end <= duration + .15 or start < last - .03:
            raise ClipifyError(f'转录第{index + 1}段时间越界或顺序无效。')
        if not isinstance(row.get('text'), str):
            raise ClipifyError('转录文字必须是字符串。')
        previous = start - .05
        for word in row.get('words', []):
            a, b = finite(word.get('start')), finite(word.get('end'))
            if not isinstance(word.get('word'), str) or not start - .1 <= a <= b <= end + .15 or a < previous - .03:
                raise ClipifyError('逐词时间戳无效。')
            previous = b
        row.setdefault('id', f's{index:06d}')
        if not isinstance(row['id'],str) or not row['id'] or row['id'] in seen:
            raise ClipifyError('转录段ID重复或无效。')
        seen.add(row['id'])
        last = end
    return rows


def cues_for_clip(rows: list[dict], start: float, end: float, *, max_chars: int = 22) -> list[dict]:
    words = []
    segment_only = []
    for row in rows:
        if row['end'] <= start or row['start'] >= end:
            continue
        if row.get('words'):
            for word in row['words']:
                if word['end'] > start and word['start'] < end and word['word'].strip():
                    words.append({**word, 'start': max(0., word['start'] - start),
                                  'end': min(end - start, word['end'] - start)})
        else:
            # Preserve actual segment timings; never fabricate per-word timing.
            segment_only.append({'start': max(0., row['start'] - start),
                                 'end': min(end - start, row['end'] - start), 'text': row['text'].strip()})
    if segment_only and words:
        raise ClipifyError('片段混合段级与词级时间，请重新转录后生成字幕。')
    if segment_only:
        return simplified_cues(segment_only)
    result, chunk = [], []
    for index, word in enumerate(words):
        chunk.append(word)
        text = text_join(chunk)
        following = words[index + 1] if index + 1 < len(words) else None
        if (len(text) >= max_chars or word['end'] - chunk[0]['start'] >= 4.5
                or (len(text) >= 10 and re.search(r'[，。！？,.!?;；]$', text))
                or following is None or following['start'] - word['end'] > .8):
            stop = min(end - start, word['end'] + .10)
            if following:
                stop = min(stop, following['start'])
            if stop > chunk[0]['start']:
                result.append({'start': chunk[0]['start'], 'end': stop, 'text': text})
            chunk = []
    return result


def stamp(value: float, *, srt: bool = False) -> str:
    units = 1000 if srt else 100
    ticks = max(0, round(value * units))
    h, ticks = divmod(ticks, 3600 * units)
    m, ticks = divmod(ticks, 60 * units)
    s, sub = divmod(ticks, units)
    return f'{h:02d}:{m:02d}:{s:02d},{sub:03d}' if srt else f'{h}:{m:02d}:{s:02d}.{sub:02d}'


def wrap(text: str, limit: int = 24) -> str:
    # Escape ASS control sequences from recognized speech or imported text.
    text = text.replace('\\', '＼').replace('{', '｛').replace('}', '｝').replace('\n', ' ')
    if len(text) <= limit:
        return text
    if len(text) > limit * 2:
        raise ClipifyError('单条字幕过长，请提供词级时间戳或缩短分句，不能丢弃后半句。')
    return text[:limit] + r'\N' + text[limit:]


def write_captions(cues: list[dict], folder: Path, width: int, height: int,
                   *, style: str = 'minimal', words: list[dict] | None = None) -> dict:
    if not cues:
        raise ClipifyError('片段没有有效字幕，不能交付空字幕成片。')
    if style not in ('minimal','opus','karaoke'):
        raise ClipifyError('字幕样式无效。')
    if style!='minimal' and not words:
        raise ClipifyError('逐字高亮需要真实词级时间戳。')
    cues = simplified_cues(cues)
    if words is not None:
        words = [{**word, 'word': simplified(word['word'])} for word in words]
    previous = 0.
    for cue in cues:
        if not 0 <= cue['start'] < cue['end'] or cue['start'] < previous - .02:
            raise ClipifyError('字幕重叠或时间无效。')
        previous = cue['end']
    font = 'Microsoft YaHei' if Path('C:/Windows/Fonts/msyh.ttc').exists() else 'sans-serif'
    size = max(24, round(min(width / 1080, height / 1920) * 52)) if width < height else max(24, round(width / 2560 * 60))
    margin = max(48, round(height * (.11 if width > height else .12)))
    header = (f'[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 2\n'
              'ScaledBorderAndShadow: yes\n\n[V4+ Styles]\n'
              'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n'
              f'Style: Default,{font},{size},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,3,0,2,48,48,{margin},1\n\n'
              '[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n')
    events=[]
    limit=20 if width<height else 24
    for cue in cues:
        if style=='minimal':
            events.append((cue['start'],cue['end'],wrap(cue['text'],limit)))
        else:
            group=[w for w in words if cue['start']<=w['start']<cue['end']]
            color='&H0000FFFF&' if style=='opus' else '&H0000FF00&'
            for index,word in enumerate(group):
                stop=min(cue['end'],group[index+1]['start'] if index+1<len(group) else word['end']+.1)
                if stop<=word['start']:continue
                parts=[wrap(w['word'],limit) for w in group]
                parts[index]='{\\c'+color+'}'+parts[index]+'{\\c&H00FFFFFF&}'
                events.append((word['start'],stop,''.join(parts)))
    (folder / 'captions.ass').write_text(header + '\n'.join(
        f'Dialogue: 0,{stamp(a)},{stamp(b)},Default,,0,0,0,,{text}' for a,b,text in events)+'\n',encoding='utf-8')
    (folder / 'captions.srt').write_text('\n\n'.join(
        f"{i}\n{stamp(c['start'], srt=True)} --> {stamp(c['end'], srt=True)}\n{c['text']}"
        for i, c in enumerate(cues, 1)) + '\n', encoding='utf-8')
    return {'events': len(cues), 'width': width, 'height': height, 'font': font,
            'language': 'zh-Hans', 'script_policy': SUBTITLE_POLICY,
            'review': '自动识别，未逐句听校'}
