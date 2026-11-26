"""一次性完成 WorkBuddy OAuth 2.1 授权，并把三个配置值写进 .env。

它解决的问题：``WORKBUDDY_REFRESH_TOKEN`` 不能手工填写，只能走一次授权码流程换回来。
本脚本在本地起一个回环回调服务，引导浏览器授权，拿到 code 后换 token，
然后把 CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN 写进项目 .env。

前置条件
--------
1. 开放平台已完成开发者认证（个人认证即可）；
2. 已创建「硬件接入」类应用并提交审核，状态为**已启用**（审核中无法授权）；
3. 该应用已勾选 ``user.localassistant.readable`` 与 ``user.localassistant.invokable``；
4. 应用后台登记的 OAuth 回调地址与本脚本的 ``--redirect-uri`` **字节级一致**。

用法
----
    # 首次：把后台拿到的两个值传进来，脚本换取 refresh_token 并写入 .env
    .venv\\Scripts\\python.exe scripts/authorize_workbuddy.py ^
        --client-id app_xxx --client-secret sk_xxx

    # 换过机器 / .env 已有 client 凭据，只需重新授权
    .venv\\Scripts\\python.exe scripts/authorize_workbuddy.py --reauth

不打印任何凭据明文；写入 .env 的值不回显。
"""
from __future__ import annotations

import argparse
import json
import secrets
import string
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
TOKEN_PATH = ROOT / "outputs" / "_harness" / "workbuddy-token.json"

AUTHORIZE_URL = "https://www.workbuddy.cn/openapi/v2/authorize"
TOKEN_URL = "https://www.workbuddy.cn/openapi/v2/token"
DEFAULT_REDIRECT = "http://127.0.0.1:8799/oauth/callback"
SCOPES = "user.localassistant.readable user.localassistant.invokable"

KEYS = ("WORKBUDDY_CLIENT_ID", "WORKBUDDY_CLIENT_SECRET", "WORKBUDDY_REFRESH_TOKEN")


def read_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if not ENV_FILE.exists():
        return env
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def upsert_env(updates: dict[str, str]) -> None:
    """就地更新 .env；保留注释与其它键的顺序，只替换目标行。"""
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            output.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            output.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            output.append(line)
    missing = [key for key in updates if key not in seen]
    if missing:
        if output and output[-1].strip():
            output.append("")
        output.append("# ---- WorkBuddy 本地助理执行引擎 ----")
        output.extend(f"{key}={updates[key]}" for key in missing)
    temporary = ENV_FILE.with_suffix(".env.auth-tmp")
    temporary.write_text("\n".join(output) + "\n", encoding="utf-8")
    temporary.replace(ENV_FILE)


def random_state() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(24))


