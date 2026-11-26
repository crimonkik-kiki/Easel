import type {ComponentType} from 'react';
import {IconChat, IconSkills, IconOutputs, IconNewChat, IconDashboard, IconImage, IconCalendar, IconText, IconRefresh} from './icons';
import {IconGear} from './settingsIcons';
import type {Bootstrap, Session} from '../api';

const icons: Record<string, ComponentType<{size?: number}>> = {dashboard: IconDashboard, chat: IconChat, skills: IconSkills, outputs: IconOutputs, image: IconImage, calendar: IconCalendar, text: IconText};
export const DEFAULT_NAV = [
  {id: 'home', label: '工作台', icon: 'dashboard'}, {id: 'chat', label: '对话', icon: 'chat'},
  {id: 'skills', label: '技能库', icon: 'skills'}, {id: 'media', label: 'AI 媒体', icon: 'image'},
  {id: 'jobs', label: '任务记录', icon: 'calendar'}, {id: 'artifacts', label: '内容库', icon: 'outputs'},
];
export const LOGO = '/brand/easel-icon-transparent.png';
export function navigation(boot: Bootstrap | null) {
  if (!boot?.navigation?.length) return DEFAULT_NAV;
  const allowed = new Set(DEFAULT_NAV.map(item => item.id));
  const used = new Set<string>();
  const rows = boot.navigation.filter(item => allowed.has(item.id) && !used.has(item.id) && used.add(item.id));
  return rows.length ? rows : DEFAULT_NAV;
}

export function ThemeToggle({theme, onToggle}: {theme: string; onToggle: () => void}) {
  const dark = theme === 'dark';
  return <button className="theme-toggle" aria-label="切换主题" title={dark ? '切换到日间模式' : '切换到夜间模式'} onClick={onToggle}>
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {dark ? <><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/></> : <path d="M20.9 13.1A9 9 0 0 1 10.9 3.1a9 9 0 1 0 10 10Z"/>}
    </svg>
  </button>;
}

interface Props {
  boot: Bootstrap | null; page: string; active: string; sessions: Session[]; busy: boolean;
  theme: string; runtime: string; ready: boolean; onTheme: () => void; onNavigate: (page: string) => void;
  onNewChat: () => void; onSession: (session: Session) => void; onSettings: () => void;
}
export function WorkbenchSidebar(p: Props) {
  const nav = navigation(p.boot);
  return <aside className="sidebar" aria-label="工作区侧栏">
    <div className="sidebar-header">
      <div className="sidebar-logo"><img className="sidebar-logo-icon" src={p.boot?.brand.logo || LOGO} alt=""/><h1 title={p.boot?.brand.name}>{p.boot?.brand.name || 'Easel'}</h1><ThemeToggle theme={p.theme} onToggle={p.onTheme}/></div>
      <select className="persona-select" aria-label="工作模式" value={p.page.startsWith('module:') ? p.page : ''} onChange={e => p.onNavigate(e.target.value || 'home')}>
        <option value="">通用模式</option>{p.boot?.modules.map(m => <option key={m.id} value={'module:' + m.id}>{m.name}</option>)}
      </select>
    </div>
    <nav className="sidebar-navigation" aria-label="主导航">
      <div className="sidebar-nav">{nav.map(item => {const Icon = icons[item.icon] || IconText; return <button key={item.id} className={'nav-item ' + (p.page === item.id ? 'active' : '')} aria-label={item.label} aria-current={p.page === item.id ? 'page' : undefined} onClick={() => p.onNavigate(item.id)}><span className="nav-icon"><Icon size={18}/></span><span className="nav-label">{item.label}</span></button>;})}
        {p.boot?.modules.map(m => <button key={m.id} className={'nav-item ' + (p.page === 'module:' + m.id ? 'active' : '')} aria-label={m.name} onClick={() => p.onNavigate('module:' + m.id)}><span className="nav-icon"><IconText size={18}/></span><span className="nav-label">{m.name}</span></button>)}
      </div>
      <div className="sidebar-section">
        <div className="sidebar-section-header"><span className="sidebar-section-title">对话</span><button className="new-chat-btn" aria-label="＋ 新对话" disabled={p.busy} onClick={p.onNewChat}><IconNewChat size={13}/>新对话</button></div>
        {p.sessions.map(s => <button key={s.id} className={'session-item ' + (p.active === s.id && p.page === 'chat' ? 'active' : '')} aria-label={s.title + ' ' + s.runtime} title={s.title} onClick={() => p.onSession(s)}><span className="session-item-title">{s.title}</span></button>)}
        {!p.sessions.length && <p className="sidebar-empty">开始对话后，记录会保存在这里。</p>}
      </div>
      <div className="sidebar-status"><span className={'status-dot ' + (p.ready ? '' : 'offline')}/><span className="sidebar-status-text">{p.runtime === 'api' ? (p.ready ? '聊天 API 已配置' : '聊天 API 未配置') : `${p.runtime} ${p.ready ? 'CLI 已检测到' : '未配置'}`}</span><button className="settings-gear" aria-label="AI 设置" title="设置（模型 · 执行引擎）" disabled={!p.boot} onClick={p.onSettings}><IconGear size={13}/>设置</button></div>
    </nav>
  </aside>;
}

export function PageHeader({title, description, busy, onRefresh}: {title: string; description?: string; busy: boolean; onRefresh: () => void}) {
  return <header className="page-head"><div><h1 className="page-title">{title}</h1>{description && <p className="page-subtitle">{description}</p>}</div><button className="btn btn-sm btn-ghost" disabled={busy} onClick={onRefresh}><IconRefresh size={14}/>刷新</button></header>;
}
