"""Create a portable source + built-UI ZIP; exclude every instance's data."""
import argparse
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'.env', '.venv', '.git', 'outputs', 'node_modules', '__pycache__', '.pytest_cache', 'release', '.codex', '.claude', '.workbuddy', '.aws', '.ssh', 'build'}


def package(destination):
    target = Path(destination).resolve()
    if not (ROOT / 'frontend/dist/index.html').is_file():
        raise ValueError('请先构建前端；发布包必须可以直接启动')
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(ROOT.rglob('*')):
            relative = file.relative_to(ROOT)
            if not file.is_file() or file == target or any(p in EXCLUDED or p.endswith('.egg-info') for p in relative.parts):
                continue
            if file.is_symlink() or file.name.endswith(('.pyc', '.tsbuildinfo', '.log')) or (file.name.startswith('.env.') and file.name != '.env.example'):
                continue
            archive.write(file, 'ai-workbench/' + relative.as_posix())
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=str(ROOT / 'release/ai-workbench-template-v0.3.0.zip'))
    args = parser.parse_args()
    print(package(args.output))
