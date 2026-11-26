"""Local, account-isolated analytics. Reading reports never contacts a platform."""
from __future__ import annotations

from contextlib import contextmanager
import csv
import io
import json
import math
from pathlib import Path
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit, urlunsplit

TZ = timezone(timedelta(hours=8))
ACCOUNT_FIELDS = ('followers', 'likes', 'following', 'posts')
WORK_FIELDS = ('views', 'likes', 'comments', 'shares', 'saves')


def number(value):
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        raise ValueError('指标不能是布尔值')
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ValueError('指标必须是非负整数或空值') from None
    if not math.isfinite(result) or result < 0 or result != int(result) or result > 10**15:
        raise ValueError('指标必须是有效的非负整数')
    return int(result)


def stamp(value, *, optional=False):
    if value is None or value == '':
        if optional:
            return None
        raise ValueError('必须提供数据观测时间 observed_at')
    try:
        if isinstance(value, str) and not value.replace('.', '', 1).isdigit():
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                raise ValueError('时间必须包含时区，例如 +08:00')
            result = parsed.timestamp()
        else:
            result = float(value)
        if not math.isfinite(result) or result < 946684800 or result > time.time() + 300:
            raise ValueError('时间超出允许范围，不能导入未来数据')
        return int(result)
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError('无效时间：' + str(error)) from None


def public_url(value):
    if not value:
        return ''
    try:
        url = urlsplit(str(value))
        if url.scheme != 'https' or not url.hostname or url.username or url.password:
            return ''
        return urlunsplit((url.scheme, url.netloc, url.path, '', ''))
    except ValueError:
        return ''


def work_url_id(value):
    """Query values can identify a work or contain secrets: require an explicit ID."""
    url = public_url(value)
    return url if url and not urlsplit(str(value)).query else ''


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def clean_text(value, limit):
    return str(value or '').strip()[:limit]


def normalize(payload, *, source):
    if not isinstance(payload, dict):
        raise ValueError('导入内容必须是 JSON 对象')
    if set(payload) - {'snapshots', 'works'}:
        raise ValueError('导入仅支持 snapshots 和 works 字段，账号由当前选择决定')
    snapshots, works = [], []
    for kind in ('snapshots', 'works'):
        if not isinstance(payload.get(kind, []), list) or len(payload.get(kind, [])) > 5000:
            raise ValueError('每类最多导入 5000 条记录')
    for raw in payload.get('snapshots', []):
        if not isinstance(raw, dict):
            raise ValueError('快照必须是对象')
        row = {key: number(raw.get(key)) for key in ACCOUNT_FIELDS}
        if all(v is None for v in row.values()):
            raise ValueError('快照至少包含一项有效指标')
        row.update(observed_at=stamp(raw.get('observed_at')), source=source,
                   metrics=raw.get('metrics', []) if source == 'platform_readback' else [])
        snapshots.append(row)
    for raw in payload.get('works', []):
        if not isinstance(raw, dict):
            raise ValueError('作品必须是对象')
        row = {key: number(raw.get(key)) for key in WORK_FIELDS}
        url = public_url(raw.get('url'))
        work_id = clean_text(raw.get('id'), 200) or work_url_id(raw.get('url'))
        title = clean_text(raw.get('title'), 500)
        if not work_id or not title:
            raise ValueError('作品必须有稳定 id 或不含查询参数的 HTTPS 原文链接，以及标题')
        topics = raw.get('topics', [])
        if isinstance(topics, str):
            topics = [s.strip().lstrip('#') for s in topics.split(',') if s.strip()]
        if not isinstance(topics, list) or len(topics) > 30 or any(not isinstance(t, str) for t in topics):
            raise ValueError('话题应为最多 30 项的文本数组')
        row.update(id=work_id, title=title, url=url, observed_at=stamp(raw.get('observed_at')),
                   published_at=stamp(raw.get('published_at'), optional=True),
                   topics=[t.strip()[:80] for t in topics if t.strip()], source=source,
                   approximate=raw.get("approximate") is True)
        if row['published_at'] and row['published_at'] > row['observed_at']:
            raise ValueError('作品发布时间不能晚于观测时间')
        works.append(row)
    if not snapshots and not works:
        raise ValueError('没有可导入的数据')
    return snapshots, works


