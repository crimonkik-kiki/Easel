import importlib.util
import json
from pathlib import Path

import pytest
from web.health_probe import ServiceUnhealthy

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('clipify_release_probe',ROOT/'scripts/clipify_release_health.py')
health=importlib.util.module_from_spec(spec);spec.loader.exec_module(health)


def fetcher(changes=None):
    values={'/':(200,b'<script src="/assets/index-abc.js"></script>','text/html'),
        '/api/accounts':[], '/api/outputs':[], '/api/clipify/tasks':[], '/api/clipify/check':{'ready':True}}
    values.update(changes or {})
    def fetch(base,path):
        if path=='/api/operations/accounts':return 404,b'{}','application/json'
        value=values[path]
        if isinstance(value,tuple):return value
        return 200,json.dumps(value).encode(),'application/json'
    return fetch


def test_probe_distinguishes_service_fault_from_probe_configuration_error(tmp_path):
    (tmp_path/'index.html').write_text('<script src="/assets/index-abc.js"></script>')
    assert health.evaluate(tmp_path,fetcher())['marker']=='HEALTHY'
    with pytest.raises(ServiceUnhealthy):health.evaluate(tmp_path,fetcher({'/api/clipify/check':{'ready':False}}))
    with pytest.raises(ServiceUnhealthy):health.evaluate(tmp_path,fetcher({'/api/outputs':(200,b'broken','application/json')}))
    (tmp_path/'index.html').write_text('bad build')
    with pytest.raises(ValueError):health.evaluate(tmp_path,fetcher())
