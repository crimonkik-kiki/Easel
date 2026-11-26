import { useState, useEffect, useCallback, useRef } from 'react';
import { fetchTrends, createIdea } from '../lib/api';
import type { TrendGroup } from '../lib/api';
import { IconFire, IconRefresh, IconBookmark, IconCheck } from './icons';

interface TrendsPageProps {
  onUseTopic: (title: string) => void;   // 一键做成内容 → 跳 chat
}

const ALL_PLATFORMS: { key: string; label: string }[] = [
  { key: 'weibo', label: '微博' },
  { key: 'douyin', label: '抖音' },
  { key: 'zhihu', label: '知乎' },
  { key: 'bilibili', label: 'B站' },
  { key: 'baidu', label: '百度' },
  { key: 'toutiao', label: '头条' },
];

export default function TrendsPage({ onUseTopic }: TrendsPageProps) {
  const [selected, setSelected] = useState<string[]>(['weibo', 'douyin', 'zhihu']);
  const [groups, setGroups] = useState<TrendGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [updated, setUpdated] = useState(0);
  const [saved, setSaved] = useState<Set<string>>(new Set());
  const requestId = useRef(0);

  const save = async (title: string, source: string) => {
    if (saved.has(title)) return;
    try {
      await createIdea({ title, source: `${source}热搜`, status: 'pending' });
      setSaved((prev) => new Set(prev).add(title));
    } catch { /* ignore */ }
  };

  const load = useCallback((pfs: string[]) => {
    const current = ++requestId.current;
    if (pfs.length === 0) { setGroups([]); setUpdated(0); setLoading(false); return; }
    setLoading(true);
    setError('');
    fetchTrends(pfs.join(','), 100)
      .then((d) => { if (current === requestId.current) { setGroups(d.trends); setUpdated(d.updated); } })
      .catch(() => { if (current === requestId.current) setError('热榜读取失败，请检查工作台服务与网络后重试。'); })
      .finally(() => { if (current === requestId.current) setLoading(false); });
  }, []);

  useEffect(() => { load(selected); }, [load, selected]);

  const toggle = (k: string) =>
    setSelected((prev) => prev.includes(k) ? prev.filter((x) => x !== k) : [...prev, k]);

  return (
    <div className="page-scroll trends-page">
      <div className="page-head">
        <div>
          <h1 className="page-title"><IconFire size={22} /> 热点雷达</h1>
          <p className="page-subtitle">
            多平台实时热搜，挑值得蹭的选题，一键交给 AI 做成你的内容。
            {updated > 0 && <span style={{ color: 'var(--text-tertiary)' }}> · 最近成功获取 {new Date(updated * 1000).toLocaleString('zh-CN', { hour12: false })}</span>}
          </p>
        </div>
        <button className="btn btn-sm" onClick={() => load(selected)} disabled={loading}>
          <IconRefresh size={14} /> {loading ? '刷新中…' : '刷新'}
        </button>
      </div>

      <div className="trend-platforms">
        {ALL_PLATFORMS.map((p) => (
          <button key={p.key} className={`chip ${selected.includes(p.key) ? 'active' : ''}`}
            onClick={() => toggle(p.key)}>{p.label}</button>
        ))}
      </div>

      {error && <div className="notice-error">{error}</div>}

      <div className="trend-grid">
        {groups.map((g) => (
          <div key={g.platform} className="card trend-col">
            <div className="trend-col-head">{g.label}<span className="trend-count">{g.items.length} / {g.total ?? g.items.length}</span></div>
            {g.stale && <div className="trend-empty" role="status">数据源暂不可用，显示 {g.updated ? new Date(g.updated * 1000).toLocaleString('zh-CN', { hour12: false }) : '上次'} 的缓存。</div>}
            {!!g.missing_hot && <div className="trend-empty">{g.missing_hot} 条未提供热度，保留上游排名。标为“热词搜索”的链接用于搜索，非原文。</div>}
            <div className="trend-list">
              {g.items.length === 0 && !loading && (
                <div className="trend-empty">
                  {g.ok === false ? '该平台暂时取不到（数据源不可用）' : '暂无数据'}
                </div>
              )}
              {g.items.map((it, i) => (
                <div key={i} className="trend-item">
                  <span className={`trend-rank ${i < 3 ? 'top' : ''}`}>{i + 1}</span>
                  <div className="trend-main">
                    <a className="trend-title" href={it.url || undefined} target="_blank" rel="noreferrer"
                      title={it.title}>{it.title}</a>
                    {it.hot && <span className="trend-hot">{it.hot}</span>}
                    {it.url_kind === 'search' && <span className="trend-hot">热词搜索</span>}
                  </div>
                  <button className="trend-save" title={saved.has(it.title) ? '已收藏到选题库' : '收藏到选题库'}
                    onClick={() => save(it.title, g.label)}>
                    {saved.has(it.title) ? <IconCheck size={14} /> : <IconBookmark size={14} />}
                  </button>
                  <button className="trend-use" title="做成内容"
                    onClick={() => onUseTopic(it.title)}>做内容</button>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
