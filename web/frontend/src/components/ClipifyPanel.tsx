import {useCallback, useEffect, useRef, useState} from 'react';
import {controlClipifyTask, fetchClipifyCheck, fetchClipifyTask, fetchClipifyTasks, mediaUrl,
  uploadClipifyVideo, setClipifySelection, startClipifyTask, fetchClipifyCaptions, reviseClipifyCaptions} from '../lib/api';
import type {ClipifyAspect, ClipifyTask, ClipifyCue} from '../lib/api';
import '../styles/clipify.css';

const ACTIVE = new Set(['starting', 'checking', 'transcribing', 'selecting', 'rendering', 'verifying']);
const ASPECTS = [{value: 'source', label: '保持原比例'}, {value: '16:9', label: '横屏 16:9'},
  {value: '9:16', label: '竖屏 9:16'}] as const;
function stored(key: string, fallback: string) {
  try {return localStorage.getItem(key) || fallback;} catch {return fallback;}
}
function remember(key: string, value: string) {
  try {localStorage.setItem(key, value);} catch { /* private mode still allows a task */ }
}

export default function ClipifyPanel({onComplete}: {onComplete?: () => void}) {
  const [source, setSource] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadedName, setUploadedName] = useState('');
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const uploadController = useRef<AbortController | null>(null);
  useEffect(() => () => {const controller = uploadController.current; uploadController.current = null; controller?.abort();}, []);
  const [aspect, setAspect] = useState<ClipifyAspect>(() => {
    const value = stored('clipify.aspect', 'source');
    return value === '16:9' || value === '9:16' ? value : 'source';
  });
  const [count, setCount] = useState(3);
  const [minimum, setMinimum] = useState(20);
  const [maximum, setMaximum] = useState(60);
  const [id, setId] = useState(() => stored('clipify.job', ''));
  const [task, setTask] = useState<ClipifyTask | null>(null);
  const [history, setHistory] = useState<ClipifyTask[]>([]);
  const [error, setError] = useState('');
  const [environment, setEnvironment] = useState('正在检查本地转录环境…');
  const [ready, setReady] = useState(false);
  const [sending, setSending] = useState(false);
  const [pollRevision, setPollRevision] = useState(0);
  const [selection, setSelection] = useState('');
  const [editing, setEditing] = useState<number | null>(null);
  const [cues, setCues] = useState<ClipifyCue[]>([]);
  const completed = useRef('');
  const busy = uploading || sending || !!task && ACTIVE.has(task.state);
  const generation = useRef(0);
  const receive = useCallback((latest: ClipifyTask) => {
    setTask(latest);
    setHistory(previous => [latest, ...previous.filter(row => row.id !== latest.id)].slice(0, 30));
    if (latest.state === 'completed' && completed.current !== latest.id) {
      completed.current = latest.id; onComplete?.();
    }
  }, [onComplete]);

  useEffect(() => {
    let alive = true;
    fetchClipifyCheck().then(result => {
      if (!alive) return;
      setReady(result.ready);
      setEnvironment(result.ready ? '本地语音转录 · 当前 AI 底座选段 · 清晰中文字幕' : result.error || '环境未就绪');
    }).catch(e => {if (alive) setEnvironment(String(e));});
    fetchClipifyTasks().then(rows => {if (alive) setHistory(rows);}).catch(() => {});
    return () => {alive = false;};
  }, []);

  useEffect(() => {
    if (!id) return;
    const seq = ++generation.current;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const latest = await fetchClipifyTask(id);
        if (stopped || seq !== generation.current) return;
        receive(latest); setError('');
        if (ACTIVE.has(latest.state)) timer = setTimeout(() => void poll(), 1500);
      } catch (e) {
        if (stopped || seq !== generation.current) return;
        setError(e instanceof Error ? e.message : '进度读取失败');
        timer = setTimeout(() => void poll(), 4000);
      }
    }
    void poll();
    return () => {stopped = true; clearTimeout(timer);};
  }, [id, receive, pollRevision]);

  async function uploadFiles(files: File[]) {
    setDragging(false);
    if (busy || uploadController.current) return;
    if (files.length !== 1) {setError('请一次选择一个视频素材'); return;}
    const file = files[0];
    if (!/\.(mp4|mkv|mov|webm|avi|m4v)$/i.test(file.name)) {setError('请选择支持的视频文件'); return;}
    if (!file.size || file.size > 20 * 1024 ** 3) {setError('请选择非空且不超过 20GB 的视频；大文件可直接填写本地路径'); return;}
    const controller = new AbortController(); uploadController.current = controller;
    setUploading(true); setUploadProgress(0); setError('');
    try {
      const uploaded = await uploadClipifyVideo(file, setUploadProgress, controller.signal);
      if (uploadController.current !== controller) return;
      setSource(uploaded.source); setUploadedName(uploaded.name);
    } catch (error) {
      if (uploadController.current === controller) setError(error instanceof Error ? error.message : '视频上传失败');
    } finally {
      if (uploadController.current === controller) {uploadController.current = null; setUploading(false);}
    }
  }

  async function action(command: 'start' | 'cancel' | 'resume' | 'selection') {
    setSending(true); setError('');
    try {
      let latest: ClipifyTask;
      if (command === 'start') {
        if (!Number.isFinite(minimum) || !Number.isFinite(maximum) || minimum > maximum) throw new Error('请检查片段时长范围');
        latest = await startClipifyTask({source, aspect, count, minimum, maximum});
        remember('clipify.aspect', aspect);
      } else if (command === 'selection') {
        const parsed: unknown = JSON.parse(selection);
        if (!Array.isArray(parsed)) throw new Error('请填写片段数组');
        await setClipifySelection(id, parsed);
        latest = await controlClipifyTask(id, 'resume');
      } else latest = await controlClipifyTask(id, command);
      setEditing(null); receive(latest); setId(latest.id); remember('clipify.job', latest.id);
      // Resuming an existing id must restart polling after a terminal state.
      if (command !== 'start') {
        setPollRevision(value => value + 1);
      }
    } catch (e) {setError(e instanceof Error ? e.message : '操作失败');}
    finally {setSending(false);}
  }

  async function edit(index: number) {
    setSending(true); setError('');
    try {setCues(await fetchClipifyCaptions(id, index)); setEditing(index);}
    catch (e) {setError(e instanceof Error ? e.message : '字幕读取失败');}
    finally {setSending(false);}
  }
  async function saveCaptions() {
    if (editing === null) return;
    setSending(true); setError('');
    try {
      const latest = await reviseClipifyCaptions(id, editing, cues);
      receive(latest); setId(latest.id); remember('clipify.job', latest.id); setEditing(null);
    } catch (e) {setError(e instanceof Error ? e.message : '字幕修订失败');}
    finally {setSending(false);}
  }

  return <section className="clipify-panel" aria-label="中文直播切片">
    <h2 style={{fontSize: 17, margin: '0 0 6px'}}>中文直播切片</h2>
    <p className="foot-note">{environment}</p>
    <div className={`clipify-dropzone${dragging ? ' dragging' : ''}${busy ? ' disabled' : ''}`}
      role="region" aria-label="视频素材上传区" aria-busy={uploading}
      onDragOver={event => {event.preventDefault(); if (!busy) setDragging(true);}}
      onDragLeave={event => {if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false);}}
      onDrop={event => {event.preventDefault(); void uploadFiles(Array.from(event.dataTransfer.files));}}>
      <input ref={fileInput} type="file" hidden aria-label="选择视频素材" accept=".mp4,.mkv,.mov,.webm,.avi,.m4v"
        disabled={busy} onChange={event => {void uploadFiles(Array.from(event.target.files || [])); event.target.value = '';}} />
      <strong>{uploading ? (uploadProgress === 100 ? '上传完成，正在校验素材…' : `正在上传 ${uploadProgress}%`) : '将视频拖到这里'}</strong>
      <p className="foot-note">MP4 / MKV / MOV / WebM / AVI / M4V · 单个文件最大 20GB</p>
      {uploading ? <><progress aria-label="视频上传进度" value={uploadProgress} max={100} />
        <button className="btn btn-sm" onClick={() => uploadController.current?.abort()}>取消上传</button></> :
        <button className="btn btn-sm" disabled={busy} onClick={() => fileInput.current?.click()}>选择视频</button>}
      {uploadedName && <p className="foot-note" role="status">已选择：{uploadedName}，可设置参数后开始切片。</p>}
    </div>
    <label style={{display: 'block', margin: '14px 0'}}>本地视频路径
      <input className="field" aria-label="本地视频路径" value={source} onChange={e => {setSource(e.target.value); setUploadedName('');}} disabled={busy}
        placeholder={'例如 D:\\素材\\课程录屏.mp4'} style={{display: 'block', width: '100%', marginTop: 6}} />
    </label>
    <div className="clipify-controls">
      <label>输出画幅 <select className="field" aria-label="切片输出画幅" value={aspect}
        onChange={e => {setAspect(e.target.value as ClipifyAspect); remember('clipify.aspect', e.target.value);}}>
        {ASPECTS.map(a => <option key={a.value} value={a.value}>{a.label}</option>)}
      </select></label>
      <label>数量 <select className="field" aria-label="切片数量" value={count} onChange={e => setCount(Number(e.target.value))}>
        {[1, 2, 3, 4, 5].map(n => <option key={n} value={n}>{n} 条</option>)}
      </select></label>
      <label>最短秒数 <input className="field" aria-label="最短秒数" type="number" min={5} max={180} value={minimum}
        onChange={e => setMinimum(Number(e.target.value))} style={{width: 80}} /></label>
      <label>最长秒数 <input className="field" aria-label="最长秒数" type="number" min={5} max={180} value={maximum}
        onChange={e => setMaximum(Number(e.target.value))} style={{width: 80}} /></label>
      <button className="btn btn-primary" onClick={() => void action('start')} disabled={busy || !ready || !source.trim()}>
        {busy ? '处理中…' : '生成带字幕短片'}
      </button>
    </div>
    <p className="foot-note">横竖屏转换保留完整画面并填充背景。原视频只读；成片自动存入内容库。修改设置用于下次任务。</p>
    {!!history.length && <label>任务记录 <select className="field" aria-label="切片任务记录" value={id} disabled={sending}
      onChange={e => {setTask(null); setEditing(null); setId(e.target.value); remember('clipify.job', e.target.value);}}>
      <option value="">选择已保存任务</option>
      {!history.some(row => row.id === id) && id && <option value={id}>当前任务</option>}
      {history.map(row => <option key={row.id} value={row.id}>{row.source.split(/[\\/]/).pop()} · {row.options.aspect} · {row.message}</option>)}
    </select></label>}
    {task && <div style={{marginTop: 16}}>
      <p role="status">{task.cancel_requested ? '正在取消，等待资源释放…' : task.message}</p>
      {ACTIVE.has(task.state) && <progress aria-label="切片处理进度" value={task.progress || 0} max={100} style={{width: '100%'}} />}
      <p className="foot-note">本任务：{ASPECTS.find(a => a.value === task.options.aspect)?.label} · {task.options.count} 条 · {task.options.minimum}–{task.options.maximum} 秒</p>
      {task.error && <p role="alert" className="notice-error">{task.error}</p>}
      {ACTIVE.has(task.state) && <button className="btn btn-sm" disabled={sending || task.cancel_requested} onClick={() => void action('cancel')}>取消任务</button>}
      {(['failed', 'cancelled', 'interrupted', 'awaiting_selection'].includes(task.state) || task.can_resume) &&
        <button className="btn btn-sm" disabled={sending} onClick={() => void action('resume')}>恢复／重新选段</button>}
      {task.state === 'awaiting_selection' && <details style={{marginTop: 12}}>
        <summary>指定片段时间后继续</summary>
        <p className="foot-note">填写与任务数量一致的数组，时间单位为秒。例如：[{`{"start":190,"end":216,"title":"AI工具与智能体"}`} ]</p>
        <textarea className="field" aria-label="手动指定切片" rows={4} value={selection} onChange={e => setSelection(e.target.value)} style={{width: '100%'}} />
        <button className="btn btn-sm" disabled={sending || !selection.trim()} onClick={() => void action('selection')}>保存片段并生成</button>
      </details>}
      {!!task.clips.length && <div className="clipify-results">
        {task.clips.map((clip, index) => <figure key={clip.file} style={{margin: 0}}>
          <video controls preload="metadata" poster={clip.poster ? mediaUrl(`${task.id}/${clip.poster}`) : undefined}
            src={mediaUrl(`${task.id}/${clip.file}`)} className="clipify-preview" />
          <figcaption>{clip.title} · {clip.duration.toFixed(1)}秒</figcaption>
          <p className="foot-note">{clip.width}×{clip.height} · {clip.subtitle?.review || '自动字幕，未逐句听校'}</p>
          <a href={mediaUrl(`${task.id}/${clip.file}`)} target="_blank" rel="noreferrer">打开视频</a>{' · '}
          <a href={mediaUrl(`${task.id}/${clip.file.replace('video.mp4', 'captions.srt')}`)} download>下载字幕</a>
          {task.state === 'completed' && <button className="btn btn-sm" style={{marginLeft: 8}} disabled={busy} onClick={() => void edit(index + 1)}>校对字幕</button>}
        </figure>)}
      </div>}
      {editing !== null && <div style={{marginTop: 16}}>
        <h3 style={{fontSize: 15}}>校对第 {editing} 条字幕</h3>
        <p className="foot-note">保留时间轴，修改文字后生成新的修订版，原成片会保留。</p>
        {cues.map((cue, index) => <label key={index} style={{display: 'flex', gap: 10, margin: '8px 0', alignItems: 'center'}}>
          <span style={{minWidth: 88, fontSize: 12}}>{cue.start.toFixed(1)}–{cue.end.toFixed(1)}秒</span>
          <input className="field" aria-label={`字幕第${index + 1}句`} maxLength={40} value={cue.text} style={{width: '100%'}} onChange={e => setCues(previous => previous.map((value, i) => i === index ? {...value, text: e.target.value} : value))} />
        </label>)}
        <button className="btn btn-primary" disabled={sending || cues.some(cue => !cue.text.trim())} onClick={() => void saveCaptions()}>生成字幕修订版</button>{' '}
        <button className="btn btn-sm" disabled={sending} onClick={() => setEditing(null)}>收起</button>
      </div>}
    </div>}
    {error && <p role="alert" className="notice-error">{error}</p>}
  </section>;
}
