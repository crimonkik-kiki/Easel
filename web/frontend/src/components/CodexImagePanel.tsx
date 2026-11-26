import {useEffect, useState} from 'react';
import {fetchCodexImageStatus, saveImageProvider, startCodexImage, fetchCodexImageJob} from '../lib/api';
import type {CodexImageStatus, CodexImageJob} from '../lib/api';

const JOB_KEY = 'easel.codexImageJob';

export default function CodexImagePanel() {
  const [status, setStatus] = useState<CodexImageStatus | null>(null);
  const [checking, setChecking] = useState(false);
  const [saving, setSaving] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState('');
  const [prompt, setPrompt] = useState('');
  const [topic, setTopic] = useState('');
  const [size, setSize] = useState('1024x1024');
  const [count, setCount] = useState(1);
  const [jobId, setJobId] = useState(() => sessionStorage.getItem(JOB_KEY) || '');
  const [job, setJob] = useState<CodexImageJob | null>(() => {
    const id = sessionStorage.getItem(JOB_KEY);
    return id ? {id, state: 'running', line: '正在恢复任务进度…', error: '', images: []} : null;
  });
  const busy = starting || job?.state === 'running';

  async function refresh() {
    setChecking(true); setError('');
    try { setStatus(await fetchCodexImageStatus()); }
    catch (e) { setError(e instanceof Error ? e.message : '连接检测失败'); }
    finally { setChecking(false); }
  }
  useEffect(() => { void refresh(); }, []);

  useEffect(() => {
    if (!jobId) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const latest = await fetchCodexImageJob(jobId);
        if (!active) return;
        setJob(latest); setError('');
        if (latest.state === 'running') timer = setTimeout(() => void poll(), 2000);
        else sessionStorage.removeItem(JOB_KEY);
      } catch (e) {
        if (!active) return;
        const message = e instanceof Error ? e.message : '进度获取失败';
        setError(message);
        if (message.includes('不存在') || message.includes('重启')) {
          sessionStorage.removeItem(JOB_KEY);
          setJob(previous => previous ? {...previous, state: 'fail', error: message} : null);
        } else timer = setTimeout(() => void poll(), 4000);
      }
    }
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [jobId]);

  async function choose(provider: 'codex' | 'api') {
    setSaving(true); setError('');
    try {
      const result = await saveImageProvider(provider);
      setStatus(previous => previous ? {...previous, provider: result.provider} : previous);
    } catch (e) { setError(e instanceof Error ? e.message : '切换失败'); }
    finally { setSaving(false); }
  }

  async function generate() {
    setStarting(true); setError('');
    try {
      const result = await startCodexImage(prompt, topic.trim() || 'Codex生图', size, count);
      setJob(result); setJobId(result.id); sessionStorage.setItem(JOB_KEY, result.id);
    } catch (e) { setError(e instanceof Error ? e.message : '提交失败'); }
    finally { setStarting(false); }
  }

  return <section style={{border: '1px solid var(--border, #8a8a8a55)', borderRadius: 12, padding: 18, marginBottom: 20}}>
    <div className="panel-top" style={{gap: 12, flexWrap: 'wrap'}}>
      <strong>生图提供方</strong>
      <select aria-label="生图提供方" value={status?.provider || 'api'} disabled={!status || saving || busy}
        onChange={e => void choose(e.target.value as 'codex' | 'api')}>
        <option value="codex">Codex 原生生图 · 沿用本机登录</option>
        <option value="api">独立图片 API</option>
      </select>
      <button className="btn btn-sm" onClick={() => void refresh()} disabled={checking}>{checking ? '检测中…' : '检测 Codex 连接'}</button>
    </div>
    <p className="foot-note" role="status">{status?.message || '正在检测本机 Codex…'}{saving ? ' · 保存中…' : ''}</p>
    {status?.provider === 'codex' && <>
      <p className="foot-note">不需要图片 API Key，使用 Codex 账号生图额度。提供方选择即时保存；不会自动转用收费 API。图片自动归档到内容库。</p>
      <label style={{display: 'block', margin: '12px 0'}}>内容主题
        <input aria-label="图片内容主题" value={topic} maxLength={60} onChange={e => setTopic(e.target.value)}
          placeholder="例如：秋日读书会封面" style={{display: 'block', width: '100%', marginTop: 6}} />
      </label>
      <label style={{display: 'block', margin: '12px 0'}}>图片需求
        <textarea aria-label="图片需求" value={prompt} maxLength={8000} rows={5} onChange={e => setPrompt(e.target.value)}
          placeholder="描述主体、风格、构图、颜色，以及需要出现的准确文字。" style={{display: 'block', width: '100%', marginTop: 6}} />
      </label>
      <div style={{display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap'}}>
        <label>目标画幅 <select aria-label="生图画幅" value={size} onChange={e => setSize(e.target.value)}>
          <option value="1024x1024">正方形</option><option value="1536x1024">横图 3:2</option>
          <option value="1024x1536">竖图 2:3</option><option value="16:9">横屏 16:9</option><option value="9:16">竖屏 9:16</option>
        </select></label>
        <label>数量 <select aria-label="生图数量" value={count} onChange={e => setCount(Number(e.target.value))}>
          {[1, 2, 3, 4].map(n => <option key={n} value={n}>{n} 张</option>)}
        </select></label>
        <button className="btn btn-primary" disabled={busy || !status.ready || !prompt.trim()} onClick={() => void generate()}>
          {busy ? '生成中…' : '使用 Codex 生成图片'}
        </button>
      </div>
      <p className="foot-note">画幅是生成要求，实际像素尺寸以结果为准。无需保持此面板打开，已生成的图片可在内容库查看。</p>
    </>}
    {job && <p role="status" className="foot-note">{job.state === 'fail' ? job.error : job.line}</p>}
    {error && <div className="env-error" role="alert">{error}</div>}
    {!!job?.images.length && <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16, marginTop: 16}}>
      {job.images.map(image => <figure key={image.path} style={{margin: 0}}>
        <a href={image.url} target="_blank" rel="noreferrer"><img src={image.url} alt="Codex 生成的图片" style={{width: '100%', maxHeight: 360, objectFit: 'contain', borderRadius: 8}} /></a>
        <figcaption className="foot-note">{image.width && image.height ? `${image.width} × ${image.height} · ` : ''}{image.path}</figcaption>
      </figure>)}
    </div>}
  </section>;
}
