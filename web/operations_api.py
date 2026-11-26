"""Explicit collection/import routes; all report/account GETs are passive."""
import asyncio
import csv
import io
import json
import re
import time

from fastapi import HTTPException, Request
from fastapi.responses import Response
from web.operations import OperationsStore, csv_text, public_url, work_url_id
from web.analytics_errors import safe_detail


def collector_payload(result):
    at = int(time.time())
    snapshots, works = [], []
    if result.get('loggedIn') is not True:
        raise ValueError('登录态失效，未写入数据；请在账号页处理')
    values = {k: result.get(k) for k in ('followers', 'likes', 'following', 'posts')}
    if any(v is not None for v in values.values()):
        metrics = [{k: str(m.get(k, ''))[:120] for k in ('label', 'value', 'vs')}
                   for m in result.get('metrics', [])[:30] if isinstance(m, dict)]
        snapshots.append({'observed_at': at, **values, 'metrics': metrics})
    skipped = 0
    for note in result.get('notes', [])[:500]:
        url = public_url(note.get('url'))
        # A shared management page is not an individual work identifier.
        management = any(s in url for s in ('content/manage', '/post/list', 'article/manage', '/creator/home'))
        work_id = str(note.get('id') or '') or (work_url_id(note.get('url')) if not management else '')
        if not work_id or not note.get('title'):
            skipped += 1
            continue
        row = {k: note.get(k) for k in ('title', 'published_at', 'topics', 'views', 'likes', 'comments', 'shares', 'saves')}
        row['topics'] = row['topics'] or []
        # Only explicit labeled counters are parsed; unknown metrics stay null.
        for key, label in [('views', '播放|阅读|浏览'), ('likes', '点赞|赞(?!同)'), ('comments', '评论|评')]:
            if row.get(key) is not None:
                continue
            match = re.search(r'(?:' + label + r')\s*([\d,.]+)\s*(万|亿|[wk])?', note.get('stat') or '', re.I)
            if match:
                if match[2]:
                    row['approximate'] = True
                raw = float(match[1].replace(',', ''))
                row[key] = round(raw * {'万': 10000, '亿': 100000000, 'w': 10000, 'k': 1000, '': 1}[str(match[2] or '').lower()])
        works.append({**row, 'id': work_id, 'url': url, 'observed_at': at})
    if not snapshots and not works:
        raise ValueError('平台没有返回可识别的指标或作品；未写入空快照')
    return {'snapshots': snapshots, 'works': works}, skipped


