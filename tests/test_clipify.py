import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from easel import clipify as c
from easel import clipify_captions as captions
from easel import clipify_media as media


def module(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def rows():
    return [{'id':'s000000','start':0.,'end':6.,'text':'中文教学内容，自动生成清晰字幕。',
             'words':[{'start':i*.5,'end':i*.5+.45,'word':char} for i,char in enumerate('中文教学内容生成字幕效果')]}]


def task():
    return {'options':{'minimum':5,'maximum':60,'count':1,'aspect':'source'},'media':{'duration':20}}


@pytest.mark.parametrize('value',[float('nan'),float('inf'),True,None,'abc'])
def test_invalid_numeric_times_are_rejected(value):
    with pytest.raises(media.ClipifyError):media.finite(value)


@pytest.mark.parametrize('aspect,expected',[('source',(2560,1440)),('16:9',(2560,1440)),('9:16',(1080,1920))])
def test_aspect_preserves_original_screen_or_fits_complete_picture(aspect,expected):
    graph,flag,shape=media.video_filter({'width':2560,'height':1440},aspect)
    assert shape==expected
    if aspect=='9:16':
        assert 'force_original_aspect_ratio=decrease' in graph
        assert '[back][front]overlay' in graph
        assert flag=='-filter_complex'


@pytest.mark.parametrize('aspect',['bad','portrait','1:1'])
def test_invalid_aspect_rejected(aspect):
    with pytest.raises(media.ClipifyError):media.dimensions(2560,1440,aspect)


def test_odd_original_dimensions_do_not_silently_crop():
    with pytest.raises(media.ClipifyError):media.dimensions(321,181,'source')


@pytest.mark.parametrize('change',[{'start':-1},{'end':float('inf')},{'text':None},{'words':[{'start':8,'end':9,'word':'x'}]}])
def test_transcript_bad_times_and_word_evidence_rejected(change):
    data={'segments':rows()};data['segments'][0].update(change)
    with pytest.raises(media.ClipifyError):captions.validate_transcript(data,6)


def test_chinese_subtitles_have_actual_relative_word_times_and_no_markup_injection(tmp_path):
    transcript=rows();transcript[0]['words'][2]['word']='{\\pos(0,0)}中'
    cues=captions.cues_for_clip(transcript,1,5)
    result=captions.write_captions(cues,tmp_path,2560,1440)
    ass=(tmp_path/'captions.ass').read_text(encoding='utf-8')
    assert 'PlayResX: 2560' in ass and 'PlayResY: 1440' in ass
    assert '{\\pos' not in ass
    assert result['events']>0
    assert all(0<=row['start']<row['end']<=4 for row in cues)
    assert (tmp_path/'captions.srt').read_text(encoding='utf-8').startswith('1\n00:00:')


def test_long_caption_is_not_silently_truncated():
    with pytest.raises(media.ClipifyError):captions.wrap('中'*100,20)


def test_word_highlighting_requires_real_word_timestamps(tmp_path):
    with pytest.raises(media.ClipifyError):
        captions.write_captions([{'start':0,'end':1,'text':'测试'}],tmp_path,1080,1920,style='opus')


def test_mixed_word_and_segment_timings_cannot_fake_word_alignment():
    data=rows()+[{'start':6,'end':8,'text':'无词级时间'}]
    with pytest.raises(media.ClipifyError):captions.cues_for_clip(data,0,8)


@pytest.mark.parametrize('selection',[
    {'segments':[]}, {'segments':[{'first':'fake','last':'s000000'}]},
    {'segments':[{'start':0,'end':float('nan')}]},
    {'segments':[{'start':0,'end':4}]},
    {'segments':[{'start':0,'end':6},{'start':5,'end':11}]},
])
def test_invalid_and_overlapping_selection_cannot_render(selection):
    with pytest.raises(media.ClipifyError):c.validate_candidates(selection,rows(),task(),manual='start' in (selection['segments'][0] if selection['segments'] else {}))


def test_model_times_come_from_source_ids_not_fabricated_offsets():
    result=c.validate_candidates({'segments':[{'first':'s000000','last':'s000000','start':1000,'end':9999,'title':'课程'}]},rows(),task())
    assert result[0]['start']==0 and result[0]['end']==6
    assert result[0]['evidence']==['s000000']


def test_process_owned_lock_prevents_second_context_and_is_released(tmp_path):
    path=tmp_path/'task.lock'
    with c.exclusive(path):
        with pytest.raises(media.ClipifyError):
            with c.exclusive(path):pass
    with c.exclusive(path):pass


def test_cancel_is_observed_without_killing_unrelated_processes(tmp_path):
    (tmp_path/'cancel.request').write_text('cancel')
    with pytest.raises(media.Cancelled):media.check_cancel(tmp_path)


@pytest.mark.parametrize('fps',[20,25,30,60])
def test_roi_timeline_uses_actual_pts_for_each_frame_rate(tmp_path,fps):
    analyze=module('clipify_analyze',c.ROOT/'skills/builtin/clipify/scripts/analyze.py')
    for side in ('left','right'):
        path=tmp_path/side
        lines=[]
        for i in range(fps*5):
            value=10 if ((i<fps*2)==(side=='left')) else 1
            lines.append(f'frame:{i} pts:{i} pts_time:{i/fps:.8f}\nlavfi.signalstats.YAVG={value}')
        path.write_text('\n'.join(lines),encoding='utf-8')
    timeline=analyze.timeline(tmp_path/'left',tmp_path/'right')
    assert abs(timeline[-1]['end']-5)<.001
    assert timeline[0]['speaker']=='left' and timeline[-1]['speaker']=='right'


def test_varying_pts_and_bad_roi_input(tmp_path):
    analyze=module('clipify_analyze_variable',c.ROOT/'skills/builtin/clipify/scripts/analyze.py')
    a=tmp_path/'a';b=tmp_path/'b'
    a.write_text('frame:0 pts:0 pts_time:0\nlavfi.signalstats.YAVG=1\nframe:1 pts:1 pts_time:0.1\nlavfi.signalstats.YAVG=1')
    b.write_text(a.read_text().replace('pts_time:0.1','pts_time:0.2'))
    with pytest.raises(ValueError,match='时间线'):analyze.timeline(a,b)
    a.write_text('')
    with pytest.raises(ValueError,match='至少'):analyze.parse(a)


def test_pan_rejects_empty_or_out_of_frame_positions():
    pan=module('clipify_pan',c.ROOT/'skills/builtin/clipify/scripts/build_pan.py')
    with pytest.raises(ValueError):pan.expression([],0,10)
    with pytest.raises(ValueError):pan.expression([{'start':0,'end':1,'speaker':'left'}],0,1500,1920,608)


def test_legacy_asr_json_stays_compatible_and_word_mode_is_explicit():
    asr=module('clipify_legacy_asr',c.ROOT/'skills/shared/scripts/asr.py')
    old=json.loads(asr._render_json([(0,1,'测试')],{'language':'zh'}))
    assert old['segments']==[{'index':1,'start':0,'end':1,'text':'测试'}]
    extended=json.loads(asr._render_json([(0,1,'测试')],{'_word_segments':rows()}))
    assert extended['word_timestamps'] and extended['segments'][0]['words']
    assert '_word_segments' not in extended


@pytest.fixture(scope='module')
def video(tmp_path_factory):
    directory=tmp_path_factory.mktemp('clipify-中文 素材')
    path=directory/'含 空格的视频.mp4'
    try:binary=media.ffmpeg()
    except media.ClipifyError:pytest.skip('FFmpeg unavailable')
    process=subprocess.run([binary,'-v','error','-nostdin','-y','-f','lavfi','-i','testsrc=size=320x180:rate=20:duration=7',
        '-f','lavfi','-i','sine=frequency=300:sample_rate=16000:duration=7','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(path)],capture_output=True,timeout=30)
    assert process.returncode==0,process.stderr
    return path


@pytest.mark.parametrize('aspect',['source','16:9','9:16'])
def test_real_encode_decode_and_captions_all_aspects(video,tmp_path,aspect):
    folder=tmp_path/'独立 任务';folder.mkdir()
    transcript={'segments':rows()};media.atomic_json(folder/'transcript.json',transcript)
    data=task();data.update(source=str(video),media=media.probe(video),version=1,clips=[])
    data['options']['aspect']=aspect
    result=c.render(folder,data,rows(),[{'start':0,'end':6,'title':'编码测试'}])
    assert len(result)==1 and result[0]['verified']
    assert result[0]['height']>result[0]['width'] if aspect=='9:16' else result[0]['width']>result[0]['height']
    assert abs(float(Fraction(result[0]['fps']))-20)<.01
    final=folder/result[0]['file'];mtime=final.stat().st_mtime_ns
    assert c.render(folder,data,rows(),[{'start':0,'end':6,'title':'编码测试'}])[0]['sha256']==result[0]['sha256']
    assert final.stat().st_mtime_ns==mtime,'verified render should be reused'


def test_source_change_refuses_cached_transcript_before_model_runs(video,tmp_path,monkeypatch):
    fake_model=tmp_path/'model';fake_model.mkdir();(fake_model/'model.bin').write_bytes(b'model')
    folder=c.create(tmp_path/'outputs',str(video),model=str(fake_model),count=1,minimum=5)
    state=c.load(folder);state['fingerprint']={'sha256':'not this source'};media.atomic_json(folder/'manifest.json',state)
    monkeypatch.setattr(c,'preflight',lambda *a:{})
    result=c.run(folder)
    assert result['state']=='failed' and '源文件已经变化' in result['error']


def test_changed_transcript_cannot_reuse_old_selection_cache(tmp_path):
    media.atomic_json(tmp_path/'transcript.json',{'segments':rows()})
    with pytest.raises(media.ClipifyError,match='转录文件已经变化'):
        c.transcribe(tmp_path,{'media':{'duration':7},'transcript_sha256':'old hash'})


def test_duplicate_evidence_ids_rejected():
    data=rows()+[{'id':'s000000','start':6.,'end':7.,'text':'第二段'}]
    with pytest.raises(media.ClipifyError,match='ID'):
        captions.validate_transcript({'segments':data},7)


def test_no_speech_never_produces_empty_caption_movie(video,tmp_path,monkeypatch):
    model=tmp_path/'model';model.mkdir();(model/'model.bin').write_bytes(b'model')
    folder=c.create(tmp_path/'outputs',str(video),model=str(model),count=1,minimum=5)
    monkeypatch.setattr(c,'preflight',lambda *a:{})
    def no_speech(folder,task):
        result={'segments':[]};media.atomic_json(folder/'transcript.json',result);return result
    monkeypatch.setattr(c,'transcribe',no_speech)
    result=c.run(folder)
    assert result['state']=='no_speech' and not result['clips']
    assert not list(folder.rglob('video.mp4'))


def test_variable_frame_timestamps_survive_render(video,tmp_path):
    import av
    varying=tmp_path/'variable.mp4'
    result=subprocess.run([media.ffmpeg(),'-v','error','-nostdin','-y','-i',str(video),
        '-vf',"select='if(lt(t,2),not(mod(n,2)),not(mod(n,3)))'",'-fps_mode','passthrough',
        '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(varying)],capture_output=True,timeout=30)
    assert result.returncode==0,result.stderr
    folder=tmp_path/'vfr-task';folder.mkdir()
    media.atomic_json(folder/'transcript.json',{'segments':rows()})
    data=task();data.update(source=str(varying),media=media.probe(varying),version=1,clips=[])
    clips=c.render(folder,data,rows(),[{'start':0,'end':6,'title':'可变时间戳测试'}])
    with av.open(str(folder/clips[0]['file'])) as container:
        times=[float(frame.pts*frame.time_base) for frame in container.decode(video=0)]
    deltas={round(b-a,3) for a,b in zip(times,times[1:])}
    assert len(deltas)>1,'output must preserve variable timing instead of forcing constant FPS'
    assert all(b>a for a,b in zip(times,times[1:]))


from fractions import Fraction


@pytest.mark.parametrize('style',['minimal','opus','karaoke'])
def test_traditional_cues_and_words_are_delivered_as_simplified(tmp_path,style):
    cues=[{'start':0.,'end':2.,'text':'學習電腦軟體與AI，臺灣課程。'}]
    words=[{'start':0.,'end':1.9,'word':cues[0]['text']}]
    before=copy.deepcopy(cues)
    result=captions.write_captions(cues,tmp_path,2560,1440,style=style,words=words)
    for filename in ['captions.srt','captions.ass']:
        text=(tmp_path/filename).read_text(encoding='utf-8')
        assert '学习电脑软体与AI，台湾课程。' in text
        assert not any(char in text for char in '學習電腦軟體臺灣課')
    assert result['language']=='zh-Hans'
    assert cues==before


def test_cached_traditional_transcript_grouping_preserves_word_timing():
    words=[{'start':0.,'end':.9,'word':'學習'},{'start':1.,'end':1.9,'word':'課程。'}]
    original=copy.deepcopy(words)
    cues=captions.cues_for_clip([{'start':0.,'end':2.,'text':'學習課程。','words':words}],0,2)
    assert cues==[{'start':0.,'end':2.,'text':'学习课程。'}]
    assert words==original
    assert captions.cues_for_clip([{'start':0.,'end':2.,'text':'學習課程。'}],0,2)[0]['text']=='学习课程。'
    assert captions.simplified('AI Agent 123，学习课程。')=='AI Agent 123，学习课程。'
