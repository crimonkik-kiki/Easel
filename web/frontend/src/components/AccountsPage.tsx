import { useState, useEffect, useCallback, useRef } from 'react';
import {
  fetchAccounts, startLogin, loginStatus, mediaUrl,
  accountWhoami, logoutAccount, submitLoginSms,
  saveCredentials, getCredentials, startMpLogin, mpLoginStatus,
  createManagedAccount, editManagedAccount, selectManagedAccount, openManagedAccount, fetchPersonas, saveAccountCardSettings, deleteManagedAccount,
} from '../lib/api';
import type { AccountItem, AccountWhoami, PersonaItem, AccountCardSettings } from '../lib/api';
import { getWhoamiCache, setWhoamiCache, verifyStale } from '../lib/whoami';

const PLATFORM_LOGOS: Record<string, string> = {
  xiaohongshu: '/assets/platform-logos/xiaohongshu-hd.png',
  kuaishou: '/assets/platform-logos/kuaishou.svg',
  'weixin-channels': '/assets/platform-logos/weixin-channels.svg',
  zhihu: '/assets/platform-logos/zhihu.svg',
  bilibili: '/assets/platform-logos/bilibili.svg',
  douyin: '/assets/platform-logos/douyin.svg',
  'wechat-oa': '/assets/platform-logos/wechat-oa-hd.png',
};

function PlatformLogo({ platform }: { platform: string }) {
  return <img className="am-official-logo" src={`${PLATFORM_LOGOS[platform]}?v=hd2`} alt="" aria-hidden="true" />;
}

function CardMenuIcon({ name }: { name: string }) {
  const shapes: Record<string, string[]> = {
    person: ['M20 21v-2a7 7 0 0 0-14 0v2', 'M13 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8'],
    settings: ['m12 3 2 3 3-.2.5 3.2 2.5 2-2 2.5.2 3-3.2.5-2 2.5-2.5-2-3 .2-.5-3.2L3 12l2-2.5-.2-3L8 6z', 'M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6'],
    folder: ['M3 6h7l2 3h9v11H3z'],
    refresh: ['M3 5v5h5', 'M3.6 10a8 8 0 1 1 1.8 8'],
    globe: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18', 'M3 12h18M12 3c-5 5-5 13 0 18 5-5 5-13 0-18'],
    edit: ['m4 16 12-12 4 4L8 20H4zM14 6l4 4M3 23h18'],
    trash: ['M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7'],
  };
  return <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{(shapes[name] || shapes.person).map((d, i) => <path key={i} d={d} />)}</svg>;
}

function AccountStatIcon({ index }: { index: number }) {
  return <svg width="32" height="32" viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {index === 1 ? <><circle cx="16" cy="16" r="13" /><path d="m11.5 16 3 4 6-8" /></>
      : index === 2 ? <><path d="M16 4 29 27H3L16 4Z" /><path d="M16 12v7" /><circle cx="16" cy="23" r="1" fill="currentColor" stroke="none" /></>
      : <><path d="M18 6.3a5.2 5.2 0 1 0-8.1 6.4M5.2 22.1c.6-4 2.6-6.6 5.7-7.5" /><circle cx="18.5" cy="15.5" r="5.1" /><path d="M10.1 28c.7-4.4 3.7-7.3 8.4-7.3s7.7 2.9 8.4 7.3" /></>}
  </svg>;
}

type QRState = {
  platform: string;
  name: string;
  state: string;       // starting | qr_ready | success | expired | error | unknown
  message: string;
  qr: string;          // outputs 相对路径
  qrTs?: number;       // 二维码文件 mtime，作 img 缓存键：码刷新一次就变，避免看到过期旧码
};

const STATE_LABEL: Record<string, string> = {
  starting: '启动中…',
  qr_ready: '请扫码',
  window_login: '请在浏览器中登录',
  scanned: '扫码成功',
  sms_required: '需短信验证',
  verifying: '验证中…',
  success: '登录成功 ✅',
  expired: '二维码已过期',
  error: '登录出错',
  unknown: '等待中…',
};