def register_operations(app, state):
    tasks = {}

    def store():
        return OperationsStore(state()['OUTPUTS_DIR'])

    async def accounts():
        g = state()
        rows = await g['api_accounts']()
        return [{**row, 'account': row['platform'], 'platform': row.get('basePlatform', row['platform']),
                 'name': row.get('nickname') or row.get('accountLabel') or row['name'],
                 'latest': store().latest(row['platform']), 'collecting': row['platform'] in tasks,
                 'legacy_available': row['platform'] in g['ANALYTICS_PLATFORMS'] and
                     (g['OUTPUTS_DIR'] / '_analytics' / (row['platform'] + '.jsonl')).is_file()}
                for row in rows if row.get('basePlatform', row['platform']) in g['ANALYTICS_PLATFORMS']
                and (row.get('registered') or row.get('loggedIn'))]

    async def selected(key):
        items = await accounts()
        values = {r['account']: {'name': r['name'], 'platform': r['platform']} for r in items if key == 'all' or key == r['account']}
        if not values and key != 'all':
            raise HTTPException(404, '账号不存在或不支持运营分析')
        return values

    @app.get('/api/operations/accounts')
    async def operations_accounts():
        return await accounts()

    @app.get('/api/operations/report')
    async def operations_report(account: str = 'all', days: int = 30):
        try:
            return store().report(await selected(account), days=days)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @app.get('/api/operations/export')
    async def operations_export(account: str = 'all', days: int = 30, kind: str = 'works'):
        try:
            report = store().report(await selected(account), days=days)
            if kind == 'report':
                content, mime, suffix = json.dumps(report, ensure_ascii=False, indent=2), 'application/json', 'json'
            else:
                content, mime, suffix = csv_text(report, kind), 'text/csv', 'csv'
            return Response(content, media_type=mime, headers={'Content-Disposition': f'attachment; filename="operations-{kind}.{suffix}"'})
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @app.post('/api/operations/{account}/import')
    async def operations_import(account: str, request: Request):
        await selected(account)
        if account == 'all':
            raise HTTPException(400, '导入前请选择一个独立账号')
        if account in tasks:
            raise HTTPException(409, '该账号正在同步，请完成后再导入')
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 5 * 1024 * 1024:
                raise HTTPException(413, '导入文件不能超过 5MB')
        try:
            text = data.decode('utf-8-sig')
            if 'text/csv' in request.headers.get('content-type', ''):
                rows = list(csv.DictReader(io.StringIO(text)))
                if any(r.get('kind') not in {'snapshot', 'work'} for r in rows):
                    raise ValueError('CSV 每行 kind 必须为 snapshot 或 work')
                payload = {'snapshots': [r for r in rows if r['kind'] == 'snapshot'],
                           'works': [r for r in rows if r['kind'] == 'work']}
            else:
                payload = json.loads(text)
            if isinstance(payload, dict):
                for kind in ('snapshots', 'works'):
                    for row in payload.get(kind, []) if isinstance(payload.get(kind, []), list) else []:
                        if isinstance(row, dict) and row.get('account') and row['account'] != account:
                            raise ValueError('文件中的账号与当前选择不一致，禁止跨账号归档')
            result = store().ingest(account, payload)
            store().log(account, 'imported', f'人工导入：新增 {result["snapshots"]} 个快照，{result["works"]} 条作品观测')
            return {'ok': True, **result, 'source': 'manual_import'}
        except (ValueError, TypeError, UnicodeError, csv.Error) as error:
            raise HTTPException(400, str(error)[:240]) from error

    @app.post('/api/operations/{account}/legacy-import')
    async def operations_legacy_import(account: str, request: Request):
        await selected(account)
        g = state()
        # Legacy files are platform-scoped: never assign them to a new alias automatically.
        if account not in g['ANALYTICS_PLATFORMS']:
            raise HTTPException(400, '旧版平台快照仅能经确认导入原默认账号，不能归入新增账号')
        if account in tasks:
            raise HTTPException(409, '请等待当前同步完成')
        try:
            confirmation = await request.json()
            if confirmation.get('confirm_account') != account:
                raise ValueError('需要明确确认快照属于当前默认账号')
            path = g['OUTPUTS_DIR'] / '_analytics' / (account + '.jsonl')
            if not path.is_file():
                raise ValueError('没有可导入的旧版历史')
            if path.stat().st_size > 5 * 1024 * 1024:
                raise ValueError('旧版历史超过5MB，请先整理后按模板导入')
            old = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
            payload = {'snapshots': [{**{key: row.get(key) for key in ('followers', 'likes', 'following', 'posts')},
                                      'observed_at': row.get('ts')} for row in old]}
            result = store().ingest(account, payload, source='legacy_platform_history')
            store().log(account, 'imported', '旧版平台快照经用户确认归属后导入；原文件保留')
            return {'ok': True, **result}
        except (ValueError, TypeError, AttributeError, UnicodeError) as error:
            raise HTTPException(400, str(error)[:240]) from error

    async def refresh(key):
        g = state()
        try:
            result = await g['_fetch_analytics'](key)
            payload, skipped = collector_payload(result)
            counts = store().ingest(key, payload, source='platform_readback')
            message = f'平台读回完成；{skipped} 条作品缺少稳定 ID/原文链接，未合并到作品库。'
            store().log(key, 'ok', message)
            return {'ok': True, **counts, 'skipped_works': skipped, 'message': message}
        except HTTPException as error:
            store().log(key, 'error', f'HTTP {error.status_code} · {safe_detail(error.detail)}；上次成功数据已保留')
            raise
        except (ValueError, TypeError) as error:
            store().log(key, 'error', str(error))
            raise HTTPException(502, str(error)) from error
        except Exception as error:
            store().log(key, 'error', '读取进程异常，上次成功数据已保留')
            raise HTTPException(502, '读取进程异常，请检查本机运行环境；原数据已保留') from error
        finally:
            g['_ANALYTICS_BUSY'].discard(key)
            tasks.pop(key, None)

    @app.post('/api/operations/{account}/refresh')
    async def operations_refresh(account: str):
        await selected(account)
        if account == 'all':
            raise HTTPException(400, '请逐个账号手动同步，不进行批量自动抓取')
        g = state()
        if account not in tasks:
            g['_assert_account_idle'](account)
            inflight = g['_analytics_inflight'].get(account)
            if inflight and not inflight.done():
                raise HTTPException(409, '该账号正在读取数据，请等待当前读取完成')
            g['_ANALYTICS_BUSY'].add(account)
            tasks[account] = asyncio.create_task(refresh(account))
            # Observe exception even if the caller disconnects.
            tasks[account].add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
        return await asyncio.shield(tasks[account])
