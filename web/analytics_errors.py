"""Bounded collection diagnostics without storing browser arguments or credentials."""
import re


def safe_detail(value):
    text = str(value)
    text = re.sub(r'(?i)\bBearer\s+\S+', '[凭据已隐藏]', text)
    text = re.sub(r'https?://[^\s<>"\']+', '[链接已隐藏]', text)
    text = re.sub(r'(?i)\b[A-Z]:[\\/][^\r\n<>"\']+', '[路径已隐藏]', text)
    text = re.sub(r'(?i)\b(?:token|cookie|authorization|password|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+', '[凭据已隐藏]', text)
    return text.replace('\r', ' ').replace('\n', ' ')[:240]


def collector_failure(stderr):
    text = str(stderr or '')
    if re.search(r"Executable doesn't exist|executable.*not found|browser.*not.*installed", text, re.I):
        return '[BROWSER_MISSING] 取数所需浏览器未安装或路径不匹配；请检查工作台浏览器配置'
    if re.search(r'ProcessSingleton|user data directory is already in use|profile.*in use|exitCode=21', text, re.I):
        return '[PROFILE_BUSY] 账号浏览器目录被占用；请关闭该账号后台窗口后再同步'
    if re.search(r'net::ERR_|ERR_PROXY_CONNECTION_FAILED|ERR_TUNNEL_CONNECTION_FAILED', text):
        return '[NETWORK_ERROR] 创作者后台连接失败；请检查当前系统网络或账号网络设置'
    if re.search(r'Target.*closed|browser.*closed|context.*closed', text, re.I):
        return '[BROWSER_CLOSED] 取数浏览器提前关闭；请检查浏览器与账号登录所用内核是否一致'
    if re.search(r'Page.goto: Timeout|Navigation.*timeout', text, re.I):
        return '[PAGE_TIMEOUT] 创作者后台加载超时，本次没有更新数据'
    first = next((line.removeprefix('ERROR:').strip() for line in text.splitlines() if line.startswith('ERROR:')), '')
    if not first:
        first = next((line.strip() for line in text.splitlines() if line.strip()), '未取到数据')
    return safe_detail(first)
