import json
import pytest
from web.health_probe import run_probe, ServiceUnavailable


def healthy(base, path):
    if path == '/':
        return 200, b'<div id="root"></div><script src="/assets/app.js"></script>', 'text/html'
    if path == '/assets/app.js':
        return 200, b'const app = 1;' * 20, 'application/javascript'
    documents = {'/api/accounts': [], '/api/account-execution': [], '/api/publish-jobs': [],
                 '/api/publish-capabilities': {'version': '2026-10-16-v1', 'platforms': {}}}
    if path in documents:
        return 200, json.dumps(documents[path]).encode(), 'application/json'
    return 404, json.dumps({'detail': '发布任务不存在'}).encode(), 'application/json'


def test_healthy_service_and_noninteractive_shapes():
    code, result = run_probe('http://127.0.0.1:7860', fetch=healthy)
    assert code == 0 and result['marker'] == 'HEALTHY'
    assert result['checks']['publication_queue_api'] == 'passed'


@pytest.mark.parametrize('failure,exit_code,marker', [
    (ServiceUnavailable('connection refused'), 20, 'SERVICE_UNAVAILABLE'),
    (RuntimeError('injected probe bug'), 30, 'PROBE_ERROR_MANUAL_REVIEW'),
])
def test_transport_and_probe_bugs_cannot_be_silently_accepted(failure, exit_code, marker):
    def fetch(*args):
        raise failure
    code, result = run_probe('http://127.0.0.1:7860', fetch=fetch)
    assert code == exit_code and result['marker'] == marker
    if exit_code == 30:
        assert result['requires_human_review']


@pytest.mark.parametrize('path,response', [
    ('/', (200, b'<html>not Easel</html>', 'text/html')),
    ('/assets/app.js', (404, b'missing', 'text/plain')),
    ('/api/accounts', (503, b'{}', 'application/json')),
    ('/api/account-execution', (200, b'null', 'application/json')),
    ('/api/publish-jobs', (200, b'{broken', 'application/json')),
    ('/api/publish-capabilities', (200, b'{"version":"old"}', 'application/json')),
])
def test_root_200_never_masks_broken_service_contracts(path, response):
    code, result = run_probe('http://127.0.0.1:7860', fetch=lambda base, target: response if target == path else healthy(base, target))
    assert code == 21 and result['marker'] == 'SERVICE_UNHEALTHY'


def test_invalid_probe_configuration_requires_human_review():
    code, result = run_probe('https://example.com', fetch=healthy)
    assert code == 30 and result['marker'] == 'PROBE_ERROR_MANUAL_REVIEW'
