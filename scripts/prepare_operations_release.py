"""Save tested sources, current dist, and a narrowly reconstructed pre-feature rollback."""
from pathlib import Path
import ast
import hashlib
import json
import re
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
release = ROOT / 'tmp' / ('operations-release-' + time.strftime('%Y%m%d-%H%M%S'))
rollback = release / 'rollback'
tested = release / 'tested'
paths = ['web/app.py', 'skills/shared/scripts/account_stats.py', 'skills/shared/scripts/weixin_mp_stats.py',
         'web/frontend/src/components/DashboardPage.tsx', 'web/frontend/src/components/Sidebar.tsx',
         'web/frontend/src/lib/api.ts']
new_paths = ['web/operations.py', 'web/operations_api.py',
             'web/frontend/src/components/OperationsAnalytics.tsx', 'web/frontend/src/styles/operations.css']
for relative in paths + new_paths:
    target = tested / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / relative, target)
for relative in paths:
    target = rollback / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / relative, target)


def function_text(source, name):
    lines = source.splitlines(keepends=True)
    node = next(n for n in ast.parse(source).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    return ''.join(lines[node.lineno-1:node.end_lineno])


app_file = rollback / 'web/app.py'
app = app_file.read_text(encoding='utf-8')
previous = (ROOT / 'tmp/restore-1105/candidate/web/app.py').read_text(encoding='utf-8')
for name in ('api_analytics', '_fetch_analytics'):
    app = app.replace(function_text(app, name), function_text(previous, name), 1)
guard = re.compile(r'    if (key|platform) in _ANALYTICS_BUSY or \(\1 in _analytics_inflight and not _analytics_inflight\[\1\]\.done\(\)\):\n        raise HTTPException\(409, "该账号正在同步创作数据，请等待完成"\)\n')
app, count = guard.subn('', app)
assert count == 5, count
app = app.replace('_ANALYTICS_BUSY: set[str] = set()\n', '')
app = app.replace('from web.operations_api import register_operations\nregister_operations(app, lambda: globals())\n', '')
compile(app, 'rollback-web-app.py', 'exec')
app_file.write_text(app, encoding='utf-8')

dashboard = subprocess.check_output(['git', 'show', 'HEAD:web/frontend/src/components/DashboardPage.tsx'], cwd=ROOT)
(rollback / paths[3]).write_bytes(dashboard)
shutil.copy2(ROOT / 'tmp/operations-source-before/Sidebar.tsx', rollback / paths[4])
api = (rollback / paths[5]).read_text(encoding='utf-8')
api, count = re.subn(r'export interface OperationsAccount \{.*?\$\{BASE\}/api/operations/export\?account=.*?;\n', '', api, count=1, flags=re.S)
assert count == 1
(rollback / paths[5]).write_text(api, encoding='utf-8')

stats = rollback / paths[1]
source = stats.read_text(encoding='utf-8')
source = source.replace('ANALYTICS_DIR = Path(os.environ.get("EASEL_ANALYTICS_DIR", str(PROJECT_ROOT / "outputs" / "_analytics")))', 'ANALYTICS_DIR = PROJECT_ROOT / "outputs" / "_analytics"')
source = source.replace('history = [] if os.environ.get("EASEL_ANALYTICS_NO_HISTORY") == "1" else load_history(a.platform)', 'history = load_history(a.platform)')
source = source.replace('if os.environ.get("EASEL_ANALYTICS_NO_HISTORY") != "1" and s["logged_in"]', 'if s["logged_in"]')
stats.write_text(source, encoding='utf-8')
mp = rollback / paths[2]
source = mp.read_text(encoding='utf-8').replace('history = [] if os.environ.get("EASEL_ANALYTICS_NO_HISTORY") == "1" else account_stats.load_history("wechat-oa")', 'history = account_stats.load_history("wechat-oa")')
source = source.replace('if os.environ.get("EASEL_ANALYTICS_NO_HISTORY") != "1" and not result.get("error")', 'if not result.get("error")')
mp.write_text(source, encoding='utf-8')
for relative in paths[:3]:
    compile((rollback / relative).read_text(encoding='utf-8'), relative, 'exec')
shutil.copytree(ROOT / 'web/frontend/dist', rollback / 'dist')
manifest = {'release': str(release), 'rollback_paths': paths,
            'rollback_method': 'Reverse only operations additions; original dashboard from HEAD, sidebar from before scoped edit; other account/publish changes preserved.',
            'tested_sha256': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths + new_paths}}
(release / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
(ROOT / 'tmp/operations-current-release.txt').write_text(str(release), encoding='utf-8')
print(json.dumps({'release': str(release), 'rollback_files': len(paths), 'dist_backup': True}, ensure_ascii=False))
