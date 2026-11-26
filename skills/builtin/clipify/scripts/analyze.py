#!/usr/bin/env python3
"""Fixed-camera two-ROI speaker timeline using actual FFmpeg PTS, never assumed FPS."""
import argparse
from bisect import bisect_left, bisect_right
import json
import math
from pathlib import Path
import re
from statistics import median


def parse(path):
    times, values = [], []
    current = None
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        match = re.search(r'pts_time:([0-9.eE+-]+)',line)
        if match:
            current=float(match[1]);continue
        match=re.match(r'lavfi\.signalstats\.YAVG=([0-9.eE+-]+)',line)
        if match and current is not None:
            value=float(match[1])
            if not math.isfinite(value) or not math.isfinite(current) or value<0 or current<0:
                raise ValueError('运动日志含无效数值')
            times.append(current);values.append(value);current=None
    if len(times)<2 or any(b<=a for a,b in zip(times,times[1:])):
        raise ValueError('运动日志至少需要两个时间递增的有效采样')
    return times,values


def timeline(left, right, min_duration=1.0):
    if min_duration<=0:raise ValueError('最短停留时间必须大于0')
    times,lv=parse(left);rt,rv=parse(right)
    if len(times)!=len(rt) or any(abs(a-b)>.001 for a,b in zip(times,rt)):
        raise ValueError('左右运动日志的时间线不一致')
    def smooth(values):
        average=sum(values)/len(values)
        normalized=[v/average if average>0 else 0 for v in values]
        prefix=[0.]
        for value in normalized:prefix.append(prefix[-1]+value)
        result=[]
        for t in times:
            a=bisect_left(times,t-.25);b=bisect_right(times,t+.25)
            result.append((prefix[b]-prefix[a])/(b-a))
        return result
    left_values,right_values=smooth(lv),smooth(rv)
    current=0 if left_values[0]>=right_values[0] else 1
    segments=[];start=times[0]
    for i,t in enumerate(times):
        following=current
        if current==0 and right_values[i]>left_values[i]*1.15:following=1
        elif current==1 and left_values[i]>right_values[i]*1.15:following=0
        if following!=current and t-start>=min_duration:
            segments.append({'start':start,'end':t,'speaker':'left' if current==0 else 'right'})
            start=t;current=following
    stop=times[-1]+median([b-a for a,b in zip(times,times[1:])])
    segments.append({'start':start,'end':stop,'speaker':'left' if current==0 else 'right'})
    return segments


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('left');parser.add_argument('right');parser.add_argument('min_duration',type=float,nargs='?',default=1.)
    args=parser.parse_args(argv)
    try:print(json.dumps(timeline(args.left,args.right,args.min_duration),ensure_ascii=False,indent=2))
    except (OSError,ValueError) as error:parser.exit(2,f'运动分析失败：{error}\n')


if __name__=='__main__':main()
