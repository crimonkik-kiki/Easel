import {useCallback, useEffect, useRef, useState} from 'react';
import DOMPurify from 'dompurify';
import {marked} from 'marked';
import {api, artifactUrl, previewUrl, terminal, upload} from './api';
import type {Artifact, Bootstrap, Job, Session, Settings} from './api';
import {DEFAULT_NAV, LOGO, navigation, PageHeader, WorkbenchSidebar} from './components/WorkbenchShell';
import Dashboard from './components/Dashboard';
import SettingsDialog from './components/SettingsDialog';
import {IconArrowUp, IconChat, IconFile, IconSkills, IconText} from './components/icons';

const names: Record<string, string> = {chat: '对话与脚本', image: '图片生成', transcription: '语音转写', speech: '语音合成', video: '视频', music: '音乐'};
const states: Record<string, string> = {queued: '排队中', running: '处理中', waiting: '等待确认', completed: '已完成', failed: '失败', cancelled: '已停止', interrupted: '待核对'};
const NAV = DEFAULT_NAV;
function Markdown({text}: {text: string}) {
  return <div className="markdown" dangerouslySetInnerHTML={{__html: DOMPurify.sanitize(marked.parse(text, {async: false}) as string)}} />;
}

function MediaPreview({path}: {path: string}) {
  if (/\.(png|jpe?g|webp|gif)$/i.test(path)) return <img src={previewUrl(path)} alt={path.split('/').pop()} loading="lazy"/>;
  if (/\.(mp3|wav|m4a)$/i.test(path)) return <audio src={previewUrl(path)} controls preload="metadata"/>;
  if (/\.(mp4|webm)$/i.test(path)) return <video src={previewUrl(path)} controls preload="metadata"/>;
  return null;
}

