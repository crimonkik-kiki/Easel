"""Non-interactive loopback health probe with explicit failure classes.

Exit 20: transport unavailable; 21: a responding service violates its contract;
30: the probe itself failed and requires human judgement. None is success.
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


class ServiceUnavailable(Exception):
    pass


class ServiceUnhealthy(Exception):
    pass


def read_url(base, path):
    url = urllib.parse.urljoin(base + '/', path)
    if urllib.parse.urlsplit(url).netloc != urllib.parse.urlsplit(base).netloc:
        raise ServiceUnhealthy('HTML references a non-local application script')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=3) as response:
            data = response.read(4 * 1024 * 1024 + 1)
            if len(data) > 4 * 1024 * 1024:
                raise ServiceUnhealthy(f'{path}: response exceeds probe limit')
            return response.status, data, response.headers.get('Content-Type', '')
    except urllib.error.HTTPError as error:
        return error.code, error.read(8192), error.headers.get('Content-Type', '')
    except (urllib.error.URLError, TimeoutError, ConnectionError, socket.timeout) as error:
        raise ServiceUnavailable(f'{path}: {type(error).__name__}') from error


def evaluate(base, expect_queue=True, fetch=read_url):
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost'} or parsed.username or parsed.password:
        raise ValueError('Probe configuration must use an unauthenticated local HTTP endpoint')
    checks = {}
    status, body, content_type = fetch(base, '/')
    if status != 200 or 'text/html' not in content_type or not re.search(rb'id=[\"\x27]root[\"\x27]', body):
        raise ServiceUnhealthy('Root must return the Easel React HTML document, not merely HTTP 200')
    scripts = re.findall(rb'<script[^>]*src=[\"\x27]([^\"\x27]+)', body)
    if not scripts:
        raise ServiceUnhealthy('Root HTML has no application script')
    for script in scripts:
        path = script.decode('utf-8')
        code, data, mime = fetch(base, path)
        if code != 200 or len(data) < 100 or not any(kind in mime for kind in ('javascript', 'ecmascript')):
            raise ServiceUnhealthy('Application script is missing or invalid')
    checks['html_and_assets'] = 'passed'

    def document(path, expected_type):
        code, data, mime = fetch(base, path)
        if code != 200 or 'json' not in mime:
            raise ServiceUnhealthy(f'{path}: HTTP {code}, expected JSON')
        try:
            value = json.loads(data)
        except (ValueError, UnicodeError) as error:
            raise ServiceUnhealthy(f'{path}: invalid JSON') from error
        if not isinstance(value, expected_type):
            raise ServiceUnhealthy(f'{path}: unexpected JSON shape')
        return value

    accounts = document('/api/accounts', list)
    if any(not isinstance(row, dict) or not isinstance(row.get('platform'), str) for row in accounts):
        raise ServiceUnhealthy('Account cache contract invalid')
    checks['account_cache_api'] = 'passed'
    operations = document('/api/account-execution', list)
    if any(not isinstance(row, dict) or row.get('active') not in (0, 1) for row in operations):
        raise ServiceUnhealthy('Operation record contract invalid')
    checks['operation_records_api'] = 'passed'
    if expect_queue:
        capabilities = document('/api/publish-capabilities', dict)
        if capabilities.get('version') != '2026-10-16-v1' or not isinstance(capabilities.get('platforms'), dict):
            raise ServiceUnhealthy('Wrong platform capability version')
        jobs = document('/api/publish-jobs', list)
        if any(not isinstance(job, dict) or not all(field in job for field in ('id', 'account', 'state', 'snapshot')) for job in jobs):
            raise ServiceUnhealthy('Publication queue contract invalid')
        code, data, mime = fetch(base, '/api/publish-jobs/health-probe-nonexistent')
        try:
            missing_detail = json.loads(data).get('detail', '')
        except (ValueError, AttributeError, UnicodeError):
            missing_detail = ''
        if code != 404 or 'json' not in mime or '发布任务不存在' not in str(missing_detail):
            raise ServiceUnhealthy('Task detail handler is missing or invalid')
        checks['publication_queue_api'] = 'passed'
        checks['task_detail_route'] = 'passed_nonexistent_id_no_data_written'
        checks['capability_version'] = capabilities['version']
    return checks


def run_probe(base, expect_queue=True, fetch=read_url):
    try:
        return 0, {'marker': 'HEALTHY', 'checks': evaluate(base, expect_queue, fetch)}
    except ServiceUnavailable as error:
        return 20, {'marker': 'SERVICE_UNAVAILABLE', 'detail': str(error)}
    except ServiceUnhealthy as error:
        return 21, {'marker': 'SERVICE_UNHEALTHY', 'detail': str(error)}
    except Exception as error:
        return 30, {'marker': 'PROBE_ERROR_MANUAL_REVIEW', 'detail': f'{type(error).__name__}: {error}', 'requires_human_review': True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:7860')
    parser.add_argument('--phase2-only', action='store_true')
    parser.add_argument('--wait-seconds', type=float, default=0)
    args = parser.parse_args()
    deadline = time.monotonic() + min(max(args.wait_seconds, 0), 20)
    while True:
        code, result = run_probe(args.base, not args.phase2_only)
        # Only connection warm-up may be polled. Contract and probe errors stop immediately.
        if code != 20 or time.monotonic() >= deadline:
            print(json.dumps(result, ensure_ascii=True))
            return code
        time.sleep(.25)


if __name__ == '__main__':
    sys.exit(main())
