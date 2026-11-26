"""Exercise the built workbench against simulated Clipify jobs only."""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
import uvicorn


def run(dist: Path, repeat=3):
    work=ROOT/'tmp/clipify-ui';work.mkdir(parents=True,exist_ok=True)
    from easel.clipify_media import ffmpeg
    fixture=work/'isolated-preview.mp4'
    if not fixture.exists():
        subprocess.run([ffmpeg(),'-v','error','-nostdin','-y','-f','lavfi','-i','testsrc=size=320x180:rate=10:duration=2','-f','lavfi','-i','sine=frequency=300:sample_rate=16000:duration=2','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(fixture)],check=True,capture_output=True,timeout=30)
    results=[]
    app=FastAPI()
    state={'created':None,'cancelled':False,'resumed':False,'gets':0,'revised':False,'posts':[]}
    identifier='clipify-'+'1'*16
    revision='clipify-'+'2'*16
    def job(which=identifier):
        completed=state['resumed'] or which==revision
        return {'id':which,'state':'completed' if completed else 'cancelled' if state['cancelled'] else 'transcribing',
            'source':r'D:\模拟素材\测试课程.mp4','message':'测试成片已完成' if completed else '正在转录模拟课程',
            'error':'','progress':100 if completed else 30,
            'options':{'aspect':'9:16','count':1 if which==revision else 3,'minimum':20,'maximum':60},
            'clips':[{'file':'clip-01/video.mp4','title':'模拟知识片段','duration':25.0,'width':1080,'height':1920,
                      'subtitle':{'review':'用户修订字幕' if which==revision else '自动识别，未逐句听校'}}] if completed else []}

    @app.api_route('/api/{path:path}',methods=['GET','POST'])
    async def api(path: str,request: Request):
        if request.method=='POST':
            if path=='clipify/upload':
                form=await request.form();file=form['file'];body=await file.read()
                state['posts'].append({'path':path,'data':{'name':file.filename,'size':len(body)}})
                return {'source':'D:/模拟上传/'+file.filename,'name':file.filename,'size':len(body),'duration':20,'width':1920,'height':1080}
            body=await request.body();data=json.loads(body or '{}')
            state['posts'].append({'path':path,'data':data})
            if path=='clipify/tasks':state['created']=data;return job()
            if path.endswith('/cancel'):state['cancelled']=True;return {**job(),'cancel_requested':True}
            if path.endswith('/resume'):state['resumed']=True;return job()
            if '/captions/' in path:
                state['revised']=True;return job(revision)
            raise AssertionError('Unexpected write: '+path)
        if path=='status':return {'gateway':True,'transport':'native','runtime':'codex','personas':[],'skills':[]}
        if path=='settings/bootstrap':return {'modelConfigured':True}
        if path=='trends':return {'trends':[]}
        if path=='clipify/check':return {'ready':True}
        if path=='clipify/tasks':return [job()] if state['created'] else []
        if '/captions/' in path:return [{'start':0.,'end':4.,'text':'这是自动识别的字幕'}]
        if path.startswith('clipify/tasks/'):
            state['gets']+=1;return job(path.split('/')[2])
        if path.startswith('media/'):
            return FileResponse(fixture)
        return []

    @app.get('/assets/{name:path}')
    def asset(name: str):
        path=(dist/'assets'/name).resolve()
        if not path.is_relative_to((dist/'assets').resolve()):raise ValueError('asset path')
        return FileResponse(path)

    @app.get('/')
    def home():return FileResponse(dist/'index.html')

    listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='off'))
    thread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True);thread.start()
    while not server.started:time.sleep(.02)
    from playwright.sync_api import sync_playwright,expect
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel='msedge',headless=True)
            for iteration in range(repeat):
                state.update(created=None,cancelled=False,resumed=False,gets=0,revised=False,posts=[])
                context=browser.new_context(viewport={'width':1440,'height':1080})
                context.add_init_script("localStorage.setItem('easel_onboarding_seen','1')")
                blocked=[];errors=[]
                def guard(route):
                    from urllib.parse import urlsplit
                    url=urlsplit(route.request.url)
                    if url.hostname not in ('127.0.0.1','localhost') or url.port!=port:
                        if url.hostname not in ('fonts.googleapis.com','fonts.gstatic.com'):blocked.append(url.hostname)
                        route.abort()
                    else:route.continue_()
                context.route('**/*',guard)
                page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{port}/')
                expect(page.get_by_role('button',name='直播切片',exact=True)).to_be_visible()
                assert state['posts']==[],'mounting must not start processing'
                page.get_by_role('button',name='直播切片',exact=True).click()
                expect(page.get_by_role('button',name='直播切片',exact=True)).to_have_class(__import__('re').compile(r'\bactive\b'))
                panel=page.get_by_role('region',name='中文直播切片')
                panel.get_by_label('切片输出画幅').select_option('9:16')
                panel.get_by_label('选择视频素材',exact=True).set_input_files({'name':'点击选择课程.mp4','mimeType':'video/mp4','buffer':b'mock video'})
                expect(panel.get_by_label('本地视频路径')).to_have_value('D:/模拟上传/点击选择课程.mp4')
                assert state['created'] is None
                transfer=page.evaluate_handle("""() => {const d=new DataTransfer();d.items.add(new File(['mock video'],'拖拽课程.mp4',{type:'video/mp4'}));return d;}""")
                panel.get_by_role('region',name='视频素材上传区').dispatch_event('drop',{'dataTransfer':transfer})
                expect(panel.get_by_label('本地视频路径')).to_have_value('D:/模拟上传/拖拽课程.mp4')
                assert state['created'] is None
                bad=page.evaluate_handle("""() => {const d=new DataTransfer();d.items.add(new File(['bad'],'错误.txt'));return d;}""")
                panel.get_by_role('region',name='视频素材上传区').dispatch_event('drop',{'dataTransfer':bad})
                expect(panel.get_by_text('请选择支持的视频文件',exact=True)).to_be_visible()
                expect(panel.get_by_label('本地视频路径')).to_have_value('D:/模拟上传/拖拽课程.mp4')
                panel.get_by_role('button',name='生成带字幕短片',exact=True).click()
                expect(panel.get_by_role('button',name='取消任务',exact=True)).to_be_visible()
                assert state['created']['aspect']=='9:16' and state['created']['count']==3
                assert state['created']['source']=='D:/模拟上传/拖拽课程.mp4'
                panel.get_by_role('button',name='取消任务',exact=True).click()
                expect(panel.get_by_role('button',name='恢复／重新选段',exact=True)).to_be_visible()
                panel.get_by_role('button',name='恢复／重新选段',exact=True).click()
                expect(panel.get_by_text('测试成片已完成',exact=True)).to_be_visible()
                assert state['gets']>=2,'same-id resume must keep polling'
                panel.get_by_role('button',name='校对字幕',exact=True).click()
                panel.get_by_label('字幕第1句').fill('这是用户修订后的字幕')
                panel.get_by_role('button',name='生成字幕修订版',exact=True).click()
                expect(panel.get_by_text('用户修订字幕',exact=False)).to_be_visible()
                assert state['revised']
                assert next(p['data']['cues'][0]['text'] for p in state['posts'] if '/captions/' in p['path'])=='这是用户修订后的字幕'
                posts_before_navigation=len(state['posts'])
                page.get_by_role('button',name='内容库',exact=True).click()
                expect(page.get_by_role('region',name='中文直播切片')).to_have_count(0)
                assert len(state['posts'])==posts_before_navigation
                page.reload()
                page.get_by_role('button',name='直播切片',exact=True).click()
                expect(page.get_by_role('button',name='直播切片',exact=True)).to_have_class(__import__('re').compile(r'\bactive\b'))
                panel=page.get_by_role('region',name='中文直播切片')
                expect(panel.get_by_label('切片输出画幅')).to_have_value('9:16')
                expect(panel.get_by_text('用户修订字幕',exact=False)).to_be_visible()
                preview=panel.locator('video').first
                expect(preview).to_be_visible()
                page.wait_for_function("document.querySelector('.clipify-preview')?.readyState >= 1")
                geometry=preview.evaluate("el => {const r=el.getBoundingClientRect();return {width:r.width,height:r.height,container:el.parentElement.getBoundingClientRect().width,fit:getComputedStyle(el).objectFit}}")
                assert geometry['width']>=800 and abs(geometry['width']-geometry['container'])<2,geometry
                assert geometry['width']/geometry['height']>=1.7 and geometry['fit']=='contain',geometry
                if iteration==0:
                    page.screenshot(path=str(work/'desktop.png'),full_page=True)
                    page.set_viewport_size({'width':720,'height':1000})
                    page.screenshot(path=str(work/'narrow.png'),full_page=True)
                    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth+2')
                assert not blocked and not errors,(blocked,errors)
                results.append({'run':iteration+1,'passed':True,'posts':len(state['posts']),'external_visits':0})
                context.close()
            browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=5)
    (work/'result.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps(results))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--dist',default='tmp/clipify-dist')
    args=parser.parse_args();run((ROOT/args.dist).resolve())
