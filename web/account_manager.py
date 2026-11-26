"""Account metadata only; browser profiles and credentials remain isolated."""
import json
import re
import uuid
from pathlib import Path

MULTI = ('xiaohongshu', 'douyin', 'kuaishou', 'weixin-channels', 'zhihu')


def read(root: Path) -> dict:
    file = root / '_accounts' / 'manager.json'
    if not file.exists():
        return {'accounts': [], 'metadata': {}, 'active': {}}
    data = json.loads(file.read_text(encoding='utf-8'))
    for item in data['accounts']:
        if item['base'] not in MULTI or not re.fullmatch(re.escape(item['base']) + r'--[a-f0-9]{16}', item['key']):
            raise ValueError('账号配置包含无效标识')
    return data


def save(root: Path, data: dict) -> None:
    folder = root / '_accounts'
    folder.mkdir(parents=True, exist_ok=True)
    temp = folder / ('manager-' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(folder / 'manager.json')
