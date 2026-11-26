"""Apply an account-specific browser network policy supplied by the workbench."""
import os


def browser_options(options: dict) -> dict:
    mode = os.environ.get('EASEL_ACCOUNT_PROXY_MODE', 'inherit')
    if mode == 'inherit':
        return options
    options = dict(options)
    options['args'] = [arg for arg in options.get('args', []) if arg != '--no-proxy-server']
    options.pop('proxy', None)
    if mode == 'direct':
        options['args'].append('--no-proxy-server')
    elif mode == 'fixed':
        server = os.environ.get('EASEL_ACCOUNT_PROXY_URL', '')
        if not server:
            raise ValueError('账号代理地址未配置')
        options['proxy'] = {'server': server}
    elif mode != 'system':
        raise ValueError('未知账号网络模式')
    return options
