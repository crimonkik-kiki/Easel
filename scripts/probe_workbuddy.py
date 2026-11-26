"""Bounded ACP probe; no credential copying and no model prompt by default."""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', action='store_true')
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--prompt', action='store_true', help='Send one fixed text-only test; tools disabled')
    args = parser.parse_args()
    folder = ROOT / 'tmp/workbuddy-probe'
    folder.mkdir(parents=True, exist_ok=True)
    config = folder / 'config'
    config.mkdir(exist_ok=True)
    env = {**os.environ, 'CODEBUDDY_CONFIG_DIR':str(config),
           'NODE_COMPILE_CACHE':str(folder/'node-cache'), 'NO_COLOR':'1',
           'CODEBUDDY_FORCE_LITE_WB_BUNDLE':'1'}
    env.pop('CODEBUDDY_API_KEY', None)
    command = [r'D:\Codexspace\Easel-runtime\node-v24.22.0-win-x64\node.exe',
               r'D:\workbuddy\resources\app.asar.unpacked\cli\bin\codebuddy', '--acp']
    if args.serve:
        command += ['--serve', '--host', '127.0.0.1']
    if args.prompt:
        command += ['--tools', '', '--strict-mcp-config']
    process = subprocess.Popen(command, cwd=folder, env=env, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
    lines = queue.Queue()
    diagnostic = []
    chunks = []
    def read_output():
        for line in process.stdout:
            lines.put(line)
        lines.put(None)
    def drain_errors():
        for line in process.stderr:
            if len(diagnostic) < 20:
                diagnostic.append(line[:300])
    threading.Thread(target=read_output, daemon=True).start()
    error_reader=threading.Thread(target=drain_errors, daemon=True)
    error_reader.start()
    def call(identifier, method, params):
        process.stdin.write(json.dumps({'jsonrpc':'2.0','id':identifier,'method':method,'params':params})+'\n')
        process.stdin.flush()
        deadline = time.monotonic()+25
        while time.monotonic()<deadline:
            try:
                line=lines.get(timeout=max(.1,deadline-time.monotonic()))
            except queue.Empty:
                break
            if line is None:
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                error_reader.join(timeout=2)
                (folder/'startup-diagnostic.txt').write_text(''.join(diagnostic),encoding='utf-8')
                raise RuntimeError('ACP process exited before reply')
            try:
                reply=json.loads(line)
            except ValueError:
                continue
            if isinstance(reply,dict) and reply.get('id')==identifier:
                return reply
            if isinstance(reply,dict) and reply.get('method')=='session/update':
                update=(reply.get('params') or {}).get('update') or {}
                if update.get('sessionUpdate')=='agent_message_chunk':
                    chunks.append(str((update.get('content') or {}).get('text',''))[:1000])
            elif isinstance(reply,dict) and 'method' in reply and 'id' in reply:
                process.stdin.write(json.dumps({'jsonrpc':'2.0','id':reply['id'],'result':{'outcome':{'outcome':'cancelled'}}})+'\n')
                process.stdin.flush()
        raise TimeoutError('ACP did not answer '+method)
    try:
        initialized=call(1,'initialize',{'protocolVersion':1,'clientInfo':{'name':'easel-probe','version':'0.1'},
            'clientCapabilities':{'fs':{'readTextFile':False,'writeTextFile':False},'terminal':False}})
        result=initialized.get('result',{})
        evidence={'protocolVersion':result.get('protocolVersion'),'capabilities':result.get('agentCapabilities'),
                  'authMethods':[m.get('id') for m in result.get('authMethods',[])], 'error':initialized.get('error')}
        if (args.session or args.prompt) and result.get('protocolVersion')==1:
            response=call(2,'session/new',{'cwd':str(folder),'mcpServers':[]})
            evidence['sessionCreated']=bool(response.get('result',{}).get('sessionId'))
            evidence['sessionError']=response.get('error')
            if args.prompt and evidence['sessionCreated']:
                answer=call(3,'session/prompt',{'sessionId':response['result']['sessionId'],
                    'prompt':[{'type':'text','text':'这是 Easel 连通性测试。请只回复 EASEL_WORKBUDDY_OK；不要调用工具、读取文件或执行命令。'}]})
                evidence['promptResult']=answer.get('result')
                evidence['promptError']=answer.get('error')
                evidence['reply']=''.join(chunks)[:1000]
        print(json.dumps(evidence,ensure_ascii=False),flush=True)
        (folder/'handshake-result.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    except Exception as error:
        print(json.dumps({'probeError':str(error),'processExit':process.poll(),
                          'diagnosticKinds':{'auth':any('auth' in s.lower() for s in diagnostic),
                                             'network':any('ENOTFOUND' in s or 'ECONN' in s for s in diagnostic)}},ensure_ascii=False),flush=True)
        raise SystemExit(2)
    finally:
        if process.poll() is None:
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__=='__main__':
    main()
