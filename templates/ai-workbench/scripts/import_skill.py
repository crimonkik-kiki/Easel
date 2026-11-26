"""Explicitly import a skill from a trusted source. Never execute/install it."""
import argparse
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'.env', '.git', '.venv', 'node_modules', '__pycache__', 'outputs', 'cookies', '_login', '.DS_Store'}


def import_skill(source, name):
    if not name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in name):
        raise ValueError('技能名无效')
    directory = Path(source).resolve() / 'skills/builtin' / name
    if not (directory / 'SKILL.md').is_file():
        raise ValueError('找不到技能目录与SKILL.md')
    target = ROOT / 'skills/builtin' / name
    if target.exists():
        raise ValueError('技能已存在，不会覆盖')
    for path in directory.rglob('*'):
        if path.is_symlink():
            raise ValueError('导入目录含符号链接，请先人工整理')
    shutil.copytree(directory, target, ignore=lambda _, names: [n for n in names if n in EXCLUDED or n.startswith('.env.') or n.endswith(('.pyc', '.log', '.pem', '.key'))])
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, help='Trusted Easel/project root')
    parser.add_argument('--name', required=True)
    args = parser.parse_args()
    print(import_skill(args.source, args.name))
    print('已复制；未安装依赖、未执行脚本。请检查SKILL.md引用与共享脚本依赖。')
