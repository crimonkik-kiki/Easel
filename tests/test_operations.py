import asyncio
from concurrent.futures import ThreadPoolExecutor
import csv
import io
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx

from web.operations import OperationsStore, csv_text, normalize
from web.operations_api import collector_payload, register_operations


@pytest.fixture
def store(tmp_path):
    return OperationsStore(tmp_path)


def sample(now=None, followers=100):
    now = int(now or time.time())
    return {'snapshots': [{'observed_at': now, 'followers': followers}],
            'works': [{'id': 'same-id', 'title': '模拟教程', 'published_at': now-100, 'observed_at': now,
                       'views': 1000, 'likes': 20, 'comments': 5, 'topics': ['AI'], 'url': 'https://example.invalid/work/1'}]}


ACCOUNTS = {'a': {'name': '模拟甲', 'platform': 'weixin-channels'}, 'b': {'name': '模拟乙', 'platform': 'weixin-channels'}}


def test_isolation_dedup_latest_cumulative_and_restart(store):
    now = int(time.time())
    store.ingest('a', sample(now-100, 100))
    store.ingest('b', sample(now-100, 900))
    assert store.ingest('a', sample(now-100, 100)) == {'snapshots': 0, 'works': 0}
    later = sample(now, 110)
    later['works'][0]['views'] = 1200
    store.ingest('a', later)
    report = OperationsStore(store.path.parents[2]).report(ACCOUNTS, now=now)
    assert report['summary']['followers'] == 1010
    assert len(report['works']) == 2
    assert next(w['views'] for w in report['works'] if w['account'] == 'a') == 1200
    assert store.report({'a': ACCOUNTS['a']}, now=now)['summary']['followers'] == 110


def test_report_preserves_zero_and_missing_values(store):
    now = int(time.time())
    data = sample(now, 0)
    data['works'][0].update(views=0, likes=0, comments=None)
    store.ingest('a', data)
    r = store.report(ACCOUNTS, now=now)
    assert r['summary']['followers'] == 0 and r['summary']['followers_coverage'] == 1
    assert r['summary']['growth'] is None
    assert r['works'][0]['rate'] is None and r['works'][0]['views'] == 0


def test_growth_requires_actual_baseline_and_complete_coverage(store):
    now = int(time.time())
    store.ingest('a', sample(now-31*86400, 100))
    store.ingest('a', sample(now-100, 120))
    r = store.report({'a': ACCOUNTS['a']}, days=30, now=now)
    assert r['summary']['growth'] == 20
    assert r['accounts'][0]['baseline_at'] == now-31*86400
    store.ingest('b', sample(now-100, 800))
    assert store.report(ACCOUNTS, days=30, now=now)['summary']['growth'] is None


def test_stale_end_does_not_fake_zero_growth(store):
    now = int(time.time())
    store.ingest('a', sample(now-100*86400))
    r = store.report({'a': ACCOUNTS['a']}, now=now)
    assert r['summary']['growth'] is None and r['accounts'][0]['stale']


def test_rate_unknown_dates_topics_and_timezone(store):
    now = int(time.time())
    data = sample(now)
    data['works'].append({'id': 'undated', 'title': '日期未知', 'observed_at': now, 'views': 100})
    store.ingest('a', data)
    r = store.report({'a': ACCOUNTS['a']}, now=now)
    assert r['summary']['works'] == 1 and r['summary']['undated_works'] == 1
    assert next(w['rate'] for w in r['works'] if w['id'] == 'same-id') == 2.5
    assert r['topics'][0]['topic'] == 'AI'
    assert r['hours'][0]['count'] == 1 and r['timezone'] == 'UTC+08:00'


def test_transaction_rolls_back_all_rows_on_timestamp_conflict(store):
    now = int(time.time())
    store.ingest('a', sample(now))
    conflict = {'snapshots': [{'observed_at': now-1, 'followers': 1}, {'observed_at': now, 'followers': 999}]}
    with pytest.raises(ValueError, match='冲突'):
        store.ingest('a', conflict)
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM snapshots').fetchone()[0] == 1


@pytest.mark.parametrize('value', [-1, float('inf'), float('nan'), True, 'unknown', 1.5])
def test_invalid_metrics_are_rejected(store, value):
    data = sample();data['snapshots'][0]['followers'] = value
    with pytest.raises(ValueError): store.ingest('a', data)
    assert store.latest('a') is None


