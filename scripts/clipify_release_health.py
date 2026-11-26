"""Passive checks for the restored workbench; never query a social platform."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from easel.clipify import ClipifyError, exclusive
from web.health_probe import ServiceUnavailable, ServiceUnhealthy, read_url


def preflight():
    status,body,_=read_url('http://127.0.0.1:7860','/api/accounts')
    try:accounts=json.loads(body)
    except ValueError:raise ServiceUnhealthy('账号页返回无效JSON')
    if status!=200 or not isinstance(accounts,list):raise ServiceUnhealthy('账号页数据接口不可用')
    code,_,_=read_url('http://127.0.0.1:7860','/api/account-execution')
    if code not in (200,404):raise ServiceUnhealthy('操作记录接口返回异常')
    # The user-restored version has no phase-2 operation endpoint. Its absence
    # is recorded, and occupancy is verified independently; 404 never means idle.
    command='Get-CimInstance Win32_Process | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress'
    result=subprocess.run(['powershell.exe','-NoProfile','-Command',command],capture_output=True,
        text=True,encoding='utf-8',errors='replace',timeout=20)
    if result.returncode:raise RuntimeError('无法核对Windows进程占用')
    processes=json.loads(result.stdout)
    pattern=r'(account_browser|account_stats|web_publisher|douyin_publish|xhs_publish|weixin_mp_stats|bili_login|weixin_mp_login|zhihu_answer|zhihu_comments_fetch|xhs_comment|publish)\.py'
    counts={'account_workers':0,'profile_browsers':0,'active_chat_locks':0,'clipify_workers':0}
    for item in processes:
        name=item.get('Name','').lower();command=item.get('CommandLine') or ''
        if name in ('python.exe','pythonw.exe') and re.search(pattern,command,re.I):counts['account_workers']+=1
        if name in ('msedge.exe','chrome.exe','chromium.exe') and '--user-data-dir' in command and re.search(r'Easel.*(?:_login|profile)|(?:_login|profile).*Easel',command,re.I):counts['profile_browsers']+=1
    for path in (ROOT/'outputs/_sessions').glob('*.lock'):
        try:
            with exclusive(path):pass
        except ClipifyError:counts['active_chat_locks']+=1
    lock=ROOT/'outputs/_clipify.lock'
    if lock.exists():
        try:
            with exclusive(lock):pass
        except ClipifyError:counts['clipify_workers']+=1
    return {'marker':'BUSY' if any(counts.values()) else 'IDLE','counts':counts,
            'operation_records_endpoint':'present' if code==200 else 'absent_in_restored_version',
            'occupancy_verified_by':'Windows processes plus OS session and Clipify locks'}


def evaluate(dist: Path, fetch=read_url):
    expected=(dist/'index.html').read_text(encoding='utf-8')
    match=re.search(r'/assets/index-[^" ]+\.js',expected)
    if not match:raise ValueError('候选构建没有JavaScript入口')
    checks={}
    code,body,content_type=fetch('http://127.0.0.1:7860','/')
    checks['root_and_tested_bundle']=code==200 and 'text/html' in content_type and match[0].encode() in body
    for path,kind in (('/api/accounts',list),('/api/outputs',list),('/api/clipify/tasks',list),('/api/clipify/check',dict)):
        code,body,_=fetch('http://127.0.0.1:7860',path)
        try:data=json.loads(body)
        except ValueError:raise ServiceUnhealthy(f'{path} 返回无效JSON')
        checks[path]=code==200 and isinstance(data,kind)
        if path=='/api/clipify/check':checks['local_media_ready']=isinstance(data,dict) and data.get('ready') is True
        if path=='/api/clipify/tasks' and isinstance(data,list) and data:
            identifier=data[0].get('id','')
            if not re.fullmatch(r'clipify-[a-f0-9]{16}',identifier):raise ServiceUnhealthy('任务ID结构异常')
            status,detail,_=fetch('http://127.0.0.1:7860','/api/clipify/tasks/'+identifier)
            try:parsed=json.loads(detail)
            except ValueError:raise ServiceUnhealthy('任务详情返回无效JSON')
            checks['task_detail']=status==200 and isinstance(parsed,dict) and parsed.get('id')==identifier
    status,_,_=fetch('http://127.0.0.1:7860','/api/operations/accounts')
    checks['operations_remains_removed']=status==404
    if not all(checks.values()):raise ServiceUnhealthy(json.dumps(checks))
    return {'marker':'HEALTHY','checks':checks,'login_or_publish_requests':0}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--preflight',action='store_true')
    parser.add_argument('--dist',default='tmp/clipify-dist');args=parser.parse_args()
    try:
        result=preflight() if args.preflight else evaluate((ROOT/args.dist).resolve())
        print(json.dumps(result,ensure_ascii=False));return 10 if result['marker']=='BUSY' else 0
    except ServiceUnavailable as error:
        print(json.dumps({'marker':'SERVICE_UNAVAILABLE','error':str(error)},ensure_ascii=False));return 2
    except ServiceUnhealthy as error:
        print(json.dumps({'marker':'SERVICE_UNHEALTHY','error':str(error)},ensure_ascii=False));return 2
    except Exception as error:
        print(json.dumps({'marker':'PROBE_ERROR_MANUAL_REVIEW','error':f'{type(error).__name__}: {error}'},ensure_ascii=False));return 3


if __name__=='__main__':raise SystemExit(main())