export default function App() {
  const [boot, setBoot] = useState<Bootstrap | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [page, setPage] = useState('home');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const chatEnd = useRef<HTMLDivElement>(null);
  const nav = navigation(boot);
  const openSettings = () => {if (!settings) return; setSettingsOpen(true); setError(''); setNotice('');};
  const navigate = (next: string) => {if (next === 'settings') {openSettings(); return;} setPage(next); setError(''); setNotice('');};
  const [sessions, setSessions] = useState<Session[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [active, setActive] = useState('');
  const [job, setJob] = useState<Job | null>(null);
  const [kind, setKind] = useState('image');
  const context = page === 'chat' ? `chat:${active || 'new'}` : page === 'media' ? `media:${kind}` : page;
  const [drafts, setDrafts] = useState<Record<string, {prompt?: string; skill?: string; attachment?: {id: string; name: string}}>>({});
  const prompt = drafts[context]?.prompt || '';
  const skill = drafts[context]?.skill || '';
  const attachment = drafts[context]?.attachment || {id: '', name: ''};
  const setPrompt = (value: string) => setDrafts(previous => ({...previous, [context]: {...previous[context], prompt: value}}));
  const setSkill = (value: string) => setDrafts(previous => ({...previous, [context]: {...previous[context], skill: value}}));
  const setAttachment = (value: {id: string; name: string}) => setDrafts(previous => ({...previous, [context]: {...previous[context], attachment: value}}));
  const [skillText, setSkillText] = useState('');
  const [skillId, setSkillId] = useState('');
  const [newSkillText, setNewSkillText] = useState('');
  const [catalog, setCatalog] = useState<{id: string; description: string; installed: boolean}[]>([]);
  const [catalogSearch, setCatalogSearch] = useState('');
  const [rename, setRename] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [moduleDrafts, setModuleDrafts] = useState<Record<string, Record<string, string>>>({});
  const values = moduleDrafts[page] || {};
  const setValues = (value: Record<string, string>) => setModuleDrafts(previous => ({...previous, [page]: value}));
  const [models, setModels] = useState<{id: string; label: string}[]>([]);
  const [runtimeCheck, setRuntimeCheck] = useState('');
  const [theme, setTheme] = useState(() => {try {return localStorage.getItem('ai-workbench.theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');} catch {return 'light';}});
  const current = sessions.find(s => s.id === active);
  const matchesContext = !!job && (page.startsWith('task:') ? page.slice(5) === job.id : page === 'chat' ? !!active && job.kind === 'chat' && job.session_id === active : page === 'media' ? job.kind === kind : page.startsWith('module:') ? job.module_id === page.slice(7) : false);
  const working = matchesContext && job && !terminal.has(job.state);
  const hasActiveJobs = jobs.some(row => !terminal.has(row.state));
  const capability = boot?.capabilities[page === 'media' ? kind : 'chat'];

  const reload = useCallback(async () => {
    const [sessionRows, jobRows, files] = await Promise.all([api<Session[]>('/api/sessions'), api<Job[]>('/api/jobs'), api<Artifact[]>('/api/artifacts')]);
    setSessions(sessionRows); setJobs(jobRows); setArtifacts(files);
    return {sessionRows, jobRows};
  }, []);
  useEffect(() => {
    let alive = true;
    Promise.all([api<Bootstrap>('/api/bootstrap'), reload()]).then(([initial, data]) => {
      if (!alive) return;
      setBoot(initial); setSettings(initial.settings); document.title = initial.brand.name;
      const favicon = document.querySelector<HTMLLinkElement>('link[rel="icon"]'); if (favicon && initial.brand.logo) favicon.href = initial.brand.logo;
      try {setDrafts(JSON.parse(localStorage.getItem(`${initial.brand.id}.drafts`) || '{}')); setModuleDrafts(JSON.parse(localStorage.getItem(`${initial.brand.id}.module-drafts`) || '{}'));} catch { /* retain an empty draft map */ }
      const previousPage = localStorage.getItem(`${initial.brand.id}.page`);
      if (previousPage && (NAV.some(item => item.id === previousPage) || initial.modules.some(m => previousPage === 'module:' + m.id) || data.jobRows.some(j => previousPage === 'task:' + j.id))) setPage(previousPage);
      const saved = localStorage.getItem(`${initial.brand.id}.session`) || '';
      const session = data.sessionRows.find(s => s.id === saved);
      if (session) {setActive(session.id); setJob(data.jobRows.find(j => j.session_id === session.id) || null);}
    }).catch(e => {if (alive) setError(e.message);});
    return () => {alive = false;};
  }, [reload]);
  useEffect(() => {
    if (!boot) return;
    try {localStorage.setItem(`${boot.brand.id}.drafts`, JSON.stringify(drafts)); localStorage.setItem(`${boot.brand.id}.page`, page); localStorage.setItem(`${boot.brand.id}.module-drafts`, JSON.stringify(moduleDrafts));} catch { /* storage full: keep the current draft in memory */ }
  }, [drafts, page, boot, moduleDrafts]);
  useEffect(() => {
    const candidate = page.startsWith('task:') ? jobs.find(j => j.id === page.slice(5)) : page === 'chat' ? (active ? jobs.find(j => j.kind === 'chat' && j.session_id === active) : undefined) : page === 'media' ? jobs.find(j => j.kind === kind) : page.startsWith('module:') ? jobs.find(j => j.module_id === page.slice(7)) : undefined;
    setJob(previous => previous?.id === candidate?.id ? previous : candidate || null);
  }, [page, active, kind, jobs]);
  useEffect(() => {setError(''); setNotice(''); setAnswers({});}, [context]);
  useEffect(() => {
    if (!hasActiveJobs) return;
    const timer = window.setInterval(() => {void reload().catch(e => setError(e.message));}, 2000);
    return () => window.clearInterval(timer);
  }, [hasActiveJobs, reload]);
  useEffect(() => {setAnswers({});}, [job?.question?.id]);
  useEffect(() => {setRuntimeCheck(''); setModels([]);}, [settings?.runtime]);
  useEffect(() => {
    if (page === 'skills') void api<typeof catalog>('/api/skill-catalog').then(setCatalog).catch(e => setError(e.message));
  }, [page, boot?.skills.length]);
  useEffect(() => {document.documentElement.dataset.theme = theme; try {localStorage.setItem('ai-workbench.theme', theme);} catch { /* theme still applies */ }}, [theme]);
  useEffect(() => {chatEnd.current?.scrollIntoView({block: 'end'});}, [current?.messages.length, job?.text, job?.question?.id]);
  useEffect(() => {if (!skillText) return; const close = (e: KeyboardEvent) => {if (e.key === 'Escape') setSkillText('');}; document.addEventListener('keydown', close); return () => document.removeEventListener('keydown', close);}, [skillText]);
  useEffect(() => {
    if (boot && active) localStorage.setItem(`${boot.brand.id}.session`, active);
  }, [active, boot]);
  useEffect(() => {
    if (!job || terminal.has(job.state)) return;
    const identifier = job.id;
    const stream = new EventSource(`/api/jobs/${identifier}/events`);
    let alive = true;
    let updating = false, dirty = false;
    const update = async () => {
      dirty = true;
      if (updating) return;
      updating = true;
      try {
        do {
          dirty = false;
          const next = await api<Job>(`/api/jobs/${identifier}`);
          if (!alive) return;
          setJob(next);
          if (terminal.has(next.state)) {stream.close(); void reload().catch(e => setError(e.message)); return;}
        } while (dirty && alive);
      } catch (e) {if (alive) setError(e instanceof Error ? e.message : '任务状态读取失败');}
      finally {updating = false;}
    };
    stream.onmessage = () => {void update();};
    stream.onerror = () => {void update();};
    return () => {alive = false; stream.close();};
    // Keep one connection per task; the server's Last-Event-ID supports replay.
  }, [job?.id, reload]);

  async function perform(action: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('');
    try {await action();} catch (e) {setError(e instanceof Error ? e.message : '操作失败');} finally {setBusy(false);}
  }
  async function newSession() {
    const session = await api<Session>('/api/sessions', 'POST');
    setActive(session.id); setJob(null); setAnswers({}); setPage('chat'); await reload(); return session;
  }
  async function submit() {
    let session = current;
    if (page === 'chat' && !session) {
      const draft = drafts[context]; session = await newSession();
      const target = `chat:${session.id}`;
      setDrafts(previous => ({...previous, [target]: draft || {}}));
    }
    const created = await api<Job>('/api/jobs', 'POST', {kind: page === 'chat' ? 'chat' : kind, prompt, session_id: page === 'chat' ? session?.id : '', skill: page === 'chat' ? skill : '', attachment: attachment.id});
    setJob(created); setDrafts(previous => ({...previous, [context]: {skill}, ...(session && page === 'chat' ? {[`chat:${session.id}`]: {skill}} : {})})); setAnswers({}); await reload();
  }
  function selectSession(session: Session) {
    setActive(session.id); setJob(jobs.find(j => j.session_id === session.id) || null); setPage('chat'); setAnswers({});
  }
  const jobView = job && matchesContext && <section className="job-result" aria-label="当前任务" data-job-id={job.id}>
    <div className="row"><span className={`badge ${job.state}`}>{states[job.state] || job.state}</span><span className="muted">{job.runtime} · {job.model || '原生默认模型'}</span>
      {!terminal.has(job.state) && <button onClick={() => void perform(async () => {await api(`/api/jobs/${job.id}/cancel`, 'POST');})}>停止任务</button>}</div>
    {job.text && !(page === 'chat' && current?.messages.some(m => m.role === 'assistant' && m.job === job.id)) && <Markdown text={job.text} />}
    {job.error && <p className="error">{job.error}</p>}
    {!!job.activities?.length && <details><summary>执行记录</summary>{job.activities.map((line, index) => <p className="muted" key={index}>{line}</p>)}</details>}
    {job.question && <div className="confirmation" aria-label="工具权限与问题确认"><h3>需要你的确认</h3>
      {job.question.items.map(q => <label key={q.questionId}>{q.question}{q.options?.length ?
        <select aria-label={q.question} value={answers[q.questionId] || ''} onChange={e => setAnswers({...answers, [q.questionId]: e.target.value})}><option value="">请选择</option>{q.options.map((o, i) => <option key={i}>{o.label}</option>)}</select> :
        <input aria-label={q.question} value={answers[q.questionId] || ''} onChange={e => setAnswers({...answers, [q.questionId]: e.target.value})}/>}</label>)}
      <button disabled={busy || job.question.items.some(q => !answers[q.questionId])} onClick={() => void perform(async () => {
        await api(`/api/jobs/${job.id}/answer`, 'POST', {question_id: job.question!.id, answers: Object.fromEntries(Object.entries(answers).map(([k, v]) => [k, [v]]))}); setAnswers({});
      })}>提交确认</button></div>}
    {job.artifacts.map(path => <div className="artifact-preview" key={path}><MediaPreview path={path}/><a href={artifactUrl(path)} download>下载 {path.split('/').pop()}</a></div>)}
  </section>;

  const showChatHero = page === 'chat' && !current?.messages.length && !job;
  const composer = <div className={'composer ' + (showChatHero ? 'composer-hero' : '')}>
    {!capability?.ready && <p className="notice">{capability?.reason || '正在检查通道配置'} <button className="text-button" onClick={openSettings}>前往 AI 设置</button></p>}
    <div className="composer-top"><span className="composer-mark" aria-hidden="true"><IconSkills size={24}/></span><textarea className="chat-input" disabled={busy} aria-label="任务内容" placeholder={kind === 'transcription' && page === 'media' ? '选择音频附件后开始转写' : '描述你想完成的工作，或选择一个技能开始…'} value={prompt} onChange={e => setPrompt(e.target.value)} rows={3} onKeyDown={e => {if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && page === 'chat') {e.preventDefault(); if (!busy && !working && capability?.ready && prompt.trim()) void perform(submit);}}}/></div>
    {attachment.id && <div className="attachment-chip"><IconText size={13}/><span>{attachment.name}</span><button aria-label="移除附件" onClick={() => setAttachment({id: '', name: ''})}>×</button></div>}
    <div className="composer-bar"><div className="composer-tools">{page === 'chat' && <select className="composer-skill" aria-label="使用技能" value={skill} onChange={e => setSkill(e.target.value)}><option value="">通用对话</option>{boot?.skills.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select>}
      <label className="composer-attach-btn file-picker"><span>＋ 附件</span><input type="file" aria-label="添加附件" disabled={busy} onChange={e => {const file = e.target.files?.[0]; if (file) void perform(async () => setAttachment(await upload(file))); e.target.value = '';}}/></label><span className="composer-hint">{page === 'chat' ? 'Enter 发送 · Shift+Enter 换行' : '附件最大 32MB'}</span></div>
      <button className="send-btn" aria-label="开始任务" title="开始任务" disabled={busy || !!working || !capability?.ready || (!prompt.trim() && !(page === 'media' && kind === 'transcription' && attachment.id))} onClick={() => void perform(submit)}><IconArrowUp size={19}/></button></div>
  </div>;
  const title = (page.startsWith('task:') ? '任务详情' : nav.find(n => n.id === page)?.label) || boot?.modules.find(m => 'module:' + m.id === page)?.name || DEFAULT_NAV.find(n => n.id === page)?.label || '工作台';
  const messages = <>{current?.messages.map((message, i) => <article className={'message message-row ' + message.role} key={i}><div className={'message-bubble ' + message.role}><Markdown text={message.content}/></div></article>)}{jobView}<div ref={chatEnd}/></>;
  const feedback = <>{error && <div role="alert" className="error">{error}</div>}{notice && <div role="status" className="notice">{notice}</div>}</>;
  return <>
    <div className="app-layout" inert={settingsOpen || !!skillText}>
      <WorkbenchSidebar boot={boot} page={page} sessions={sessions} active={active} busy={busy} theme={theme} runtime={settings?.runtime || 'api'} ready={!!boot?.capabilities.chat.ready} onTheme={() => setTheme(theme === 'dark' ? 'light' : 'dark')} onNavigate={navigate} onNewChat={() => void perform(async () => {await newSession();})} onSession={selectSession} onSettings={openSettings}/>
      <main className="main-content"><div className={'page-host ' + (page === 'chat' ? 'chat-page' : '')} data-page={page}>
        {page === 'chat' ? <>{!settingsOpen && feedback}
          {showChatHero ? <div className="chat-hero"><div className="chat-hero-brand"><img src={boot?.brand.logo || LOGO} alt=""/>{boot?.brand.name || 'Easel'}</div><h1 className="chat-hero-title">{boot?.brand.welcome_title || '今天，想一起完成什么？'}</h1><p className="chat-hero-sub">{boot?.brand.welcome_subtitle || '选择技能，开始工作。'}</p>{composer}<div className="suggestions">{[{title: '梳理一段内容', text: '提炼要点，让信息更清晰', prompt: '请帮我总结下面这段内容，提炼关键结论与行动项：', Icon: IconText}, {title: '把想法变成计划', text: '拆解目标，整理可执行步骤', prompt: '请帮我把这个想法整理成可执行的工作计划：', Icon: IconChat}].map(s => <button className="card card-hover suggestion-card" key={s.title} onClick={() => setPrompt(s.prompt)}><span className="suggestion-icon"><s.Icon size={19}/></span><span className="suggestion-body"><strong className="suggestion-title">{s.title}</strong><span className="suggestion-text">{s.text}</span></span></button>)}</div></div>
          : <>{current && <header className="conversation-toolbar"><input aria-label="对话名称" value={rename} placeholder={current.title} onChange={e => setRename(e.target.value)}/><button className="btn btn-sm" disabled={busy || !rename.trim()} onClick={() => void perform(async () => {await api(`/api/sessions/${current.id}`, 'PATCH', {title: rename}); setRename(''); await reload();})}>重命名</button><a className="btn btn-sm btn-ghost" href={`/api/sessions/${current.id}/export`} download>导出对话</a><span className="muted">{current.runtime}</span></header>}<div className="chat-messages"><div className="chat-thread">{messages}</div></div><div className="chat-input-area"><div className="chat-input-inner">{composer}</div></div></>}
        </> : <div className={'page-scroll template-page ' + (page === 'home' ? 'dash-page' : '')}>
          {page !== 'home' && <PageHeader title={title} busy={busy} onRefresh={() => void perform(async () => {await reload(); setNotice('已刷新');})}/>}
          {!settingsOpen && feedback}{!boot && <p className="muted">正在读取配置…</p>}
          {page === 'home' && <Dashboard boot={boot} sessions={sessions} jobs={jobs} artifacts={artifacts} onNavigate={navigate} onSession={selectSession} onNewChat={() => void perform(async () => {await newSession();})} onSettings={openSettings}/>}
          <div className="page-body">
      {page === 'skills' && <section><p className="muted">技能提供工作流程规范。API模式使用指令处理文本；本机工具由所选Agent提供。</p><div className="skill-grid">{boot?.skills.map(s => <div className="card skill-card" key={s.id}><div className="skill-card-icon"><IconSkills size={20}/></div><h3 className="skill-card-name">{s.name}</h3><p className="muted">{s.id}</p><div className="row"><button onClick={() => void perform(async () => {const r = await api<{text: string}>(`/api/skills/${s.id}`); setSkillText(r.text);})}>查看规范</button><button onClick={() => {setDrafts(previous => ({...previous, [`chat:${active || 'new'}`]: {...previous[`chat:${active || 'new'}`], skill: s.id}})); setPage('chat');}}>用于对话</button></div></div>)}</div><details className="panel card"><summary>新增或导入提示词技能</summary><label>技能标识<input aria-label="新技能标识" value={skillId} onChange={e => setSkillId(e.target.value)} placeholder="例如 meeting-summary"/></label><label>技能规范<textarea aria-label="新技能规范" rows={6} value={newSkillText} onChange={e => setNewSkillText(e.target.value)}/></label><label>导入 SKILL.md<input type="file" accept=".md" aria-label="导入技能文档" onChange={e => {const file = e.target.files?.[0]; if (file) void perform(async () => {if (file.size > 200000) throw new Error('技能文档过大'); setNewSkillText(await file.text());}); e.target.value = '';}}/></label><button disabled={busy || !skillId.trim() || !newSkillText.trim()} onClick={() => void perform(async () => {await api('/api/skills', 'POST', {id: skillId, text: newSkillText}); const next = await api<Bootstrap>('/api/bootstrap'); setBoot(next); setSkillId(''); setNewSkillText(''); setNotice('技能已保存，可以用于对话');})}>保存新技能</button><p className="muted">此入口保存提示词规范；含脚本或引用资料的完整技能目录请按扩展说明导入。</p></details>
        <details className="panel card"><summary>{catalog.length ? `Easel 技能目录（${catalog.length}）` : '正在读取技能目录…'}</summary><input aria-label="搜索技能目录" value={catalogSearch} onChange={e => setCatalogSearch(e.target.value)} placeholder="搜索名称或用途"/>{catalog.filter(row => (row.id + row.description).toLowerCase().includes(catalogSearch.toLowerCase())).map(row => <div className="job-row" key={row.id}><span><strong>{row.id}</strong><small>{row.description}</small></span><span>{row.installed ? '已装载' : '需导入完整目录'}</span></div>)}</details>
        </section>}
      {page === 'media' && <section><div className="tabs">{Object.entries(names).filter(([id]) => id !== 'chat').map(([id, label]) => <button className={kind === id ? 'active' : ''} key={id} onClick={() => setKind(id)}>{label}</button>)}</div>
        <p className="muted">当前通道：{settings?.channels[kind].provider} · {settings?.channels[kind].model || '尚未配置模型'}</p>
        {['video', 'music'].includes(kind) && <p className="notice">此通道需要接入对应供应商，配置与扩展方法见模板说明。</p>}{composer}{jobView}</section>}
      {page === 'jobs' && <section><p className="muted">任务持久化保存。重启中断的任务需核对结果后新建，不会自动重发。</p>{!jobs.length && <div className="empty">还没有任务记录</div>}{jobs.map(item => <button className="job-row" key={item.id} onClick={() => {setJob(item); setPage('task:' + item.id);}}><span>{item.prompt.slice(0, 70) || '语音转写'}</span><span className="muted">{item.kind} · {states[item.state]}</span></button>)}</section>}
      {page.startsWith('task:') && job && <section className="panel card"><h2>{job.prompt.slice(0, 100) || '语音转写'}</h2><p className="muted">任务ID：{job.id} · 类型：{job.kind}</p>{jobView}</section>}
      {page === 'artifacts' && <section><p className="muted">只展示AI生成的交付文件，不展示凭据、会话库或上传源文件。</p>{!artifacts.length && <div className="empty">生成的文件会出现在这里</div>}<div className="gallery-grid">{artifacts.map(file => <article className="card gcard" key={file.path}><div className="gcard-thumb">{/\.(png|jpe?g|webp|gif|mp4|webm|mp3|wav|m4a)$/i.test(file.path) ? <MediaPreview path={file.path}/> : <IconFile size={36}/>}</div><div className="gcard-info"><h3 className="gcard-title" title={file.name}>{file.name}</h3><p className="gcard-sub" title={file.path}>{Math.ceil(file.size / 1024)} KB · {file.path}</p><a className="btn btn-sm btn-ghost artifact-download" href={artifactUrl(file.path)} download>下载文件</a></div></article>)}</div></section>}
      {page.startsWith('module:') && boot?.modules.filter(m => page === 'module:' + m.id).map(module => <section className="panel" key={module.id}><p>{module.description}</p>{!boot?.capabilities.chat.ready && <p className="notice">{boot?.capabilities.chat.reason}</p>}{module.fields.map(field => <label key={field.id}>{field.label}{field.type === 'select' ? <select aria-label={field.label} value={values[field.id] || ''} onChange={e => setValues({...values, [field.id]: e.target.value})}><option value="">请选择</option>{field.options?.map(option => <option key={option}>{option}</option>)}</select> : field.type === 'text' || field.type === 'number' ? <input type={field.type} aria-label={field.label} placeholder={field.placeholder} value={values[field.id] || ''} onChange={e => setValues({...values, [field.id]: e.target.value})}/> : <textarea aria-label={field.label} placeholder={field.placeholder} rows={7} value={values[field.id] || ''} onChange={e => setValues({...values, [field.id]: e.target.value})}/>}</label>)}<button className="primary" disabled={busy || !!working || !boot?.capabilities.chat.ready} onClick={() => void perform(async () => {setJob(await api<Job>(`/api/modules/${module.id}/run`, 'POST', values)); await reload();})}>{module.action_label || '开始任务'}</button>{jobView}</section>)}
          </div>
        </div>}
      </div></main>
    </div>
    {settingsOpen && settings && <SettingsDialog boot={boot} settings={settings} busy={busy} activeJobs={hasActiveJobs} error={error} notice={notice} models={models} runtimeCheck={runtimeCheck} onChange={setSettings} onClose={() => setSettingsOpen(false)} onSave={() => void perform(async () => {const saved = await api<Settings>('/api/settings', 'PUT', settings); setSettings(saved); setBoot(await api<Bootstrap>('/api/bootstrap')); setNotice('AI 配置已保存');})} onCheck={() => void perform(async () => {const result = await api<{message: string}>(`/api/runtimes/${settings.runtime}/check`, 'POST'); setRuntimeCheck(result.message);})} onModels={runtime => void perform(async () => {setModels(await api(`/api/models/${runtime}`, 'POST')); if (runtime === 'api') setNotice('已读取可用模型，可在聊天模型输入框中选择');})}/>}
    {skillText && <div className="drawer-overlay" onMouseDown={e => {if (e.target === e.currentTarget) setSkillText('');}}><aside className="drawer" role="dialog" aria-modal="true" aria-label="技能规范"><header className="drawer-header row"><h2>技能规范</h2><button className="icon-btn push" aria-label="关闭技能规范" onClick={() => setSkillText('')}>×</button></header><div className="drawer-body"><Markdown text={skillText}/></div></aside></div>}
  </>;
}
