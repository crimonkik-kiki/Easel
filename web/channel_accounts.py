"""Local video-channel account names and selection; browser secrets stay in profiles."""
import json
import re
import uuid
from pathlib import Path

DEFAULT = 'weixin-channels'


def valid_key(key: str) -> bool:
    return key == DEFAULT or bool(re.fullmatch(r'weixin-channels--[a-f0-9]{16}', key))


def read(root: Path) -> dict:
    file = root / '_accounts' / 'channels.json'
    if not file.exists():
        return {'active': DEFAULT, 'accounts': [{'key': DEFAULT, 'label': '默认视频号'}]}
    data = json.loads(file.read_text(encoding='utf-8'))
    accounts = data.get('accounts', [])
    if (not accounts or any(not valid_key(item.get('key', '')) for item in accounts)
            or len({item['key'] for item in accounts}) != len(accounts)
            or DEFAULT not in {item['key'] for item in accounts}):
        raise ValueError('视频号账号配置损坏，请检查 outputs/_accounts/channels.json')
    if data.get('active') not in {item['key'] for item in accounts}:
        data['active'] = DEFAULT
    return data


def save(root: Path, data: dict) -> None:
    folder = root / '_accounts'
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / ('channels-' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(folder / 'channels.json')


def profile_base(root: Path, key: str) -> Path:
    if not valid_key(key) or key == DEFAULT:
        raise ValueError('无效的新账号标识')
    return root.parent / '.easel-channel-profiles' / key
