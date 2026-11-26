"""Copy the clean scaffold into a NEW directory; never copy credentials/data."""
import argparse
import json
from pathlib import Path
import shutil
import uuid

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'.env', '.venv', '.git', 'outputs', 'node_modules', '__pycache__', '.pytest_cache', 'release', '.codex', '.claude', '.workbuddy', '.aws', '.ssh', 'build'}


def create(destination, name, port):
    target = Path(destination).expanduser().resolve()
    if target.exists():
        raise ValueError('目标目录已存在，拒绝覆盖。请选择一个新的目录。')
    if target.is_relative_to(ROOT):
        raise ValueError('新工作台不能创建在模板内部')
    if not name.strip() or not 1024 <= port <= 65535:
        raise ValueError('名称或端口无效')

    def ignore(directory, names):
        return [n for n in names if n in EXCLUDED or n.endswith(('.pyc', '.tsbuildinfo', '.log', '.egg-info')) or (n.startswith('.env.') and n != '.env.example')]
    shutil.copytree(ROOT, target, ignore=ignore)
    brand = json.loads((target / 'workbench.json').read_text(encoding='utf-8'))
    brand.update(id='workbench-' + uuid.uuid4().hex[:12], name=name.strip(), port=port)
    (target / 'workbench.json').write_text(json.dumps(brand, ensure_ascii=False, indent=2), encoding='utf-8')
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination')
    parser.add_argument('--name', required=True)
    parser.add_argument('--port', type=int, default=7871)
    args = parser.parse_args()
    try:
        print(create(args.destination, args.name, args.port))
    except ValueError as error:
        parser.exit(1, str(error) + '\n')