class OperationsStore:
    def __init__(self, outputs: Path):
        directory = outputs / '_analytics' / 'operations'
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / 'analytics.sqlite3'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS snapshots(account TEXT, observed_at INTEGER, data TEXT NOT NULL, PRIMARY KEY(account,observed_at))')
            db.execute('CREATE TABLE IF NOT EXISTS work_observations(account TEXT, work_id TEXT, observed_at INTEGER, data TEXT NOT NULL, PRIMARY KEY(account,work_id,observed_at))')
            db.execute('CREATE TABLE IF NOT EXISTS sync_log(id INTEGER PRIMARY KEY AUTOINCREMENT,account TEXT, observed_at INTEGER,status TEXT,message TEXT)')
            db.execute('CREATE INDEX IF NOT EXISTS work_account_time ON work_observations(account,observed_at)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def ingest(self, account, payload, *, source='manual_import'):
        snapshots, works = normalize(payload, source=source)
        inserted = {'snapshots': 0, 'works': 0}
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for table, rows, count in [('snapshots', snapshots, 'snapshots'), ('work_observations', works, 'works')]:
                for row in rows:
                    values = (account, row['observed_at']) if table == 'snapshots' else (account, row['id'], row['observed_at'])
                    where = 'account=? AND observed_at=?' if table == 'snapshots' else 'account=? AND work_id=? AND observed_at=?'
                    old = db.execute(f'SELECT data FROM {table} WHERE {where}', values).fetchone()
                    text = canonical(row)
                    if old:
                        if old['data'] != text:
                            raise ValueError('相同账号、作品和观测时间的数据冲突；请核对后使用新的观测时间')
                        continue
                    db.execute(f'INSERT INTO {table} VALUES({",".join("?" for _ in (*values, text))})', (*values, text))
                    inserted[count] += 1
        return inserted

    def log(self, account, status, message):
        with self.connect() as db:
            db.execute('INSERT INTO sync_log(account,observed_at,status,message) VALUES(?,?,?,?)',
                       (account, int(time.time()), status, clean_text(message, 240)))

    def latest(self, account):
        with self.connect() as db:
            row = db.execute('SELECT data FROM snapshots WHERE account=? ORDER BY observed_at DESC LIMIT 1', (account,)).fetchone()
            return json.loads(row['data']) if row else None

    def report(self, accounts: dict, *, days=30, now=None):
        if days not in (7, 30, 90, 365):
            raise ValueError('支持 7、30、90 或 365 天')
        now = int(now or time.time())
        start = now - days * 86400
        comparisons, timeline, works, logs = [], [], [], []
        for key, info in accounts.items():
            with self.connect() as db:
                history = [json.loads(r['data']) for r in db.execute('SELECT data FROM snapshots WHERE account=? AND observed_at<=? ORDER BY observed_at', (key, now))]
                # Latest observation as of report end. Do not sum repeated cumulative counters.
                rows = db.execute('''SELECT w.data FROM work_observations w JOIN
                    (SELECT work_id,MAX(observed_at) ts FROM work_observations WHERE account=? AND observed_at<=? GROUP BY work_id) latest
                    ON w.work_id=latest.work_id AND w.observed_at=latest.ts WHERE w.account=?''', (key, now, key)).fetchall()
                account_logs = db.execute('SELECT observed_at,status,message FROM sync_log WHERE account=? ORDER BY id DESC LIMIT 10', (key,)).fetchall()
            latest = history[-1] if history else None
            baseline = next((h for h in reversed(history) if h['observed_at'] <= start), None)
            growth = None
            if latest and baseline and latest['observed_at'] > baseline['observed_at'] and latest['followers'] is not None and baseline['followers'] is not None:
                growth = latest['followers'] - baseline['followers']
            fresh = latest is not None and latest['observed_at'] >= start
            comparisons.append({'account': key, **info, 'latest': latest, 'growth': growth if fresh else None,
                                'baseline_at': baseline['observed_at'] if baseline else None,
                                'stale': not latest or now - latest['observed_at'] > 86400})
            # Daily points only where observations exist; absent days remain gaps.
            daily = {}
            for h in history:
                if h['observed_at'] >= start:
                    daily[datetime.fromtimestamp(h['observed_at'], TZ).date().isoformat()] = h
            timeline += [{'account': key, 'name': info['name'], 'date': date, **h} for date, h in daily.items()]
            for r in rows:
                w = json.loads(r['data'])
                if w['published_at'] and not start <= w['published_at'] <= now:
                    continue
                w.update(account=key, account_name=info['name'], platform=info['platform'],
                         rate=((w['likes'] + w['comments']) / w['views'] * 100)
                         if w['views'] and w['likes'] is not None and w['comments'] is not None else None)
                works.append(w)
            logs += [{'account': key, **dict(row)} for row in account_logs]
        works.sort(key=lambda w: (w['views'] is not None, w['views'] or 0), reverse=True)
        known = [r['latest']['followers'] for r in comparisons if r['latest'] and r['latest']['followers'] is not None]
        growths = [r['growth'] for r in comparisons if r['growth'] is not None]
        dated = [w for w in works if w['published_at'] is not None]
        insights = []
        if len(growths) < len(comparisons):
            insights.append({'title': '增长基线不足', 'detail': f'{len(comparisons)-len(growths)} 个账号缺少所选区间起点或有效期末观测，不能计算完整净增。'})
        if any(r['stale'] for r in comparisons):
            insights.append({'title': '数据需要更新', 'detail': '部分账号超过 24 小时没有新观测；报表保留最后成功数据，未把取数失败记为零。'})
        if any(w['published_at'] is None for w in works):
            insights.append({'title': '部分作品缺少发布时间', 'detail': '未计入区间发布量和发文时段分析，仍在作品表展示，避免把历史作品误算作本期新增。'})
        if works:
            top = works[0]
            insights.append({'title': '已记录作品中的阅读/播放领先项', 'detail': f'「{top["title"]}」来自 {top["account_name"]}；排行仅基于当前已记录作品，不代表账号全部作品。' if top['views'] is not None else '作品暂无可排序的阅读/播放数据。'})
        comparable = [r for r in comparisons if r['growth'] is not None]
        if comparable:
            leader = max(comparable, key=lambda r: r['growth'])
            baseline_date = datetime.fromtimestamp(leader['baseline_at'], TZ).date().isoformat()
            insights.append({'title': '可比账号的粉丝变化',
                             'detail': f'{leader["name"]} 较 {baseline_date} 的基线变化 {leader["growth"]:+,}；仅比较有有效基线的账号。'})
        missing_views = sum(w['views'] is None for w in works)
        if missing_views:
            insights.append({'title': '补齐作品指标再比较', 'detail': f'{missing_views} 条作品没有阅读/播放值，未作为零参与均值或赞评率计算；建议补充后台导出数据。'})
        topics = {}
        hours = {}
        for w in dated:
            for topic in set(w['topics']):
                topics.setdefault((w['platform'], topic), []).append(w)
            hour = datetime.fromtimestamp(w['published_at'], TZ).hour
            hours.setdefault((w['platform'], hour), []).append(w)
        def groups(items, field):
            result = []
            for (platform, label), values in items.items():
                seen = [w['views'] for w in values if w['views'] is not None]
                result.append({'platform': platform, field: label, 'count': len(values),
                               'with_views': len(seen), 'average_views': round(sum(seen)/len(seen), 1) if seen else None})
            return sorted(result, key=lambda r: (r['average_views'] is not None, r['average_views'] or 0), reverse=True)
        return {'days': days, 'start': start, 'end': now, 'timezone': 'UTC+08:00',
                'summary': {'followers': sum(known) if known else None, 'followers_coverage': len(known),
                            'growth': sum(growths) if growths and len(growths) == len(comparisons) else None,
                            'growth_coverage': len(growths), 'accounts': len(comparisons), 'works': len(dated),
                            'undated_works': len(works)-len(dated), 'with_views': sum(w['views'] is not None for w in works)},
                'accounts': comparisons, 'timeline': sorted(timeline, key=lambda r: (r['date'], r['account'])),
                'works': works, 'insights': insights, 'topics': groups(topics, 'topic'), 'hours': groups(hours, 'hour'),
                'sync_log': sorted(logs, key=lambda r: r['observed_at'], reverse=True)[:30],
                'definitions': ['粉丝合计未对不同账号的同一用户去重。', '净增对比不晚于区间起点的最近快照，并显示实际基线时间。',
                                '作品指标是最后观测时的累计值，不是所选区间增量；只统计已采集或导入的样本。',
                                '赞评率=(点赞+评论)/阅读或播放×100%；任一缺失或分母为零则不计算。',
                                '各平台阅读/播放口径不同，跨平台排名仅供查看，不能直接比较流量质量。',
                                '带 ≈ 的作品含万/亿等缩写计数，是近似值；对应赞评率也仅为估算。',
                                '话题与时段数据仅为样本描述，不证明发布时间或话题导致流量变化。']}


def csv_text(report, kind):
    if kind == 'works':
        rows = report['works']
        columns = ('account', 'account_name', 'platform', 'id', 'title', 'published_at', 'observed_at', *WORK_FIELDS, 'rate', 'approximate', 'topics', 'source', 'url')
    elif kind == 'history':
        rows = report['timeline']
        columns = ('account', 'name', 'date', 'observed_at', *ACCOUNT_FIELDS, 'source')
    else:
        raise ValueError('导出类型只能是 works 或 history')
    out = io.StringIO(newline='')
    writer = csv.writer(out)
    writer.writerow(columns)
    for row in rows:
        values = []
        for key in columns:
            value = row.get(key)
            if isinstance(value, list):
                value = ','.join(str(item) for item in value)
            if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')):
                value = "'" + value
            values.append('' if value is None else value)
        writer.writerow(values)
    return '\ufeff' + out.getvalue()
