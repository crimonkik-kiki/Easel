"""Passive localhost health checks, with distinct service and probe failure markers."""
import argparse
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--wait', type=int, default=0)
args = parser.parse_args()
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
checks = {}
try:
    deadline = time.monotonic() + args.wait
    while True:
        try:
            with opener.open('http://127.0.0.1:7860/', timeout=4) as response:
                html = response.read().decode('utf-8')
                break
        except (urllib.error.URLError, TimeoutError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(.5)
    expected = (ROOT / 'tmp/operations-ui-dist/index.html').read_text(encoding='utf-8')
    bundle = re.search(r'/assets/index-[^" ]+\.js', expected)
    if not bundle:
        raise RuntimeError('candidate index contains no JavaScript bundle')
    checks['root_and_candidate_bundle'] = bundle[0] in html
    for endpoint in ('/api/accounts', '/api/skills'):
        with opener.open('http://127.0.0.1:7860' + endpoint, timeout=8) as response:
            data = json.load(response)
        checks[endpoint] = isinstance(data, (dict, list))
    for endpoint in ('/api/operations/accounts', '/api/operations/report?account=all&days=30'):
        try:
            opener.open('http://127.0.0.1:7860' + endpoint, timeout=8)
            checks[endpoint + '_removed'] = False
        except urllib.error.HTTPError as error:
            checks[endpoint + '_removed'] = error.code == 404
    if not all(checks.values()):
        print(json.dumps({'marker':'SERVICE_UNHEALTHY', 'checks':checks}))
        raise SystemExit(2)
    print(json.dumps({'marker':'HEALTHY', 'checks':checks, 'collection_or_login_requests':0}))
except (urllib.error.URLError, TimeoutError) as error:
    print(json.dumps({'marker':'SERVICE_UNAVAILABLE', 'error':str(error), 'checks':checks}))
    raise SystemExit(2)
except SystemExit:
    raise
except Exception as error:
    print(json.dumps({'marker':'PROBE_ERROR_MANUAL_REVIEW', 'error':str(error), 'checks':checks}))
    raise SystemExit(3)
