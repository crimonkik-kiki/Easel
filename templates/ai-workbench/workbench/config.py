"""Instance-local configuration. Public responses never include credentials."""
import copy
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from .harnesses.store import read_json, write_json

CHANNELS = ('chat', 'image', 'transcription', 'speech', 'video', 'music')
RUNTIMES = ('api', 'codex', 'opencode', 'acp', 'workbuddy')


def validate_url(value):
    if not value:
        return
    try:
        url = urlsplit(value)
        valid = url.scheme in ('http', 'https') and url.hostname and not (
            url.username or url.password or url.query or url.fragment)
        valid = valid and url.port != 0 and not any(c.isspace() or ord(c) < 32 for c in value)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError('请输入有效的 HTTP/HTTPS 服务地址，不要包含凭据或查询参数')


class Config:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.path = self.root / 'outputs/_config/settings.json'
        self.brand = read_json(self.root / 'workbench.json')

    def environment(self):
        env = {}
        path = self.root / '.env'
        if path.exists():
            for line in path.read_text(encoding='utf-8').splitlines():
                if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env[key.strip()] = value.strip().strip("\"'")
        env.update(os.environ)
        from .runtime_env import web_environment
        return web_environment(env)

    def read(self):
        data = read_json(self.path)
        env = self.environment()
        channels = {name: {'base_url': '', 'model': '', 'key': '', 'provider': 'api'} for name in CHANNELS}
        channels['image']['response_format'] = 'auto'
        channels['speech']['voice'] = 'alloy'
        channels['chat'].update(base_url=env.get('WORKBENCH_DIRECT_API_BASE_URL', ''),
                                model=env.get('WORKBENCH_DIRECT_API_MODEL', ''),
                                key=env.get('WORKBENCH_DIRECT_API_KEY', ''))
        for name, value in data.get('channels', {}).items():
            if name in channels:
                channels[name].update(value)
        return {'runtime': data.get('runtime', 'api'), 'sandbox': data.get('sandbox', 'workspace-write'),
                'models': data.get('models', {}),
                'system_prompt': data.get('system_prompt', '请清晰、准确地协助用户完成工作，缺少信息时先询问。'),
                'channels': channels}

    def public(self):
        data = copy.deepcopy(self.read())
        for channel in data['channels'].values():
            channel['key_configured'] = bool(channel.pop('key', ''))
        return data

    def save(self, body):
        if not isinstance(body, dict):
            raise ValueError('配置必须是对象')
        allowed = {'runtime', 'sandbox', 'system_prompt', 'channels', 'models'}
        if set(body) - allowed:
            raise ValueError('包含不支持的配置字段')
        data = self.read()
        data.update({key: body[key] for key in ('runtime', 'sandbox', 'system_prompt', 'models') if key in body})
        if data['runtime'] not in RUNTIMES or data['sandbox'] not in ('read-only', 'workspace-write'):
            raise ValueError('执行引擎或权限范围无效')
        if not isinstance(data['system_prompt'], str) or len(data['system_prompt']) > 12000:
            raise ValueError('助手指令过长')
        if not isinstance(data['models'], dict) or any(key not in RUNTIMES or not isinstance(value, str)
                or len(value) > 240 or any(ord(c) < 32 for c in value) for key, value in data['models'].items()):
            raise ValueError('原生模型覆盖格式无效')
        if data['models'].get('workbuddy'):
            raise ValueError('WorkBuddy的模型由桌面端选择，请清空其模型覆盖')
        if not isinstance(body.get('channels', {}), dict):
            raise ValueError('通道配置必须是对象')
        for name, changes in body.get('channels', {}).items():
            if name not in CHANNELS or not isinstance(changes, dict):
                raise ValueError('未知 AI 通道')
            if set(changes) - {'base_url', 'model', 'key', 'provider', 'clear_key', 'key_configured', 'voice', 'response_format'}:
                raise ValueError('通道字段无效')
            for key in ('base_url', 'model', 'provider', 'voice', 'response_format'):
                if key in changes:
                    value = changes[key]
                    if not isinstance(value, str) or len(value) > 1000 or any(ord(c) < 32 for c in value):
                        raise ValueError('通道配置格式无效')
                    data['channels'][name][key] = value.strip()
            value = changes.get('key', '')
            if not isinstance(value, str) or len(value) > 4000 or any(c.isspace() for c in value):
                raise ValueError('凭据格式无效')
            if changes.get('clear_key'):
                data['channels'][name]['key'] = ''
            elif value:
                data['channels'][name]['key'] = value
            validate_url(data['channels'][name]['base_url'])
            if data['channels'][name]['provider'] not in ('api', 'codex', 'extension'):
                raise ValueError('媒体供应商无效')
            if name != 'image' and data['channels'][name]['provider'] == 'codex':
                raise ValueError('Codex原生生图只能用于图片通道')
            if name == 'image' and data['channels'][name].get('response_format') not in ('auto', 'b64_json', 'url'):
                raise ValueError('图片响应格式无效')
        write_json(self.path, data)
        if os.name != 'nt':
            self.path.chmod(0o600)
        return self.public()

    def redact(self, text):
        for channel in self.read()['channels'].values():
            if channel['key']:
                text = text.replace(channel['key'], '[REDACTED]')
        for key, value in self.environment().items():
            if key.startswith('WORKBUDDY_') and value:
                text = text.replace(value, '[REDACTED]')
        return text[:20000]