/** 头像：有 URL 就显示图（加载失败退回首字），否则显示昵称/平台名首字。 */
function Avatar({ url, name }: { url?: string; name: string }) {
  const [broken, setBroken] = useState('');
  const initial = (name || '?').trim().charAt(0);
  if (url && broken !== url) {
    return <img className="account-avatar" src={url} alt={name}
      referrerPolicy="no-referrer" onError={() => setBroken(url)} />;
  }
  return <div className="account-avatar account-avatar-fallback">{initial}</div>;
}

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<AccountItem[]>([]);
  const [query, setQuery] = useState('');
  const [pickingPlatform, setPickingPlatform] = useState(false);
  const [platformQuery, setPlatformQuery] = useState('');
  const [groupManager, setGroupManager] = useState(false);
  const [cardPanel, setCardPanel] = useState<{ account: AccountItem; tab: string } | null>(null);
  const [cardForm, setCardForm] = useState<AccountCardSettings>({ persona: '', default_tags: '', content_suffix: '', proxy_mode: 'inherit', proxy_url: '' });
  const [cardGroup, setCardGroup] = useState('');
  const [personas, setPersonas] = useState<PersonaItem[]>([]);
  useEffect(() => { fetchPersonas().then(setPersonas).catch(() => {}); }, []);
  const openCardPanel = (account: AccountItem, tab: string) => {
    setErr(''); setCardPanel({ account, tab }); setCardGroup(account.group || '');
    setCardForm({ persona: account.persona || '', default_tags: account.publishSettings?.default_tags || '', content_suffix: account.publishSettings?.content_suffix || '', proxy_mode: account.network?.mode || 'inherit', proxy_url: account.network?.url || '' });
  };
  const [platformFilter, setPlatformFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [groupFilter, setGroupFilter] = useState('*');
  const [selected, setSelected] = useState<string[]>([]);
  const [editor, setEditor] = useState<{ key?: string; platform: string; label: string; group: string; remark: string } | null>(null);
  const [batchBusy, setBatchBusy] = useState(false);
  const [managing, setManaging] = useState(false);
  const [err, setErr] = useState('');
  const [qr, setQr] = useState<QRState | null>(null);
  const [qrNonce, setQrNonce] = useState(0);   // 每次登录 +1，稳定缓存 key，避免每次轮询 img 闪烁
  const [terminalMsg, setTerminalMsg] = useState('');
  const [busy, setBusy] = useState('');
  const [logoutBusy, setLogoutBusy] = useState('');
  const [smsCode, setSmsCode] = useState('');
  const [smsBusy, setSmsBusy] = useState(false);
  const [smsErr, setSmsErr] = useState('');
  // whoami 结果缓存到 localStorage：打开页面秒显示昵称/头像，不必每次都起浏览器校验
  const [whoami, setWhoami] = useState<Record<string, AccountWhoami | 'loading'>>(() => getWhoamiCache());
  // 凭证式登录（微信公众号 AppID/AppSecret）
  const [cred, setCred] = useState<{ platform: string; name: string } | null>(null);
  const [credForm, setCredForm] = useState({ appId: '', appSecret: '', author: '' });
  const [credBusy, setCredBusy] = useState(false);
  const [credMsg, setCredMsg] = useState('');
  const [credErr, setCredErr] = useState('');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const aliveRef = useRef(true);
  const qrPlatformRef = useRef('');   // 当前登录中的平台，供 submitSms 稳定引用
  const whoamiRequests = useRef<Record<string, number>>({});
  const qrRequest = useRef(0);

  useEffect(() => {
    aliveRef.current = true;
    return () => { aliveRef.current = false; qrRequest.current += 1; };
  }, []);

  // 真校验某平台登录态 + 拉昵称/头像（后端起浏览器，数秒）；手动「校验账号」或登录成功后调
  const runWhoami = useCallback((platform: string) => {
    const sequence = (whoamiRequests.current[platform] || 0) + 1;
    whoamiRequests.current[platform] = sequence;
    setWhoami((w) => ({ ...w, [platform]: 'loading' }));
    accountWhoami(platform, true)
      .then((r) => {
        if (aliveRef.current && whoamiRequests.current[platform] === sequence) {
          setWhoami((w) => ({ ...w, [platform]: r }));
          setWhoamiCache(platform, r);
          setAccounts((list) => list.map((account) =>
            account.platform === platform ? { ...account, loggedIn: r.loggedIn } : account));
        }
      })
      .catch(() => {
        if (aliveRef.current && whoamiRequests.current[platform] === sequence) {
          setWhoami((previous) => {
            const updated = { ...previous };
            const cached = getWhoamiCache()[platform];
            if (cached) updated[platform] = cached;
            else delete updated[platform];
            return updated;
          });
        }
      });
  }, []);

  // 打开页面：拉「快」状态（读 status.json，不起浏览器），随后后台自愈——对缓存缺失/过期的
  // 浏览器平台逐个真校验（whoami），结果到了刷新 UI，并令陈旧的假阴性缓存被真值覆盖。
  const load = useCallback(() => {
    setErr('');
    fetchAccounts()
      .then((list) => {
        if (!aliveRef.current) return;
        setAccounts(list);
        const targets = list
          .filter((a) => a.supported && a.backend !== 'biliup')
          .map((a) => a.platform);
        for (const account of list) {
          const cached = getWhoamiCache()[account.platform];
          if (cached && cached.loggedIn !== account.loggedIn) {
            setWhoamiCache(account.platform, null);
            setWhoami((previous) => {
              const updated = { ...previous };
              delete updated[account.platform];
              return updated;
            });
          }
        }
        verifyStale(targets, {
          alive: () => aliveRef.current,
          onUpdate: (platform, r) => {
            setWhoami((w) => ({ ...w, [platform]: r }));
            setAccounts((current) => current.map((account) =>
              account.platform === platform ? { ...account, loggedIn: r.loggedIn } : account));
          },
        });
      })
      .catch(() => setErr('加载账号状态失败'));
  }, []);

  useEffect(() => { load(); }, [load]);

  // 切回本标签页 / 窗口重新获得焦点时自动重拉账号态——登录/退出后即使漏了一次刷新，切回来也是最新的，
  // 用户无需手动刷新页面。（登录中弹着二维码时不打扰，避免打断轮询。）
  useEffect(() => {
    const refresh = () => { if (document.visibilityState === 'visible' && !pollRef.current) load(); };
    window.addEventListener('focus', refresh);
    document.addEventListener('visibilitychange', refresh);
    return () => {
      window.removeEventListener('focus', refresh);
      document.removeEventListener('visibilitychange', refresh);
    };
  }, [load]);

  const stopPoll = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }, []);

  useEffect(() => () => stopPoll(), [stopPoll]);

  const closeQr = useCallback(() => {
    qrRequest.current += 1;
    stopPoll();
    setQr(null);
    setBusy('');
    setSmsCode(''); setSmsErr(''); setSmsBusy(false);
    load();
  }, [stopPoll, load]);

  const submitSms = useCallback(async () => {
    const code = smsCode.replace(/\D/g, '');
    if (code.length < 4) { setSmsErr('请输入手机收到的验证码'); return; }
    setSmsBusy(true); setSmsErr('');
    try {
      await submitLoginSms(qrPlatformRef.current, code);
      setSmsCode('');
      // 乐观切到「验证中」转圈：后端读走码→verifying；成功→success，失败→退回 sms_required 带错误
      setQr((prev) => prev && ({ ...prev, state: 'verifying', message: '正在验证验证码…' }));
      // 不停轮询：runner 读走验证码填码提交后，state 会转 success / 或退回 sms_required 重试
    } catch (e) {
      setSmsErr(e instanceof Error ? e.message : '提交验证码失败');
    } finally {
      setSmsBusy(false);
    }
  }, [smsCode]);

  // 凭证式（公众号）：打开 AppID/AppSecret 表单
  const openCred = useCallback((a: AccountItem) => {
    setCred({ platform: a.platform, name: a.name });
    setCredForm({ appId: '', appSecret: '', author: '' });
    setCredMsg(''); setCredErr('');
    getCredentials(a.platform)
      .then((c) => { if (aliveRef.current && c.configured) setCredMsg(`已配置：AppID ${c.appIdMasked}`); })
      .catch(() => { /* 未配置，忽略 */ });
  }, []);

  const closeCred = useCallback(() => { setCred(null); setCredBusy(false); load(); }, [load]);

  const submitCred = useCallback(async () => {
    if (!cred) return;
    const appId = credForm.appId.trim();
    const appSecret = credForm.appSecret.trim();
    if (!appId || !appSecret) { setCredErr('AppID 和 AppSecret 都要填'); return; }
    setCredBusy(true); setCredErr(''); setCredMsg('');
    try {
      const r = await saveCredentials(cred.platform, { appId, appSecret, name: cred.name, author: credForm.author.trim() });
      if (r.ok) {
        runWhoami(cred.platform);
        closeCred();
      } else {
        setCredErr(r.message || '验证未通过');
      }
    } catch (e) {
      setCredErr(e instanceof Error ? e.message : '保存失败');
    } finally {
      setCredBusy(false);
    }
  }, [cred, credForm, runWhoami, closeCred]);

  const handleLogin = useCallback(async (a: AccountItem) => {
    if (!a.supported) return;
    if (a.backend === 'wechat-oa') { openCred(a); return; }   // 公众号走凭证表单，不扫码
    const sequence = ++qrRequest.current;
    stopPoll();
    setErr('');
    whoamiRequests.current[a.platform] = (whoamiRequests.current[a.platform] || 0) + 1;
    setWhoamiCache(a.platform, null);
    setTerminalMsg('');
    setBusy(a.platform);
    setSmsCode(''); setSmsErr('');
    qrPlatformRef.current = a.platform;
    setQrNonce((n) => n + 1);
    setQr({ platform: a.platform, name: a.name, state: 'starting',
            message: '正在启动浏览器并准备二维码…', qr: '' });
    try {
      const res = await startLogin(a.platform);
      if (!aliveRef.current || qrRequest.current !== sequence) return;
      if (res.mode === 'terminal') {
        setQr(null);
        setTerminalMsg(res.message || '请在终端登录');
        return;
      }
      if (res.mode === 'credentials') { setQr(null); openCred(a); return; }
      setQr({ platform: a.platform, name: a.name, state: res.state || 'starting',
              message: res.message || '', qr: res.qr || '', qrTs: res.qrTs });
      stopPoll();
      let polling = false;
      let finished = false;
      let failures = 0;
      const startedAt = Date.now();
      pollRef.current = setInterval(async () => {
        if (!aliveRef.current || qrRequest.current !== sequence || polling || finished) return;
        if (Date.now() - startedAt > 360000) {
          finished = true;
          stopPoll();
          setQr((previous) => previous && ({ ...previous, state: 'expired',
            message: '登录等待超时，请关闭后重新登录', qr: '' }));
          return;
        }
        polling = true;
        try {
          const s = await loginStatus(a.platform);
          if (!aliveRef.current || qrRequest.current !== sequence) return;
          failures = 0;
          setQr((prev) => prev && ({ ...prev, state: s.state, message: s.message, qr: s.qr, qrTs: s.qrTs }));
          if (['success', 'expired', 'error'].includes(s.state)) {
            finished = true;
            stopPoll();
            if (s.state === 'success') {
              setAccounts((list) => list.map((account) =>
                account.platform === a.platform ? { ...account, loggedIn: true } : account));
              setWhoamiCache(a.platform, null);
              runWhoami(a.platform);
            }
          }
        } catch {
          if (!aliveRef.current || qrRequest.current !== sequence) return;
          failures += 1;
          if (failures >= 5) {
            finished = true;
            stopPoll();
            setQr((previous) => previous && ({ ...previous, state: 'error',
              message: '登录状态连接中断，请检查网络后重新登录', qr: '' }));
          }
        } finally {
          polling = false;
        }
      }, 1000);
    } catch (e) {
      if (!aliveRef.current || qrRequest.current !== sequence) return;
      const message = e instanceof Error ? e.message : '启动登录失败';
      setQr((previous) => previous && ({ ...previous, state: 'error', message, qr: '' }));
    } finally {
      if (aliveRef.current && qrRequest.current === sequence) setBusy('');
    }
  }, [stopPoll, runWhoami, openCred]);

  // 公众号后台扫码登录（数据中心取数用，独立于 AppID 凭证）
  const handleMpLogin = useCallback(async (a: AccountItem) => {
    const sequence = ++qrRequest.current;
    stopPoll();
    setErr('');
    setBusy(a.platform + ':mp');
    setSmsCode(''); setSmsErr('');
    setQrNonce((n) => n + 1);
    setQr({ platform: a.platform, name: a.name + ' · 后台取数', state: 'starting',
            message: '正在启动浏览器并准备二维码…', qr: '' });
    try {
      const res = await startMpLogin(a.platform);
      if (!aliveRef.current || qrRequest.current !== sequence) return;
      setQr({ platform: a.platform, name: a.name + ' · 后台取数', state: res.state || 'starting',
              message: res.message || '', qr: res.qr || '', qrTs: res.qrTs });
      stopPoll();
      let polling = false;
      let finished = false;
      let failures = 0;
      const startedAt = Date.now();
      pollRef.current = setInterval(async () => {
        if (!aliveRef.current || qrRequest.current !== sequence || polling || finished) return;
        if (Date.now() - startedAt > 360000) {
          finished = true;
          stopPoll();
          setQr((previous) => previous && ({ ...previous, state: 'expired',
            message: '登录等待超时，请关闭后重新登录', qr: '' }));
          return;
        }
        polling = true;
        try {
          const s = await mpLoginStatus(a.platform);
          if (!aliveRef.current || qrRequest.current !== sequence) return;
          failures = 0;
          setQr((prev) => prev && ({ ...prev, state: s.state, message: s.message, qr: s.qr, qrTs: s.qrTs }));
          if (['success', 'expired', 'error'].includes(s.state)) {
            finished = true;
            stopPoll();
            if (s.state === 'success') {
              // 像快手一样“内存态立即翻”：wechat-oa 的 effLoggedIn 只看 a.loggedIn，这里直接把它乐观置 true，
              // 卡片瞬间变「已登录」，不必等 load() 那趟网络往返（后面 load() 再对账兜底）。
              setAccounts((list) => list.map((x) => x.platform === a.platform ? { ...x, loggedIn: true } : x));
              setWhoami((w) => { const n = { ...w }; delete n[a.platform]; return n; });
              setWhoamiCache(a.platform, null);
              runWhoami(a.platform);
              load();
            }
          }
        } catch {
          if (!aliveRef.current || qrRequest.current !== sequence) return;
          failures += 1;
          if (failures >= 5) {
            finished = true;
            stopPoll();
            setQr((previous) => previous && ({ ...previous, state: 'error',
              message: '登录状态连接中断，请检查网络后重新登录', qr: '' }));
          }
        } finally {
          polling = false;
        }
      }, 1000);
    } catch (e) {
      if (!aliveRef.current || qrRequest.current !== sequence) return;
      const message = e instanceof Error ? e.message : '启动后台登录失败';
      setQr((previous) => previous && ({ ...previous, state: 'error', message, qr: '' }));
    } finally {
      if (aliveRef.current && qrRequest.current === sequence) setBusy('');
    }
  }, [stopPoll, runWhoami, load]);

  const handleLogout = useCallback(async (a: AccountItem) => {
    if (!window.confirm(`确定退出「${a.name}」的登录？登录态将被清除，下次发布需重新扫码。`)) return;
    setLogoutBusy(a.platform);
    try {
      await logoutAccount(a.platform);
      // 内存态立即翻未登录（同登录路径），不等 load() 回来
      setAccounts((list) => list.map((x) => x.platform === a.platform ? { ...x, loggedIn: false } : x));
      setWhoami((w) => { const n = { ...w }; delete n[a.platform]; return n; });
      setWhoamiCache(a.platform, null);
      load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : '退出登录失败');
    } finally {
      setLogoutBusy('');
    }
  }, [load]);

  // 卡片真实登录态：whoami 权威（已返回则以它为准，自愈假阳性），否则用后端 last-known。
  const effLoggedIn = (a: AccountItem): boolean => {
    const w = whoami[a.platform];
    if (w && w !== 'loading') return w.loggedIn;
    return a.loggedIn;
  };

  const badge = (a: AccountItem) => {
    if (!a.supported) return <span className="badge">待重写</span>;
    if (whoami[a.platform] === 'loading') return <span className="badge">校验中…</span>;
    if (effLoggedIn(a)) return <span className="badge badge-ok">✓ 已登录</span>;
    return <span className="badge">未登录</span>;
  };

  const platformOf = (a: AccountItem) => a.basePlatform || a.platform;
  const groups = [...new Set(accounts.map((a) => a.group || '').filter(Boolean))].sort();
  const platforms = [...new Map(accounts.map((a) => [platformOf(a), a.platformName || a.name])).entries()];
  const registered = accounts.filter((a) => effLoggedIn(a) || a.registered || a.platform.includes('--') || a.group || a.remark);
  const visible = registered.filter((a) => {
    const w = whoami[a.platform];
    const name = w && w !== 'loading' ? w.name : '';
    return (!platformFilter || platformOf(a) === platformFilter)
      && (groupFilter === '*' || (a.group || '') === groupFilter)
      && (!statusFilter || (statusFilter === 'online' ? effLoggedIn(a) : !effLoggedIn(a)))
      && (!query.trim() || [a.name, a.accountLabel, a.group, a.remark, name].join(' ').toLowerCase().includes(query.trim().toLowerCase()));
  });
  const chosen = accounts.filter((a) => selected.includes(a.platform));
  const saveEditor = async () => {
    if (!editor || !editor.label.trim()) return;
    setManaging(true); setErr('');
    try {
      if (editor.key) await editManagedAccount(editor.key, editor);
      else await createManagedAccount(editor);
      setEditor(null); load();
    } catch (error) { setErr(error instanceof Error ? error.message : '保存失败'); }
    finally { setManaging(false); }
  };
  const checkSelected = async (targets = chosen) => {
    setBatchBusy(true); setErr('');
    let failures = 0;
    for (const a of targets.filter((a) => a.supported)) {
      if (!aliveRef.current) break;
      setWhoami((w) => ({ ...w, [a.platform]: 'loading' }));
      try {
        const result = await accountWhoami(a.platform, true);
        if (!aliveRef.current) break;
        setWhoamiCache(a.platform, result);
        setWhoami((w) => ({ ...w, [a.platform]: result }));
        setAccounts((list) => list.map((x) => x.platform === a.platform ? { ...x, loggedIn: result.loggedIn } : x));
      } catch {
        failures += 1;
        setWhoami((w) => { const updated = { ...w }; delete updated[a.platform]; return updated; });
      }
    }
    if (aliveRef.current) { setBatchBusy(false); if (failures) setErr(`${failures} 个账号校验未完成，请单独重试。`); }
  };

  const saveCardPanel = async () => {
    if (!cardPanel) return;
    setManaging(true); setErr('');
    try {
      if (cardPanel.tab === 'group') await editManagedAccount(cardPanel.account.platform, { label: cardPanel.account.accountLabel || cardPanel.account.name, group: cardGroup, remark: cardPanel.account.remark || '' });
      else await saveAccountCardSettings(cardPanel.account.platform, cardForm);
      setCardPanel(null); load();
    } catch (error) { setErr(error instanceof Error ? error.message : '保存失败'); }
    finally { setManaging(false); }
  };
  const removeCardAccount = async () => {
    if (!cardPanel) return;
    const key = cardPanel.account.platform;
    setManaging(true); setErr('');
    try {
      await deleteManagedAccount(key);
      setWhoamiCache(key, null); setWhoami((old) => { const next = { ...old }; delete next[key]; return next; });
      setSelected((old) => old.filter((x) => x !== key)); setCardPanel(null); load();
    } catch (error) { setErr(error instanceof Error ? error.message : '删除失败'); }
    finally { setManaging(false); }
  };
  const reloginCardAccount = async (account: AccountItem) => {
    if (!window.confirm(`重新登录「${account.accountLabel || account.name}」将清除该账号当前登录，再重新扫码；其他账号不受影响。继续？`)) return;
    try {
      await logoutAccount(account.platform); setWhoamiCache(account.platform, null);
      setWhoami((old) => { const next = { ...old }; delete next[account.platform]; return next; });
      setAccounts((list) => list.map((a) => a.platform === account.platform ? { ...a, loggedIn: false } : a));
      if (account.backend === 'wechat-oa') await handleMpLogin(account); else await handleLogin(account);
    } catch (error) { setErr(error instanceof Error ? error.message : '重新登录失败'); }
  };

  const choosePlatform = async (base: string) => {
    if (managing || busy) return;
    setManaging(true); setErr('');
    try {
      let account = accounts.find((a) => a.platform === base && !effLoggedIn(a));
      if (!account || account.multiAccount) {
        const label = (platforms.find(([key]) => key === base)?.[1] || base) + '新账号';
        const result = await createManagedAccount({ platform: base, label, group: groupFilter === '*' ? '' : groupFilter, remark: '' });
        const list = await fetchAccounts(); setAccounts(list);
        account = list.find((a) => a.platform === result.platform);
      }
      if (!account) throw new Error('未找到账号，请刷新后重试');
      setPickingPlatform(false); setPlatformQuery('');
      if (account.backend === 'wechat-oa') await handleMpLogin(account);
      else await handleLogin(account);
    } catch (error) { setErr(error instanceof Error ? error.message : '添加账号失败'); }
    finally { setManaging(false); }
  };

  return (
    <div className="accounts-page account-manager am-card-view">
      <div className="am-heading"><div><h1 className="page-title">账号管理</h1><p className="page-subtitle">多平台账号独立登录，统一管理与同步。</p></div></div>
      <div className="am-stats">
        {[[registered.length, '总账号'], [registered.filter(effLoggedIn).length, '已登录'], [registered.filter((a) => !effLoggedIn(a)).length, '需处理'], [new Set(registered.map(platformOf)).size, '覆盖平台']].map(([number, label], i) =>
          <div key={label} className={`am-stat am-stat-${i}`}><i><AccountStatIcon index={i} /></i><div><strong>{number}</strong><span>{label}</span></div></div>)}
      </div>
      {err && <div role="alert" className="am-error">{err}</div>}
      {terminalMsg && <div className="am-notice">{terminalMsg}</div>}
      <section className="card am-toolbar">
        <div className="am-filters">
          <select className="field" aria-label="筛选平台" value={platformFilter} onChange={(e) => setPlatformFilter(e.target.value)}><option value="">全部平台</option>{platforms.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
          <select className="field" aria-label="筛选状态" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}><option value="">全部状态</option><option value="online">已登录</option><option value="offline">需处理</option></select>
          <select className="field" aria-label="筛选分组" value={groupFilter} onChange={(e) => setGroupFilter(e.target.value)}><option value="*">全部分组</option><option value="">未分组</option>{groups.map((g) => <option key={g} value={g}>{g}</option>)}</select>
          <input className="field" aria-label="搜索账号" placeholder="⌕ 搜索账号名" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        <div className="am-toolbar-actions"><span>账号 {registered.length}</span><button className="btn" onClick={() => setGroupManager(true)}>▦ 分组管理</button><button className="btn btn-primary" disabled={managing} onClick={() => { setErr(''); setPickingPlatform(true); }}>＋ 添加账号</button></div>
        <div className="am-batch"><label><input type="checkbox" aria-label="选择当前列表全部账号" checked={visible.length > 0 && visible.every((a) => selected.includes(a.platform))} onChange={(e) => setSelected((old) => e.target.checked ? [...new Set([...old, ...visible.map((a) => a.platform)])] : old.filter((key) => !visible.some((a) => a.platform === key)))} /> 全选当前筛选</label><span>已选 {chosen.length} 个账号</span>
          <button className="btn btn-sm btn-ghost" disabled={!chosen.length} onClick={() => setSelected([])}>取消选择</button>
          <button className="btn btn-sm" disabled={!visible.length || batchBusy} onClick={() => checkSelected(visible)}>{batchBusy ? '正在同步…' : `⟳ 同步当前筛选（${visible.length}）`}</button>
          {chosen.length > 0 && <button className="btn btn-sm" disabled={batchBusy} onClick={() => checkSelected()}>同步所选</button>}
        </div>
      </section>
      <div className="am-account-grid">{visible.map((a) => {
        const w = whoami[a.platform]; const info = w && w !== 'loading' ? w : null;
        const logged = effLoggedIn(a); const cached = getWhoamiCache()[a.platform];
        const base = platformOf(a);
        return <article key={a.platform} className="card am-account-card" aria-label={a.accountLabel || a.name}>
          <header><input type="checkbox" aria-label={`选择 ${a.accountLabel || a.name}`} checked={selected.includes(a.platform)} onChange={(e) => setSelected((old) => e.target.checked ? [...new Set([...old, a.platform])] : old.filter((key) => key !== a.platform))} />
            <span className="am-platform-logo"><PlatformLogo platform={base} /></span>
            <div className="am-card-title"><strong>{info?.avatar && <Avatar url={info.avatar} name={info.name || a.name} />}{info?.name || a.accountLabel || a.name}</strong><div>{a.platformName || a.name} <span className="am-tag">{a.group || '未分组'}</span></div></div>{badge(a)}
          </header>
          <div className="am-session"><span>登录状态</span><strong className={logged ? 'am-green' : ''}>{w === 'loading' ? '同步中…' : logged ? '登录有效' : '需要登录'}</strong></div>
          <div className={`am-session-bar ${logged ? 'is-valid' : ''}`} />
          <div className="am-card-tags">{a.persona && <span className="am-tag am-tag-blue">定位：{a.persona}</span>}{(a.publishSettings?.default_tags || a.publishSettings?.content_suffix) && <span className="am-tag">已配发布设置</span>}{a.active && a.multiAccount && <span className="am-tag am-tag-blue">发布默认</span>}{a.remark && <span className="am-tag">{a.remark}</span>}</div>
          <div className="am-account-sub">{cached?.ts ? `最近校验 · ${new Date(cached.ts).toLocaleString('zh-CN', { hour12: false })}` : '尚未校验 · 点击同步获取最新状态'}</div>
          <footer>
            <button className="btn" disabled={w === 'loading' || batchBusy || !!busy} onClick={() => logged ? runWhoami(a.platform) : a.backend === 'wechat-oa' ? handleMpLogin(a) : handleLogin(a)}>{logged ? '⟳ 同步' : '登录账号'}</button>
            {a.multiAccount && <button className="btn" disabled={!logged || w === 'loading' || batchBusy} onClick={async () => { setErr(''); try { const result = await openManagedAccount(a.platform); setTerminalMsg(result.message); } catch (error) { setErr(error instanceof Error ? error.message : '打开失败'); } }}>↗ 打开后台</button>}
            <details className="am-more"><summary aria-label={`更多操作 ${a.accountLabel || a.name}`}>⋮</summary><div role="menu" onClick={(event) => event.currentTarget.closest('details')?.removeAttribute('open')}>
              <button role="menuitem" onClick={() => openCardPanel(a, 'detail')}><CardMenuIcon name="person" /> 账号详情</button>
              <button role="menuitem" onClick={() => openCardPanel(a, 'publish')}><CardMenuIcon name="settings" /> 发布设置</button>
              <button role="menuitem" onClick={() => openCardPanel(a, 'group')}><CardMenuIcon name="folder" /> 移动到分组 <span>›</span></button>
              <button role="menuitem" onClick={() => openCardPanel(a, 'persona')}><CardMenuIcon name="person" /> 绑定内容定位 <span>›</span></button>
              <button role="menuitem" disabled={!!busy || batchBusy || w === 'loading'} onClick={() => reloginCardAccount(a)}><CardMenuIcon name="refresh" /> 重新登录</button>
              <button role="menuitem" onClick={() => openCardPanel(a, 'network')}><CardMenuIcon name="globe" /> 桌面代理</button>
              <button role="menuitem" onClick={() => setEditor({ key: a.platform, platform: base, label: a.accountLabel || a.name, group: a.group || '', remark: a.remark || '' })}><CardMenuIcon name="edit" /> 重命名</button>
              {a.multiAccount && !a.active && <button role="menuitem" disabled={managing} onClick={async () => { setManaging(true); try { await selectManagedAccount(a.platform); load(); } catch (error) { setErr(error instanceof Error ? error.message : '切换失败'); } finally { setManaging(false); } }}>设为发布默认</button>}
              {logged && <button role="menuitem" disabled={logoutBusy === a.platform || w === 'loading'} onClick={() => handleLogout(a)}>退出登录</button>}
              <hr /><button role="menuitem" className="am-menu-danger" onClick={() => openCardPanel(a, 'delete')}><CardMenuIcon name="trash" /> 删除</button>
            </div></details>
          </footer>
        </article>;
      })}</div>
      {!visible.length && <div className="card am-empty">{registered.length ? '没有符合筛选条件的账号' : '还没有账号，点击“添加账号”选择平台并扫码登录。'}</div>}
      <p className="am-footnote">每个账号使用独立登录环境。打开后台后，请关闭该窗口再同步或发布。</p>
      {pickingPlatform && <div className="overlay" onClick={() => !managing && setPickingPlatform(false)}><div className="modal am-platform-modal" role="dialog" aria-modal="true" aria-label="添加账号 · 选择平台" onClick={(e) => e.stopPropagation()}>
        <div className="am-heading"><h3>添加账号 · 选择平台</h3><button className="btn btn-ghost" aria-label="关闭选择平台" disabled={managing} onClick={() => setPickingPlatform(false)}>×</button></div>
        <p className="am-account-sub">选择平台后将打开独立浏览器窗口，扫码登录后保存账号。小红书、抖音、快手、视频号、知乎支持多账号。</p>
        <input className="field" aria-label="搜索平台" placeholder="⌕ 搜索平台名称" autoFocus value={platformQuery} onChange={(e) => setPlatformQuery(e.target.value)} />
        {err && <div className="am-error">{err}</div>}
        <div className="am-platform-grid">{platforms.filter(([, label]) => label.includes(platformQuery.trim())).map(([base, label]) => {
          const existing = accounts.find((a) => a.platform === base); const unavailable = !existing?.multiAccount && registered.some((a) => platformOf(a) === base);
          return <button key={base} disabled={managing || unavailable} onClick={() => choosePlatform(base)}><span className="am-platform-symbol"><PlatformLogo platform={base} /></span><strong>{label}</strong>{unavailable && <small>已有账号</small>}</button>;
        })}</div>
        {!platforms.some(([, label]) => label.includes(platformQuery.trim())) && <div className="am-empty">该平台暂未接入</div>}
        <p className="am-account-sub">仅展示本机已接入的平台。B站、公众号目前各支持一个账号。</p>
      </div></div>}
      {groupManager && <div className="overlay" onClick={() => setGroupManager(false)}><div className="modal am-editor" role="dialog" aria-modal="true" aria-label="分组管理" onClick={(e) => e.stopPropagation()}><h3>分组管理</h3><p className="am-account-sub">在账号的“更多 → 编辑账号”中设置分组，同名分组自动归并。</p>{groups.map((group) => <button className="am-group" key={group} onClick={() => { setGroupFilter(group); setGroupManager(false); }}><span>{group}</span><span>{registered.filter((a) => a.group === group).length} 个账号 →</span></button>)}{!groups.length && <p>暂无分组，可先编辑账号添加。</p>}<button className="btn" onClick={() => setGroupManager(false)}>关闭</button></div></div>}
      {cardPanel && <div className="overlay" onClick={() => !managing && setCardPanel(null)}><form className="modal am-editor am-card-settings" role="dialog" aria-modal="true" aria-label={{ detail: '账号详情', publish: '发布设置', group: '移动到分组', persona: '绑定内容定位', network: '桌面代理', delete: '删除账号' }[cardPanel.tab]} onClick={(event) => event.stopPropagation()} onSubmit={(event) => { event.preventDefault(); if (cardPanel.tab === 'delete') removeCardAccount(); else saveCardPanel(); }}>
        <h3>{{ detail: '账号详情', publish: '发布设置', group: '移动到分组', persona: '绑定内容定位', network: '桌面代理', delete: '删除账号' }[cardPanel.tab]}</h3>
        <p className="am-account-sub">{cardPanel.account.platformName} · {cardPanel.account.accountLabel || cardPanel.account.name}</p>
        {err && <div role="alert" className="am-error">{err}</div>}
        {cardPanel.tab === 'detail' && <dl className="am-detail-list"><dt>平台昵称</dt><dd>{(() => { const info = whoami[cardPanel.account.platform]; return info && info !== 'loading' ? info.name || '尚未获取' : '尚未获取'; })()}</dd><dt>账号标识</dt><dd>{cardPanel.account.platform}</dd><dt>登录状态</dt><dd>{effLoggedIn(cardPanel.account) ? '已登录' : '未登录'}</dd><dt>分组</dt><dd>{cardPanel.account.group || '未分组'}</dd><dt>内容定位</dt><dd>{cardPanel.account.persona || '未绑定'}</dd><dt>备注</dt><dd>{cardPanel.account.remark || '无'}</dd></dl>}
        {cardPanel.tab === 'publish' && <><label className="field-label">默认话题标签</label><input className="field" aria-label="默认话题标签" maxLength={300} value={cardForm.default_tags} onChange={(event) => setCardForm({ ...cardForm, default_tags: event.target.value })} placeholder="例如：AI,职场,学习" /><p className="am-account-sub">发布页未填写标签时使用；发布页填写的标签优先。</p><label className="field-label">正文尾注</label><textarea className="field" aria-label="正文尾注" rows={4} maxLength={1000} value={cardForm.content_suffix} onChange={(event) => setCardForm({ ...cardForm, content_suffix: event.target.value })} placeholder="发布时追加到正文末尾，例如品牌署名。" /></>}
        {cardPanel.tab === 'group' && <><label className="field-label">账号分组</label><input className="field" aria-label="移动账号分组" list="card-group-options" maxLength={60} value={cardGroup} onChange={(event) => setCardGroup(event.target.value)} placeholder="选择分组或输入新分组，留空表示未分组" /><datalist id="card-group-options">{groups.map((g) => <option key={g} value={g} />)}</datalist></>}
        {cardPanel.tab === 'persona' && <><label className="field-label">内容定位</label><select className="field" aria-label="账号内容定位" value={cardForm.persona} onChange={(event) => setCardForm({ ...cardForm, persona: event.target.value })}><option value="">未绑定</option>{personas.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}</select><p className="am-account-sub">使用“画像”中的定位。发布前预检会按目标账号绑定的定位进行检查。</p></>}
        {cardPanel.tab === 'network' && <><label className="field-label">网络模式</label><select className="field" aria-label="账号网络模式" disabled={!cardPanel.account.multiAccount} value={cardForm.proxy_mode} onChange={(event) => setCardForm({ ...cardForm, proxy_mode: event.target.value })}><option value="inherit">沿用工作台配置</option><option value="system">跟随系统代理</option><option value="direct">浏览器直连</option><option value="fixed">固定代理</option></select>{cardForm.proxy_mode === 'fixed' && <><label className="field-label">代理地址</label><input className="field" aria-label="账号代理地址" maxLength={500} value={cardForm.proxy_url} onChange={(event) => setCardForm({ ...cardForm, proxy_url: event.target.value })} placeholder="http://127.0.0.1:7890" /></>}<p className="am-account-sub">{cardPanel.account.multiAccount ? '对该账号后续登录、校验、打开后台和发布生效。支持无认证的 HTTP/HTTPS/SOCKS5 代理。浏览器直连仍受系统 TUN 路由影响。' : '该平台暂不支持独立代理，保留工作台原配置。'}</p></>}
        {cardPanel.tab === 'delete' && <div className="am-error">确定删除此账号？该账号的登录资料、卡片设置将被清除；其他账号和已生成内容不受影响。以后可重新添加并扫码登录。</div>}
        <div className="am-actions"><button type="button" className="btn" disabled={managing} onClick={() => setCardPanel(null)}>{cardPanel.tab === 'detail' ? '关闭' : '取消'}</button>{cardPanel.tab !== 'detail' && <button className={`btn ${cardPanel.tab === 'delete' ? 'btn-danger' : 'btn-primary'}`} disabled={managing}>{managing ? '处理中…' : cardPanel.tab === 'delete' ? '确认删除账号' : '保存设置'}</button>}</div>
      </form></div>}
      {editor && <div className="overlay" onClick={() => !managing && setEditor(null)}><form className="modal am-editor" role="dialog" aria-modal="true" aria-label={editor.key ? '编辑账号' : '添加账号'} onClick={(e) => e.stopPropagation()} onSubmit={(e) => { e.preventDefault(); saveEditor(); }}>
        <h3>{editor.key ? '编辑账号' : '添加账号'}</h3>
        <p className="am-account-sub">新增账号将使用独立登录环境；保存后请在列表中扫码登录。</p>
        {err && <div role="alert" className="am-error">{err}</div>}
        <label className="field-label">平台</label><select className="field" aria-label="账号平台" disabled={!!editor.key || managing} value={editor.platform} onChange={(e) => setEditor({ ...editor, platform: e.target.value })}>
          {(editor.key ? platforms : platforms.filter(([key]) => accounts.some((a) => platformOf(a) === key && a.multiAccount))).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select>
        <label className="field-label">账号名称</label><input className="field" aria-label="账号名称" autoFocus required maxLength={60} value={editor.label} onChange={(e) => setEditor({ ...editor, label: e.target.value })} placeholder="例如：品牌主号" />
        <label className="field-label">分组</label><input className="field" aria-label="账号分组" list="am-group-options" maxLength={60} value={editor.group} onChange={(e) => setEditor({ ...editor, group: e.target.value })} placeholder="选择已有分组或输入新分组" />
        <datalist id="am-group-options">{groups.map((g) => <option key={g} value={g} />)}</datalist>
        <label className="field-label">备注</label><input className="field" aria-label="账号备注" maxLength={240} value={editor.remark} onChange={(e) => setEditor({ ...editor, remark: e.target.value })} placeholder="用途、负责人等（可选）" />
        <div className="am-actions"><button type="button" className="btn" disabled={managing} onClick={() => setEditor(null)}>取消</button><button className="btn btn-primary" disabled={managing || !editor.label.trim()}>{managing ? '保存中…' : '保存账号'}</button></div>
      </form></div>}

      {qr && (
        <div className="overlay" onClick={closeQr}>
          <div className="modal" style={{ width: 360, maxWidth: '100%', textAlign: 'center' }}
            onClick={(e) => e.stopPropagation()}>
            <h3 style={{ margin: '0 0 4px' }}>登录 {qr.name}</h3>
            <div style={{ fontSize: 13, marginBottom: 14,
              color: qr.state === 'success' ? 'var(--green)'
                : ['error', 'expired'].includes(qr.state) ? 'var(--red)' : 'var(--text-secondary)' }}>
              {STATE_LABEL[qr.state] || qr.state}{qr.message ? ` — ${qr.message}` : ''}
            </div>
            {qr.state === 'sms_required' ? (
              <div style={{ padding: '6px 4px 2px' }}>
                <div style={{ fontSize: 13, marginBottom: 10,
                  color: /错误|过期|失败|重新|未找到|未完成|不正确|失效/.test(qr.message || '')
                    ? 'var(--red)' : 'var(--text-secondary)' }}>
                  {qr.message || '平台风控要求短信验证，验证码已发到你手机，请输入：'}
                </div>
                <input
                  value={smsCode}
                  onChange={(e) => setSmsCode(e.target.value.replace(/\D/g, '').slice(0, 8))}
                  onKeyDown={(e) => { if (e.key === 'Enter') submitSms(); }}
                  placeholder="短信验证码" inputMode="numeric" autoFocus
                  style={{ width: '100%', boxSizing: 'border-box', textAlign: 'center',
                    letterSpacing: 6, fontSize: 20, padding: '10px 12px',
                    border: '1px solid var(--border)', borderRadius: 8 }} />
                {smsErr && <div style={{ color: 'var(--red)', fontSize: 12, marginTop: 6 }}>{smsErr}</div>}
                <button className="btn btn-primary btn-block" style={{ marginTop: 12 }}
                  disabled={smsBusy} onClick={submitSms}>
                  {smsBusy ? '提交中…' : '提交验证码'}
                </button>
              </div>
            ) : ['qr_ready', 'window_login'].includes(qr.state) && qr.qr ? (
              <img className="qr-img" src={`${mediaUrl(qr.qr)}?v=${qr.qrTs || qrNonce}`} alt="登录二维码" />
            ) : qr.state === 'window_login' ? (
              <div style={{ padding: 30, fontSize: 14, lineHeight: 1.8 }}>
                请在弹出的独立浏览器窗口中完成扫码或短信验证，保留窗口直到登录完成。
              </div>
            ) : qr.state === 'scanned' ? (
              <div className="loading" style={{ padding: 40 }}><div className="spinner" />
                {qr.message || '扫码成功，请在手机上确认登录，正在等待平台验证…'}
              </div>
            ) : qr.state === 'verifying' ? (
              <div className="loading" style={{ padding: 40 }}><div className="spinner" />正在验证验证码，登录中…</div>
            ) : qr.state === 'success' ? (
              <div style={{ fontSize: 48, padding: 40 }}>✅</div>
            ) : ['error', 'expired'].includes(qr.state) ? (
              <div style={{ fontSize: 13, color: 'var(--red)', padding: 30 }}>
                {qr.message || '登录失败'}<br />请根据上方具体原因排查；可关闭后重试，日志在 outputs/_login/。
              </div>
            ) : (
              <div className="loading" style={{ padding: 40 }}><div className="spinner" />准备二维码…</div>
            )}
            <div style={{ marginTop: 16 }}>
              <button className="btn" onClick={closeQr}>{qr.state === 'success' ? '完成' : '关闭'}</button>
            </div>
          </div>
        </div>
      )}

      {cred && (
        <div className="overlay" onClick={closeCred}>
          <div className="modal" style={{ width: 420, maxWidth: '100%' }} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ margin: '0 0 4px' }}>配置 {cred.name}</h3>
            <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', marginBottom: 14, lineHeight: 1.6 }}>
              公众号用官方接口发布，需填开发者凭证（公众平台 → 设置与开发 → 开发接口管理）。<br />
              ⚠️ 需把本服务器出口 IP 加入公众号「IP 白名单」，否则报 40164。文章发到<b>草稿箱</b>，群发请到 mp 后台确认。
            </div>
            {credMsg && <div style={{ fontSize: 12.5, color: 'var(--green)', marginBottom: 10 }}>{credMsg}</div>}
            <label style={{ fontSize: 12, color: 'var(--text-secondary)' }}>AppID</label>
            <input value={credForm.appId} autoFocus
              onChange={(e) => setCredForm((f) => ({ ...f, appId: e.target.value.trim() }))}
              placeholder="wx..." style={{ width: '100%', boxSizing: 'border-box', padding: '9px 12px',
                margin: '4px 0 12px', border: '1px solid var(--border)', borderRadius: 8, fontSize: 14 }} />
            <label style={{ fontSize: 12, color: 'var(--text-secondary)' }}>AppSecret</label>
            <input value={credForm.appSecret} type="password"
              onChange={(e) => setCredForm((f) => ({ ...f, appSecret: e.target.value.trim() }))}
              placeholder="开发者密钥（不会回显）" style={{ width: '100%', boxSizing: 'border-box', padding: '9px 12px',
                margin: '4px 0 12px', border: '1px solid var(--border)', borderRadius: 8, fontSize: 14 }} />
            <label style={{ fontSize: 12, color: 'var(--text-secondary)' }}>默认作者（可选）</label>
            <input value={credForm.author}
              onChange={(e) => setCredForm((f) => ({ ...f, author: e.target.value }))}
              placeholder="文章署名" style={{ width: '100%', boxSizing: 'border-box', padding: '9px 12px',
                margin: '4px 0 4px', border: '1px solid var(--border)', borderRadius: 8, fontSize: 14 }} />
            {credErr && <div style={{ color: 'var(--red)', fontSize: 12.5, marginTop: 8 }}>{credErr}</div>}
            <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
              <button className="btn btn-primary" style={{ flex: 1 }} disabled={credBusy} onClick={submitCred}>
                {credBusy ? '验证中…' : '保存并验证'}
              </button>
              <button className="btn" onClick={closeCred}>关闭</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