@pytest.mark.parametrize('change', [
    {'observed_at': '2026-10-01T12:00:00'}, {'observed_at': 999999999999},
    {'observed_at': None}, {'followers': None},
])
def test_invalid_snapshot_time_or_empty_counters(store, change):
    data = {'snapshots': [{'observed_at': int(time.time()), 'followers': 0, **change}]}
    with pytest.raises(ValueError): store.ingest('a', data)


def test_parallel_identical_import_has_one_observation(store):
    data = sample()
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: store.ingest('a', data), range(4)))
    assert sum(r['snapshots'] for r in results) == 1
    assert sum(r['works'] for r in results) == 1


def test_csv_export_escapes_formula_and_strips_private_url_query(store):
    data = sample();data['works'][0].update(title='=SUM(1,1)', url='https://example.invalid/post/1?token=secret')
    store.ingest('a', data)
    r = store.report({'a': ACCOUNTS['a']})
    assert r['works'][0]['url'] == 'https://example.invalid/post/1'
    text = csv_text(r, 'works')
    assert "'=SUM" in text and 'secret' not in text
    assert len(list(csv.reader(io.StringIO(text.lstrip('\ufeff'))))) == 2


def test_collector_does_not_merge_by_title_or_management_url():
    result = {'loggedIn': True, 'followers': 1, 'notes': [
        {'title': '同名作品', 'url': 'https://channels.weixin.qq.com/platform/post/list'},
        {'title': '同名作品', 'url': 'https://example.invalid/posts/2', 'stat': '播放1.2万 · 赞20 · 评5'}]}
    data, skipped = collector_payload(result)
    assert skipped == 1 and len(data['works']) == 1
    assert data['works'][0]['views'] == 12000 and data['works'][0]['comments'] == 5
    assert data['works'][0]['approximate'] is True
    with pytest.raises(ValueError): collector_payload({'loggedIn': False})


def test_query_only_work_identity_requires_explicit_id(store):
    data = sample()
    data['works'][0].pop('id')
    data['works'][0]['url'] = 'https://example.invalid/watch?v=first'
    with pytest.raises(ValueError, match='稳定 id'):
        store.ingest('a', data)
    collected, skipped = collector_payload({'loggedIn': True, 'followers': 1,
        'notes': [{'title': '模拟作品', 'url': 'https://example.invalid/watch?v=second'}]})
    assert collected['works'] == [] and skipped == 1


@pytest.fixture
def api(tmp_path):
    app = FastAPI()
    async def listing():
        return [{'platform': key, 'basePlatform': 'weixin-channels', 'name': info['name'],
                 'nickname': info['name'], 'loggedIn': True, 'registered': True} for key, info in ACCOUNTS.items()]
    async def fetch(key):
        return {'loggedIn': True, 'followers': 123, 'notes': []}
    state = {'OUTPUTS_DIR': tmp_path, 'api_accounts': listing, 'ANALYTICS_PLATFORMS': {'weixin-channels'},
             '_assert_account_idle': lambda key: None, '_analytics_inflight': {},
             '_ANALYTICS_BUSY': set(), '_fetch_analytics': fetch}
    register_operations(app, lambda: state)
    return TestClient(app), state, app


def test_passive_reads_and_exports_never_fetch_platform(api):
    client, state, app = api
    async def forbidden(*args): pytest.fail('passive request launched collection')
    state['_fetch_analytics'] = forbidden
    for url in ['/api/operations/accounts', '/api/operations/report', '/api/operations/export?kind=works']:
        assert client.get(url).status_code == 200
    assert client.post('/api/operations/all/refresh').status_code == 400


def test_unregistered_platform_slots_do_not_count_as_accounts(api):
    client, state, app = api
    async def empty_registry():
        return [{'platform': 'weixin-channels', 'name': '视频号', 'registered': False,
                 'loggedIn': False}]
    state['api_accounts'] = empty_registry
    assert client.get('/api/operations/accounts').json() == []
    response = client.get('/api/operations/report')
    assert response.status_code == 200
    assert response.json()['summary']['accounts'] == 0
    assert response.json()['summary']['followers'] is None
    assert client.get('/api/operations/report?account=weixin-channels').status_code == 404


