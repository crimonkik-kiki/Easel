#!/usr/bin/env python3
"""Build crop expressions; reject empty timelines and out-of-frame coordinates."""
import argparse
import json
import math
from pathlib import Path


def expression(segments, left, right, source_width=None, crop_width=None):
    if not isinstance(segments,list) or not segments:raise ValueError('说话人时间线为空')
    if left<0 or right<0:raise ValueError('裁切位置不能小于0')
    if (source_width is None)!=(crop_width is None):raise ValueError('源宽度和裁切宽度需同时指定')
    if source_width is not None and (crop_width<=0 or source_width<crop_width or max(left,right)>source_width-crop_width):
        raise ValueError('裁切位置超出画面')
    previous=-1.
    for row in segments:
        a,b=float(row['start']),float(row['end'])
        if not math.isfinite(a) or not math.isfinite(b) or not 0<=a<b or a<previous:
            raise ValueError('时间线顺序无效')
        if row['speaker'] not in ('left','right'):raise ValueError('未知说话人')
        previous=b
    def x(row):return left if row['speaker']=='left' else right
    result=str(x(segments[-1]))
    for row in reversed(segments[:-1]):
        result=f"if(lt(t\\,{row['end']:.4f})\\,{x(row)}\\,{result})"
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input');parser.add_argument('left',type=int);parser.add_argument('right',type=int)
    parser.add_argument('--source-width',type=int);parser.add_argument('--crop-width',type=int)
    args=parser.parse_args(argv)
    try:
        print(expression(json.loads(Path(args.input).read_text(encoding='utf-8-sig')),args.left,args.right,args.source_width,args.crop_width))
    except (OSError,ValueError,KeyError,TypeError) as error:parser.exit(2,f'裁切表达式失败：{error}\n')


if __name__=='__main__':main()
