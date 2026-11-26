#!/usr/bin/env python3
"""Clipify captions: legacy positional arguments plus explicit canvas options."""
import argparse
import json
import shutil
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from easel.clipify_captions import validate_transcript, cues_for_clip, write_captions


def main(argv=None):
    parser=argparse.ArgumentParser(description="中英文ASS字幕（真实词级时间戳）")
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("style",nargs="?",default="opus",choices=("opus","karaoke","minimal"))
    parser.add_argument("--width",type=int,default=1080)
    parser.add_argument("--height",type=int,default=1920)
    args=parser.parse_args(argv)
    if args.width<64 or args.height<64:parser.error("字幕画布尺寸无效")
    data=json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
    end=max((float(s["end"]) for s in data.get("segments",[])),default=0)
    rows=validate_transcript(data,end)
    cues=cues_for_clip(rows,0,end,max_chars=18 if args.width<args.height else 22)
    folder=Path(args.output).resolve().parent
    folder.mkdir(parents=True,exist_ok=True)
    words=[w for row in rows for w in row.get("words",[])]
    result=write_captions(cues,folder,args.width,args.height,style=args.style,words=words)
    default=folder/"captions.ass"
    if default!=Path(args.output).resolve():shutil.copyfile(default,args.output)
    print(json.dumps(result,ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
