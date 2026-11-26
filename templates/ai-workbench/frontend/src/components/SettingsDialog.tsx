import {useEffect, useRef, useState} from 'react';
import type {Bootstrap, Settings} from '../api';
import {IconGear} from './settingsIcons';
import {IconText} from './icons';

const labels: Record<string, string> = {chat: '对话与脚本', transcription: '语音转写', speech: '语音合成', image: '图片生成', video: '视频', music: '音乐'};
const order = ['chat', 'transcription', 'speech', 'image', 'video', 'music'];
interface Props {
  boot: Bootstrap | null; settings: Settings; busy: boolean; activeJobs: boolean; error: string; notice: string;
  models: {id: string; label: string}[]; runtimeCheck: string;
  onChange: (settings: Settings) => void; onClose: () => void; onSave: () => void;
  onCheck: () => void; onModels: (runtime: string) => void;
}
export default function SettingsDialog(p: Props) {
  const [section, setSection] = useState('model');
  const [tab, setTab] = useState('chat');
  const ref = useRef<HTMLDivElement>(null);
  const close = useRef(p.onClose); close.current = p.onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const dialog = ref.current!;
    dialog.focus();
    const keydown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {e.preventDefault(); close.current();}
      if (e.key !== 'Tab') return;
      const items = Array.from(dialog.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href]')).filter(el => el.offsetParent !== null);
      const first = items[0], last = items.at(-1);
      if (!first || !last) {e.preventDefault(); return;}
      if (e.shiftKey && (document.activeElement === first || document.activeElement === dialog)) {e.preventDefault(); last.focus();}
      else if (!e.shiftKey && (document.activeElement === last || document.activeElement === dialog)) {e.preventDefault(); first.focus();}
    };
    document.addEventListener('keydown', keydown);
    return () => {document.removeEventListener('keydown', keydown); previous?.focus();};
  }, []);
  const settings = p.settings;
  const channel = settings.channels[tab];
  const update = (key: string, value: string | boolean) => p.onChange({...settings, channels: {...settings.channels, [tab]: {...channel, [key]: value}}});
  return <div className="settings-overlay" onMouseDown={e => {if (e.target === e.currentTarget) p.onClose();}}>
    <div className="settings-panel" ref={ref} role="dialog" aria-modal="true" aria-labelledby="settings-title" tabIndex={-1}>
      <header className="settings-head"><div><h2 className="settings-title" id="settings-title">设置</h2><p className="settings-sub">模型配置 · 执行引擎 · 更多设置</p></div><div className="settings-actions"><button className="btn btn-sm btn-primary" disabled={p.busy || p.activeJobs} onClick={p.onSave}>保存 AI 配置</button><button className="settings-close" aria-label="关闭设置" onClick={p.onClose}>×</button></div></header>
      {!p.boot?.capabilities.chat.ready && <div className="settings-config-alert">还没有配置模型 — 选择执行引擎或填写模型 API，保存后即可开始工作。</div>}
      {p.error && <div className="error settings-feedback" role="alert">{p.error}</div>}{p.notice && <div className="notice settings-feedback" role="status">{p.notice}</div>}
      <div className="settings-body"><nav className="settings-nav" aria-label="设置分类"><button className={'snav ' + (section === 'model' ? 'active' : '')} onClick={() => setSection('model')}><IconGear size={16}/>模型配置<small>六个通道</small></button><button className={'snav ' + (section === 'more' ? 'active' : '')} onClick={() => setSection('more')}><IconText size={16}/>更多设置</button></nav>
        <div className="settings-main">
          {section === 'model' && <><div className="tabbar" role="tablist" aria-label="模型通道">{order.map(id => <button key={id} role="tab" aria-selected={id === tab} className={'tab ' + (tab === id ? 'active' : '')} onClick={() => setTab(id)}><span className="cdot"/>{labels[id]}</button>)}</div>
            <section className="st-panel" role="tabpanel" aria-label={labels[tab]}>
              {tab === 'chat' && <><div className="panel-top"><h3>Agent 底座</h3><span className="desc">选择仅聊天，或使用 Agent 执行工具</span></div>
                <div className="setting-row"><label htmlFor="runtime">执行引擎</label><div><select id="runtime" disabled={p.busy} aria-label="执行引擎" value={settings.runtime} onChange={e => p.onChange({...settings, runtime: e.target.value})}>{p.boot?.runtimes.map(r => <option key={r.id} value={r.id}>{r.label}{!r.available ? '（未配置或未检测到）' : ''}</option>)}</select><p className="setting-help">原生 Agent 使用各自认证；额外权限逐次确认。WorkBuddy 需要开放平台授权，桌面登录本身不等于已接通。</p></div></div>
                {settings.runtime !== 'api' && <><div className="setting-row"><span>连接检测</span><div className="row"><button disabled={p.busy} onClick={p.onCheck}>检测所选引擎</button><span role="status" className="muted">{p.runtimeCheck}</span></div></div><div className="setting-row"><label htmlFor="native-model">模型覆盖</label><div className="row"><input id="native-model" aria-label="原生模型覆盖" placeholder="留空使用原生默认模型" list="native-models" disabled={settings.runtime === 'workbuddy'} value={settings.models[settings.runtime] || ''} onChange={e => p.onChange({...settings, models: {...settings.models, [settings.runtime]: e.target.value}})}/>{['codex', 'opencode'].includes(settings.runtime) && <button disabled={p.busy} onClick={() => p.onModels(settings.runtime)}>读取可用模型</button>}<datalist id="native-models">{p.models.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}</datalist></div></div></>}
                <div className="setting-row"><label htmlFor="sandbox">工具权限</label><div><select id="sandbox" aria-label="工具权限" value={settings.sandbox} onChange={e => p.onChange({...settings, sandbox: e.target.value})}><option value="read-only">只读</option><option value="workspace-write">工作区写入</option></select><p className="setting-help">需要生成文件时选择工作区写入；额外授权仍由你确认。</p></div></div>
                <label className="assistant-instructions">助手指令<textarea aria-label="助手指令" rows={3} value={settings.system_prompt} onChange={e => p.onChange({...settings, system_prompt: e.target.value})}/></label>
              </>}
              {(tab !== 'chat' || settings.runtime === 'api') && <div className="channel-settings"><div className="panel-top"><h3>{labels[tab]} API</h3><span className="desc">独立配置模型与服务地址</span></div>
                {['video', 'music'].includes(tab) && <p className="notice">此通道需要注册供应商适配器，填写地址不会自动获得生成能力。</p>}
                {tab === 'image' && <label>图片供应商<select aria-label="图片供应商" value={channel.provider} onChange={e => update('provider', e.target.value)}><option value="api">图片 API</option><option value="codex">Codex 原生生图</option></select></label>}
                {(['base_url', 'model', 'key'] as const).map(key => <div className="setting-row" key={key}><label htmlFor={'channel-' + key}>{key === 'base_url' ? '服务地址' : key === 'model' ? '模型' : 'API Key'}</label><div><input id={'channel-' + key} aria-label={`${labels[tab]} ${key}`} list={tab === 'chat' && key === 'model' ? 'api-models' : undefined} type={key === 'key' ? 'password' : 'text'} autoComplete="off" value={channel[key] || ''} placeholder={key === 'key' && channel.key_configured ? '已保存；留空保留' : ''} onChange={e => update(key, e.target.value)}/></div></div>)}
                {tab === 'chat' && <div className="row"><button disabled={p.busy} onClick={() => p.onModels('api')}>读取 API 模型</button><datalist id="api-models">{p.models.map(m => <option key={m.id} value={m.id}/>)}</datalist></div>}
                {tab === 'image' && channel.provider === 'api' && <label>图片响应格式<select aria-label="图片响应格式" value={channel.response_format || 'auto'} onChange={e => update('response_format', e.target.value)}><option value="auto">自动（沿用服务默认）</option><option value="b64_json">Base64 图片</option><option value="url">图片下载地址</option></select></label>}
                {tab === 'speech' && <label>语音音色<input aria-label="语音音色" value={channel.voice || 'alloy'} onChange={e => update('voice', e.target.value)}/></label>}
                {channel.key_configured && <label className="inline"><input type="checkbox" checked={!!channel.clear_key} onChange={e => update('clear_key', e.target.checked)}/>清除已保存的 Key</label>}
              </div>}
            </section>
          </>}
          {section === 'more' && <section className="st-sec"><h3>工作台信息</h3><p className="page-subtitle">{p.boot?.brand.name} · {p.boot?.brand.subtitle}</p><div className="setting-row"><span>品牌与导航</span><p className="setting-help">在工程的 workbench.json 中配置名称、Logo、欢迎文案、导航和业务模块。修改后重启工作台生效。</p></div><div className="setting-row"><span>数据与文件</span><p className="setting-help">配置、会话和任务保存在当前工程的 outputs 目录。内容库只展示生成文件。</p></div></section>}
        </div>
      </div><footer className="settings-foot">原生 Agent 认证由其 CLI 管理；媒体通道单独配置。保存设置不会替你批准工具权限。</footer>
    </div>
  </div>;
}
