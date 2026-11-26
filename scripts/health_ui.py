"""Read-only UI deployment check using in-browser synthetic account/task data.

No production rows are created, no real account is visited, and every non-GET
application request is rejected. The compiled application UI is exercised.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import tempfile
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check(base):
    from playwright.sync_api import sync_playwright, TimeoutError as UITimeout
    origin = urllib.parse.urlsplit(base)
    if origin.scheme != 'http' or origin.hostname not in {'localhost', '127.0.0.1'}:
        raise ValueError('UI probe only accepts local HTTP services')
    violations, page_errors = [], []
    snapshot = {'version': 1, 'account': 'health-mock', 'account_name': '模拟健康检查账号', 'platform': 'douyin',
        'capability_version': '2026-10-16-v1', 'capability': {'cover': 'after_upload', 'declaration': 'unconfirmed', 'automatic': False},
        'payload': {'title': '模拟健康检查任务', 'body': '仅用于界面检查，无真实平台发布', 'tags': '', 'media': []},
        'cover': {'status': 'unconfirmed'}, 'declaration': {'status': 'unconfirmed', 'note': '须在平台人工确认'}, 'files': []}
    fixture = {'id': 'health-ui-fixture', 'account': 'health-mock', 'idempotency_key': 'health-ui-only',
        'state': 'published', 'snapshot': snapshot, 'snapshot_hash': 'f' * 64, 'created': 0, 'updated': 0, 'attempts': 1,
        'events': [{'seq': 1, 'state': 'published', 'message': '模拟人工核对回执', 'created': 0}],
        'receipts': [{'seq': 1, 'status': 'published', 'submission': 'submitted', 'evidence': '模拟平台回执，仅用于界面检查', 'created': 0}],
        'receipt_revision': 1, 'outbox': [], 'retry_policy': {'can_retry': False, 'automatic_retry': False, 'next_action': 'done', 'reason': '禁止原任务重新提交'}}
    work = ROOT / 'tmp' / 'health-ui'
    work.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        # A fresh, project-local profile, never an account profile.
        profile = tempfile.mkdtemp(prefix='profile-', dir=work)
        context = playwright.chromium.launch_persistent_context(profile, channel='msedge', headless=True)
        try:
            page = context.pages[0]
            page.set_default_timeout(10000)
            page.add_init_script("localStorage.setItem('easel_onboarding_seen','1')")
            page.on('pageerror', lambda error: page_errors.append(str(error)))

            def route(request_route):
                request = request_route.request
                url = urllib.parse.urlsplit(request.url)
                if url.netloc != origin.netloc:
                    # Public fonts are also blocked; never contact any external service.
                    if url.hostname not in {'fonts.googleapis.com', 'fonts.gstatic.com'}:
                        violations.append('external_request')
                    return request_route.abort()
                path = url.path
                if request.method not in {'GET', 'HEAD'}:
                    violations.append('unexpected_mutation')
                    return request_route.abort()
                if '/whoami' in path or path.startswith(('/api/login/', '/api/publish/')) or (
                    path.startswith('/api/analytics/') and path != '/api/analytics/platforms'):
                    violations.append('automatic_account_access')
                    return request_route.abort()
                if path.startswith('/api/'):
                    data = []
                    if path == '/api/publish-jobs':
                        data = [fixture]
                    elif path == '/api/publish-jobs/health-ui-fixture':
                        data = fixture
                    elif path == '/api/status':
                        data = {'personas': [], 'runtime': 'codex', 'gateway': False}
                    elif path == '/api/settings/bootstrap':
                        data = {'modelConfigured': True}
                    elif path == '/api/trends':
                        data = {'trends': []}
                    return request_route.fulfill(status=200, content_type='application/json', body=json.dumps(data, ensure_ascii=False))
                return request_route.continue_()

            page.route('**/*', route)
            from web.health_probe import ServiceUnhealthy
            try:
                page.goto(base)
                page.get_by_text('账号管理', exact=True).first.click()
                page.get_by_role('button', name='操作记录', exact=True).click()
                dialog = page.get_by_role('dialog', name='账号操作记录')
                dialog.wait_for()
                dialog.get_by_role('button', name='关闭', exact=True).click()
                page.get_by_text('工作台', exact=True).first.click()
                page.get_by_text('去发布', exact=True).click()
                queue = page.get_by_role('region', name='持久化发布队列')
                queue.wait_for()
                queue.get_by_text('模拟健康检查账号 · 模拟健康检查任务', exact=True).wait_for()
                queue.get_by_role('button', name='详情与日志').click()
                detail = page.get_by_role('dialog', name='发布任务详情')
                detail.wait_for()
                detail.get_by_role('heading', name='平台回执（人工核对）', exact=True).wait_for()
                if '已发布（人工核对）' not in detail.inner_text() or '模拟平台回执' not in detail.inner_text():
                    raise ServiceUnhealthy('Receipt UI did not disclose manual confirmation source')
                page.wait_for_timeout(300)
                if violations or page_errors:
                    raise ServiceUnhealthy(f'UI violations={violations}; javascript_errors={len(page_errors)}')
            except UITimeout as error:
                raise ServiceUnhealthy(f'UI check failed: {error.message[:300]}') from error
            return {'account_page': 'passed_in_browser_mock', 'publish_page': 'passed_in_browser_mock',
                    'automatic_account_access': 0, 'operation_records_dialog': 'passed',
                    'publication_queue': 'passed_in_browser_mock', 'task_detail': 'passed_in_browser_mock',
                    'receipt_source': 'manual_confirmation_explicit', 'production_rows_written': 0}
        finally:
            context.close()


def main():
    from web.health_probe import ServiceUnhealthy, ServiceUnavailable
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:7860')
    args = parser.parse_args()
    try:
        result = {'marker': 'HEALTHY', 'checks': check(args.base)}
        code = 0
    except ServiceUnavailable as error:
        code, result = 20, {'marker': 'SERVICE_UNAVAILABLE', 'detail': str(error)}
    except ServiceUnhealthy as error:
        code, result = 21, {'marker': 'SERVICE_UNHEALTHY', 'detail': str(error)}
    except Exception as error:
        code, result = 30, {'marker': 'PROBE_ERROR_MANUAL_REVIEW', 'detail': f'{type(error).__name__}: {error}', 'requires_human_review': True}
    print(json.dumps(result, ensure_ascii=True))
    return code


if __name__ == '__main__':
    sys.exit(main())