def test_import_survives_reload_and_failed_import_keeps_previous(api):
    client, state, app = api
    assert client.post('/api/operations/a/import', json=sample()).status_code == 200
    bad = sample();bad['snapshots'][0]['followers'] = -1
    assert client.post('/api/operations/a/import', json=bad).status_code == 400
    assert client.get('/api/operations/report?account=a').json()['summary']['followers'] == 100
    assert client.get('/api/operations/report?account=b').json()['summary']['followers'] is None
    assert client.get('/api/operations/report?account=missing').status_code == 404
    assert client.get('/api/operations/report?days=0').status_code == 400
    assert client.post('/api/operations/all/import', json=sample()).status_code == 400


def test_csv_import_and_export_can_be_read(api):
    client, state, app = api
    text = f'kind,observed_at,followers\nsnapshot,{int(time.time())},20\n'
    result = client.post('/api/operations/b/import', content=text, headers={'content-type': 'text/csv'})
    assert result.status_code == 200, result.text
    assert client.get('/api/operations/report?account=b').json()['summary']['followers'] == 20
    export = client.get('/api/operations/export?account=b&kind=history')
    assert 'manual_import' in export.text and 'attachment' in export.headers['content-disposition']


def test_import_rejects_account_claim_and_oversize_body(api):
    client, state, app = api
    data = sample();data['snapshots'][0]['account'] = 'b'
    assert client.post('/api/operations/a/import', json=data).status_code == 400
    assert client.post('/api/operations/a/import', content=' '*(5*1024*1024+1)).status_code == 413


def test_legacy_import_is_explicit_and_never_assigns_to_other_alias(api):
    client, state, app = api
    state['ANALYTICS_PLATFORMS'].add('a')
    folder = state['OUTPUTS_DIR'] / '_analytics';folder.mkdir(exist_ok=True)
    file = folder/'a.jsonl'
    file.write_text('{"ts":'+str(int(time.time())-100)+',"followers":42}\n', encoding='utf-8')
    assert client.get('/api/operations/report?account=a').json()['summary']['followers'] is None
    assert client.post('/api/operations/a/legacy-import', json={}).status_code == 400
    assert client.post('/api/operations/b/legacy-import', json={'confirm_account':'b'}).status_code == 400
    result = client.post('/api/operations/a/legacy-import', json={'confirm_account':'a'})
    assert result.status_code == 200 and result.json()['snapshots'] == 1
    assert file.is_file()
    report = client.get('/api/operations/report?account=a').json()
    assert report['summary']['followers'] == 42
    assert report['accounts'][0]['latest']['source'] == 'legacy_platform_history'


def test_refresh_serializes_and_preserves_data_after_failure(api):
    client, state, app = api
    async def scenario():
        started, finish = asyncio.Event(), asyncio.Event()
        calls = []
        async def fetch(key):
            calls.append(key);started.set();await finish.wait()
            return {'loggedIn': True, 'followers': 10}
        state['_fetch_analytics'] = fetch
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as http:
            first = asyncio.create_task(http.post('/api/operations/a/refresh'))
            await started.wait()
            second = asyncio.create_task(http.post('/api/operations/a/refresh'))
            await asyncio.sleep(0)
            assert (await http.post('/api/operations/a/import', json=sample())).status_code == 409
            finish.set()
            assert (await first).status_code == (await second).status_code == 200
            assert calls == ['a'] and state['_ANALYTICS_BUSY'] == set()
            async def expired(key): return {'loggedIn': False}
            state['_fetch_analytics'] = expired
            assert (await http.post('/api/operations/a/refresh')).status_code == 502
            data = (await http.get('/api/operations/report?account=a')).json()
            assert data['summary']['followers'] == 10
            assert data['sync_log'][0]['status'] == 'error'
    asyncio.run(scenario())


def test_http_collection_failure_keeps_actionable_safe_diagnostic(api):
    from fastapi import HTTPException
    client, state, app = api
    async def failed(key):
        raise HTTPException(502, '[PROFILE_BUSY] 账号目录被占用 token=private-value')
    state['_fetch_analytics'] = failed
    assert client.post('/api/operations/a/refresh').status_code == 502
    record = client.get('/api/operations/report?account=a').json()['sync_log'][0]
    assert 'PROFILE_BUSY' in record['message'] and 'HTTP 502' in record['message']
    assert 'private-value' not in record['message']
