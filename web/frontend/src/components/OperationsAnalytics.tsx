import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchOperationsAccounts, fetchOperationsReport, refreshOperations, importOperations, importLegacyOperations, operationsExportUrl } from '../lib/api';
import type { OperationsAccount, OperationsReport, OperationsWork } from '../lib/api';
import '../styles/operations.css';

const PLATFORMS: Record<string, string> = { 'weixin-channels': '视频号', xiaohongshu: '小红书',
  douyin: '抖音', kuaishou: '快手', zhihu: '知乎', bilibili: 'B站', 'wechat-oa': '公众号' };
const COLORS = ['#5265c4', '#17a487', '#d48a26', '#af61ac', '#3685b8', '#d06b69', '#7c8c35'];
const fmt = (n: number | null | undefined) => n == null ? '—' : n.toLocaleString('zh-CN', { maximumFractionDigits: 1 });
const date = (n: number | null | undefined) => n ? new Date(n * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '暂无记录';
const source = (s: string) => s === 'platform_readback' ? '平台读回' : s === 'legacy_platform_history' ? '旧版快照（已确认归属）' : '人工导入';
const errorText = (e: unknown) => e instanceof Error ? e.message : '操作失败，请重试';

function Trend({ report, metric }: { report: OperationsReport; metric: 'followers' | 'likes' | 'posts' }) {
  const values = report.timeline.flatMap(r => r[metric] == null ? [] : [r[metric]!]);
  if (!values.length) return <div className="ops-empty">还没有可绘制的观测。导入历史快照，或在选择单个账号后手动同步。</div>;
  const max = Math.max(...values, 1), min = Math.min(...values, 0), range = max - min || 1;
  const x = (ts: number) => 54 + (ts - report.start) / (report.end - report.start) * 790;
  const y = (v: number) => 200 - (v - min) / range * 160;
  return <>
    <div className="ops-chart-wrap"><svg className="ops-chart" viewBox="0 0 880 242" role="img" aria-label="账号快照趋势，仅显示已保存的观测点">
      {[0, 0.5, 1].map(t => <g key={t}><line x1="54" x2="844" y1={y(min + range * t)} y2={y(min + range * t)} stroke="currentColor" opacity=".12" /><text x="45" y={y(min + range * t) + 4} textAnchor="end" fill="currentColor" fontSize="11">{fmt(min + range * t)}</text></g>)}
      {report.accounts.map((a, i) => {
        const points = report.timeline.filter(r => r.account === a.account && r[metric] != null);
        return <g key={a.account} fill={COLORS[i % COLORS.length]}>
          <polyline fill="none" stroke={COLORS[i % COLORS.length]} strokeWidth="2" strokeDasharray="5 4" points={points.map(p => `${x(p.observed_at)},${y(p[metric]!)}`).join(' ')} />
          {points.map(p => <circle key={p.observed_at} cx={x(p.observed_at)} cy={y(p[metric]!)} r="4"><title>{a.name} · {p.date} · {fmt(p[metric])} · {source(p.source)}</title></circle>)}
        </g>;
      })}
      <text x="54" y="228" fontSize="11" fill="currentColor">{new Date(report.start * 1000).toLocaleDateString('zh-CN')}</text>
      <text x="844" y="228" textAnchor="end" fontSize="11" fill="currentColor">{new Date(report.end * 1000).toLocaleDateString('zh-CN')}</text>
    </svg></div>
    <div className="ops-legend">{report.accounts.map((a, i) => <span key={a.account}><i style={{ background: COLORS[i % COLORS.length] }} />{a.name}</span>)}</div>
    <p className="ops-note">虚线仅连接已有观测点；缺失日期不补零，不代表连续日数据。时间统一为 UTC+8。</p>
  </>;
}

export default function OperationsAnalytics() {
  const [accounts, setAccounts] = useState<OperationsAccount[]>([]);
  const [account, setAccount] = useState('all');
  const [days, setDays] = useState(30);
  const [report, setReport] = useState<OperationsReport | null>(null);
  const [tab, setTab] = useState('overview');
  const [metric, setMetric] = useState<'followers' | 'likes' | 'posts'>('followers');
  const [sort, setSort] = useState<'views' | 'likes' | 'comments' | 'rate'>('views');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(0);
  const [platform, setPlatform] = useState('all');
  useEffect(() => setPage(0), [account, days, query, platform, sort]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [showImport, setShowImport] = useState(false);
  const [file, setFile] = useState<{ name: string; text: string; csv: boolean } | null>(null);
  const generation = useRef(0);
  const selected = accounts.find(a => a.account === account);
  const load = useCallback(async () => {
    const current = ++generation.current;
    setLoading(true); setError('');
    try {
      const [items, data] = await Promise.all([fetchOperationsAccounts(), fetchOperationsReport(account, days)]);
      if (current === generation.current) { setAccounts(items); setReport(data); }
    } catch (e) { if (current === generation.current) setError(errorText(e)); }
    finally { if (current === generation.current) setLoading(false); }
  }, [account, days]);
  useEffect(() => {
    setReport(null); void load();
    return () => { generation.current += 1; };
  }, [load]);
  const sync = async () => {
    if (account === 'all') return;
    setBusy(true); setError(''); setNotice('');
    try { const result = await refreshOperations(account); setNotice(result.message); await load(); }
    catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  };
  const chooseFile = async (input: File | undefined) => {
    setError(''); setFile(null);
    if (!input) return;
    if (input.size > 5 * 1024 * 1024) { setError('文件不能超过 5MB'); return; }
    try { setFile({ name: input.name, text: await input.text(), csv: input.name.toLowerCase().endsWith('.csv') }); }
    catch { setError('文件读取失败，请重新选择'); }
  };
  const importFile = async () => {
    if (!file || account === 'all') return;
    setBusy(true); setError('');
    try {
      const result = await importOperations(account, file.text, file.csv);
      setNotice(`已保存 ${result.snapshots} 个快照、${result.works} 条作品观测；重复记录不会再次计入。`);
      setFile(null); setShowImport(false); await load();
    } catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  };
  const importLegacy = async () => {
    if (!window.confirm(`旧版快照按平台保存。请确认这些历史属于「${selected?.name}」，确认后将导入此默认账号；原文件保留。`)) return;
    setBusy(true); setError('');
    try { const r = await importLegacyOperations(account); setNotice(`已导入 ${r.snapshots} 条旧版快照。`); await load(); }
    catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  };
  const downloadTemplate = () => {
    const content = 'kind,id,title,published_at,observed_at,followers,likes,following,posts,views,comments,shares,saves,topics,url\n';
    const url = URL.createObjectURL(new Blob(['\ufeff' + content], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a'); link.href = url; link.download = 'operations-template.csv'; link.click(); URL.revokeObjectURL(url);
  };
  const filtered = (report?.works || []).filter(w => (platform === 'all' || platform === w.platform) && `${w.title} ${w.topics.join(' ')}`.toLowerCase().includes(query.toLowerCase()));
  const works = [...filtered].sort((a, b) => (b[sort] ?? -1) - (a[sort] ?? -1));
  return <section className="card ops-panel" aria-label="运营分析">
    <header className="ops-head"><div><span className="ops-eyebrow">CONTENT INTELLIGENCE</span><h2>运营分析</h2><p>从账号变化，到作品表现，再到下一步行动。</p></div><span className="ops-local">本地数据 · 手动同步</span></header>
    <div className="ops-toolbar">
      <label>分析账号<select aria-label="分析账号" value={account} onChange={e => { setAccount(e.target.value); setNotice(''); setError(''); setFile(null); }} disabled={busy}>
        <option value="all">全部账号 · 对比查看</option>
        {accounts.map(a => <option key={a.account} value={a.account}>{a.name} · {PLATFORMS[a.platform] || a.platform}{accounts.filter(b => b.name === a.name && b.platform === a.platform).length > 1 ? ` · ${a.account.slice(-4)}` : ''}</option>)}
      </select></label>
      <label>分析区间<select aria-label="分析区间" value={days} onChange={e => setDays(Number(e.target.value))} disabled={busy}>{[7, 30, 90, 365].map(d => <option key={d} value={d}>近 {d} 天</option>)}</select></label>
      <div className="ops-actions"><button className="ops-secondary" onClick={() => setShowImport(!showImport)} disabled={account === 'all' || busy}>导入数据</button><button className="ops-primary" onClick={sync} disabled={account === 'all' || busy || !selected?.loggedIn}>{busy ? '处理中…' : '同步此账号'}</button></div>
    </div>
    {account === 'all' && <p className="ops-note">查看报表不会访问平台。需要导入或同步时，先选择一个独立账号。</p>}
    {!loading && accounts.length === 0 && !error && <p className="ops-note">暂无已添加的账号，请先到账号管理添加账号；分析页不会自动登录。</p>}
    {selected && !selected.loggedIn && <p className="ops-note">此账号未登录，可先导入后台导出的数据；平台同步需在账号管理中处理登录。</p>}
    {selected?.legacy_available && <button className="ops-secondary" disabled={busy} onClick={importLegacy}>导入旧版快照（先确认账号归属）</button>}
    {showImport && account !== 'all' && <div className="ops-import">
      <strong>导入到「{selected?.name}」</strong><p>支持 UTF-8 CSV 或 JSON，最多 5MB。数据会标记为“人工导入”，不会覆盖其他账号。</p>
      <button onClick={downloadTemplate}>下载空白 CSV 模板</button><input aria-label="选择运营数据文件" type="file" accept=".csv,.json" disabled={busy} onChange={e => void chooseFile(e.target.files?.[0])} />
      <details><summary>字段与 JSON 格式说明</summary><p>CSV 的 kind 为 snapshot（账号快照）或 work（作品）。观测时间 observed_at 必填；可用带时区 ISO 时间。空指标留空，不能用 0 代替缺失。作品需要 id 或原文链接，topics 用英文逗号分隔。</p><pre>{'{"snapshots":[{"observed_at":"2026-10-20T18:00:00+08:00","followers":100}],"works":[]}'}</pre><p>作品字段：id、title、published_at、observed_at、views、likes、comments、shares、saves、topics、url。</p></details>
      {file && <div className="ops-import-confirm"><span>已选 {file.name} · 目标：{selected?.name}</span><button className="ops-primary" disabled={busy} onClick={importFile}>确认导入并保存</button></div>}
    </div>}
    {error && <div className="ops-error" role="alert">{error}<button onClick={() => void load()} disabled={busy || loading}>重新读取本地报表</button></div>}
    {notice && <p className="ops-success" role="status">{notice}</p>}
    {loading && <p role="status" className="ops-note">正在读取本地报表…</p>}
    {report && <>
      <div className="ops-kpis">
        <div><span>粉丝数合计</span><strong>{fmt(report.summary.followers)}</strong><small>{report.summary.followers_coverage}/{report.summary.accounts} 个账号有值 · 未去重</small></div>
        <div><span>区间净增粉丝</span><strong>{report.summary.growth != null && report.summary.growth > 0 ? '+' : ''}{fmt(report.summary.growth)}</strong><small>有效基线 {report.summary.growth_coverage}/{report.summary.accounts}</small></div>
        <div><span>区间内已记录作品</span><strong>{fmt(report.summary.works)}</strong><small>另有 {report.summary.undated_works} 条缺少发布时间</small></div>
        <div><span>有阅读/播放值的作品</span><strong>{report.summary.with_views}<em> / {report.works.length}</em></strong><small>仅当前已记录样本</small></div>
      </div>
      <nav className="ops-tabs" aria-label="分析内容">{[['overview', '账号趋势'], ['works', '作品表现'], ['insights', '复盘与洞察']].map(([key, label]) => <button key={key} onClick={() => setTab(key)} className={tab === key ? 'on' : ''} aria-pressed={tab === key}>{label}</button>)}<div className="ops-export"><a href={operationsExportUrl(account, days, tab === 'works' ? 'works' : 'history')}>导出 CSV</a><a href={operationsExportUrl(account, days, 'report')}>完整报告 JSON</a></div></nav>
      {tab === 'overview' && <>
        <div className="ops-section-head"><h3>账号快照趋势</h3><select aria-label="趋势指标" value={metric} onChange={e => setMetric(e.target.value as typeof metric)}><option value="followers">粉丝</option><option value="likes">账号获赞（各平台口径不同）</option><option value="posts">作品总数</option></select></div>
        <Trend report={report} metric={metric} />
        <div className="ops-table-wrap"><table><thead><tr><th>账号 / 平台</th><th>粉丝</th><th>区间净增</th><th>实际基线</th><th>最后观测 / 来源</th><th>数据状态</th></tr></thead><tbody>{report.accounts.map(a => <tr key={a.account}><td><strong>{a.name}</strong><small>{PLATFORMS[a.platform] || a.platform}</small></td><td>{fmt(a.latest?.followers)}</td><td>{fmt(a.growth)}</td><td>{date(a.baseline_at)}</td><td>{date(a.latest?.observed_at)}<small>{a.latest ? source(a.latest.source) : '暂无来源'}</small></td><td><span className={`ops-status ${a.stale ? 'stale' : ''}`}>{!a.latest ? '暂无数据' : a.stale ? '超过24小时未更新' : '近24小时有更新'}</span></td></tr>)}</tbody></table></div>
        {selected && report.accounts[0]?.latest?.metrics?.length ? <div className="ops-platform-metrics"><h3>平台原始指标</h3><p className="ops-note">平台自身提供的统计窗口，不能视为上方所选区间。</p>{report.accounts[0].latest.metrics.map((m, i) => <span key={i}>{m.label} <strong>{m.value}</strong> <small>{m.vs}</small></span>)}</div> : null}
      </>}
      {tab === 'works' && <>
        <div className="ops-work-controls"><input aria-label="搜索作品" placeholder="搜索标题或话题" value={query} onChange={e => setQuery(e.target.value)} /><select aria-label="筛选作品平台" value={platform} onChange={e => setPlatform(e.target.value)}><option value="all">全部平台</option>{Object.entries(PLATFORMS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><select aria-label="作品排序" value={sort} onChange={e => setSort(e.target.value as typeof sort)}><option value="views">阅读/播放优先</option><option value="likes">点赞优先</option><option value="comments">评论优先</option><option value="rate">赞评率优先</option></select></div>
        <p className="ops-note">指标为最后观测时的累计值；跨平台口径不同。赞评率＝（赞＋评）÷阅读或播放，缺值不计算。</p>
        <div className="ops-table-wrap"><table><thead><tr><th>作品 / 账号</th><th>阅读/播放</th><th>点赞</th><th>评论</th><th>赞评率</th><th>发布 / 观测</th></tr></thead><tbody>{works.slice(page * 50, (page + 1) * 50).map((w: OperationsWork) => <tr key={`${w.account}:${w.id}`}><td>{w.url ? <a href={w.url} target="_blank" rel="noreferrer">{w.title}</a> : <strong>{w.title}</strong>}<small>{w.account_name} · {PLATFORMS[w.platform]} · {source(w.source)}</small>{w.topics.length > 0 && <small>{w.topics.map(t => `#${t}`).join(' ')}</small>}</td><td>{w.approximate ? '≈ ' : ''}{fmt(w.views)}</td><td>{fmt(w.likes)}</td><td>{fmt(w.comments)}</td><td>{w.rate == null ? '—' : `${w.approximate ? '≈ ' : ''}${w.rate.toFixed(2)}%`}</td><td>{w.published_at ? date(w.published_at) : '发布时间未提供'}<small>观测：{date(w.observed_at)}</small></td></tr>)}</tbody></table></div>
        {works.length > 50 && <div className="ops-pagination"><button disabled={page === 0} onClick={() => setPage(p => p - 1)}>上一页</button><span>{page + 1} / {Math.ceil(works.length / 50)} · 共 {works.length} 条</span><button disabled={(page + 1) * 50 >= works.length} onClick={() => setPage(p => p + 1)}>下一页</button></div>}
        {!works.length && <div className="ops-empty">暂无匹配作品。可导入带稳定作品 ID 的后台数据，或同步平台提供的作品信息。</div>}
      </>}
      {tab === 'insights' && <>
        <div className="ops-section-head"><h3>基于当前数据的复盘</h3><span className="ops-note">规则统计 · 非流量预测</span></div>
        <div className="ops-insights">{report.insights.map((r, i) => <article key={i}><h4>{r.title}</h4><p>{r.detail}</p></article>)}{!report.insights.length && <p>暂无可生成的结论，先积累快照和作品数据。</p>}</div>
        <div className="ops-breakdowns"><div><h3>话题表现</h3>{report.topics.length ? report.topics.slice(0, 12).map((t, i) => <p key={i}>#{t.topic} <small>{PLATFORMS[t.platform]} · {t.count} 条</small><strong>均值 {fmt(t.average_views)}</strong></p>) : <p className="ops-note">需要带发布时间和话题的作品样本。</p>}</div><div><h3>发文时段（UTC+8）</h3>{report.hours.length ? report.hours.slice(0, 12).map((t, i) => <p key={i}>{t.hour}:00–{t.hour}:59 <small>{PLATFORMS[t.platform]} · {t.count} 条</small><strong>均值 {fmt(t.average_views)}</strong></p>) : <p className="ops-note">需要带发布时间的作品样本。</p>}</div></div>
        <p className="ops-note">均值只涵盖有阅读/播放值的作品；样本少、作品曝光时长不同，不能据此断言最佳发布时间。</p>
        <h3>同步与导入记录</h3><div className="ops-log">{report.sync_log.map((r, i) => <div key={i}><time>{date(r.observed_at)}</time><span>{accounts.find(a => a.account === r.account)?.name || r.account}</span><span className={r.status === 'error' ? 'ops-red' : ''}>{r.message}</span></div>)}{!report.sync_log.length && <p className="ops-note">暂无同步或导入记录。</p>}</div>
      </>}
      <details className="ops-definitions"><summary>统计口径与数据边界</summary>{report.definitions.map(d => <p key={d}>{d}</p>)}<p>旧版按平台保存的历史未自动归到某个账号，防止串号；可核对归属后转换为模板格式导入。</p></details>
    </>}
  </section>;
}