class Callback(BaseHTTPRequestHandler):
    captured: dict[str, str | None] = {}

    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        Callback.captured = {
            "code": (query.get("code") or [None])[0],
            "state": (query.get("state") or [None])[0],
            "error": (query.get("error") or [None])[0],
            "error_description": (query.get("error_description") or [None])[0],
        }
        body = (
            "<html><head><meta charset='utf-8'><title>WorkBuddy 授权</title></head>"
            "<body style=\"font-family:-apple-system,'Segoe UI',sans-serif;padding:56px;"
            "background:#fafafa;color:#27272a\">"
            "<h2 style='font-weight:600'>授权完成</h2>"
            "<p style='color:#52525b'>可以关闭本页面，回到命令行查看结果。</p>"
            "</body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def wait_for_code(redirect_uri: str, state: str, timeout: int = 300) -> str:
    parsed = urllib.parse.urlparse(redirect_uri)
    if parsed.scheme != "http":
        raise SystemExit(
            f"[错误] 回调地址必须是 http，当前为 {parsed.scheme}。\n"
            f"       请在开放平台登记 http://127.0.0.1:<端口>/oauth/callback 这类本地回环地址。")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80

    Callback.captured = {}
    server = HTTPServer((host, port), Callback)
    server.timeout = 1
    threading.Thread(target=_serve, args=(server,), daemon=True).start()
    print(f"[等待] 本地回调监听 http://{host}:{port}{parsed.path}")
    print(f"[等待] 如浏览器未自动打开，请手动访问上面给出的授权链接（{timeout}s 内有效）")

    deadline = time.time() + timeout
    while time.time() < deadline:
        server.handle_request()
        if Callback.captured.get("code") or Callback.captured.get("error"):
            break
    server.server_close()

    captured = Callback.captured
    if captured.get("error"):
        raise SystemExit(
            f"[失败] 授权页返回错误：{captured.get('error')} - {captured.get('error_description')}\n"
            f"       → 常见原因：应用仍在审核中（需「已启用」）、回调地址与后台登记不一致、"
            f"或应用未勾选本地助理 Scope")
    if not captured.get("code"):
        raise SystemExit("[失败] 等待授权超时，未收到授权码")
    if captured.get("state") != state:
        raise SystemExit("[失败] state 校验不通过，可能是回调地址不匹配或授权被中断")
    return captured["code"]


def _serve(server: HTTPServer):
    while True:
        try:
            server.handle_request()
        except Exception:
            break


def post_form(url: str, fields: dict[str, str]) -> dict:
    data = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        detail = body[:300]
        try:
            payload = json.loads(body)
            detail = str(payload.get("error") or payload.get("message") or detail)
        except ValueError:
            pass
        raise SystemExit(
            f"[失败] 换取凭证失败 HTTP {error.code}：{detail}\n"
            f"       → 核对 client_secret；确认回调地址与授权阶段完全一致；"
            f"授权码一次性、有效期 10 分钟") from error
    except urllib.error.URLError as error:
        raise SystemExit(f"[失败] 网络不可达：{error.reason}") from error


def main() -> int:
    parser = argparse.ArgumentParser(description="WorkBuddy OAuth 2.1 授权并写入 .env")
    parser.add_argument("--client-id")
    parser.add_argument("--client-secret")
    parser.add_argument("--redirect-uri", default=DEFAULT_REDIRECT,
                        help=f"必须与开放平台登记值一致，默认 {DEFAULT_REDIRECT}")
    parser.add_argument("--reauth", action="store_true",
                        help="复用 .env 中已有的 client 凭据，只重新授权")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    print("=" * 66)
    print("WorkBuddy OAuth 2.1 授权")
    print("=" * 66)

    env = read_env()
    client_id = (args.client_id or env.get("WORKBUDDY_CLIENT_ID") or "").strip()
    client_secret = (args.client_secret or env.get("WORKBUDDY_CLIENT_SECRET") or "").strip()

    if args.reauth and env.get("WORKBUDDY_CLIENT_ID") != client_id:
        pass
    if not client_id or not client_secret:
        print("\n[阻塞] 缺少 client_id / client_secret。")
        print("       取得位置：open.workbuddy.cn/console → 硬件接入 → 应用详情")
        print("       client_secret 只在创建成功时明文展示一次，遗失需联系平台。")
        return 2

    print(f"\n[1/4] 应用凭据")
    print(f"      client_id     {client_id[:10]}…")
    print(f"      client_secret 已设置（{len(client_secret)} 字符）")
    print(f"      redirect_uri  {args.redirect_uri}")
    print(f"      scope         {SCOPES}")

    print("\n[2/4] 打开授权页")
    state = random_state()
    query = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": args.redirect_uri,
        "scope": SCOPES,
        "state": state,
    })
    url = f"{AUTHORIZE_URL}?{query}"
    print(f"      {url}")
    try:
        webbrowser.open(url)
    except Exception:
        print("      （无法自动打开浏览器，请手动复制上面的链接）")

    code = wait_for_code(args.redirect_uri, state, args.timeout)
    print(f"      [完成] 收到授权码 {code[:10]}…")

    print("\n[3/4] 换取 refresh_token")
    payload = post_form(TOKEN_URL, {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": args.redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    })
    access = payload.get("access_token", "")
    refresh = payload.get("refresh_token", "")
    granted = str(payload.get("scope", ""))
    if not access or not refresh:
        print(f"      [失败] 响应缺少 access_token 或 refresh_token：{list(payload)}")
        return 2
    print(f"      access_token  已取得（{payload.get('expires_in')} 秒有效）")
    print(f"      refresh_token 已取得")
    print(f"      实际授予 scope：{granted or '（响应未返回）'}")

    missing = [scope for scope in SCOPES.split() if scope not in granted.split()]
    if granted and missing:
        print(f"\n[警告] 以下 Scope 未授予：{', '.join(missing)}")
        print("       → 应用后台的「权限管理信息」没勾选这两项，或审核未通过。")
        print("         本地助理接口会返回 403 insufficient_scope，请先补齐权限再授权。")

    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps({
        "access_token": access,
        "refresh_token": refresh,
        "expires_at": int(time.time()) + int(payload.get("expires_in") or 3600),
        "scope": granted,
        "open_id": payload.get("open_id", ""),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        TOKEN_PATH.chmod(0o600)
    except OSError:
        pass

    print("\n[4/4] 写入 .env")
    upsert_env({
        "WORKBUDDY_CLIENT_ID": client_id,
        "WORKBUDDY_CLIENT_SECRET": client_secret,
        "WORKBUDDY_REFRESH_TOKEN": refresh,
    })
    print(f"      已写入 {ENV_FILE.name}（三个键，值不回显）")
    print(f"      token 缓存 {TOKEN_PATH.relative_to(ROOT)}")

    print("\n下一步：")
    print("      .venv\\Scripts\\python.exe scripts/check_workbuddy.py --send \"只回复 OK\"")
    print("      通过后到 Web「设置 → 模型配置 → 对话 → 执行引擎」选择 WorkBuddy 本地助理")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
