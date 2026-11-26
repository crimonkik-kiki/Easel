"""WorkBuddy 本地助理底座：端到端连通性验证。

回答一个问题：现在把 Easel 的「执行引擎」切成 WorkBuddy，能不能真的跑一轮对话。

只做只读探测，不发布内容、不写 outputs、不打印任何凭据明文。

用法：
    .venv\\Scripts\\python.exe scripts/check_workbuddy.py
    .venv\\Scripts\\python.exe scripts/check_workbuddy.py --send "只回复 OK"

凭据来源（按优先级）：
    进程环境变量  >  项目 .env
    WORKBUDDY_CLIENT_ID / WORKBUDDY_CLIENT_SECRET / WORKBUDDY_REFRESH_TOKEN
    可选 WORKBUDDY_OPENAPI_BASE 覆盖服务地址
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TOKEN_PATH = ROOT / "outputs" / "_harness" / "workbuddy-token.json"
SCOPES = "user.localassistant.readable user.localassistant.invokable"


def load_env() -> dict[str, str]:
    env = dict(**__import__("os").environ)
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return env


def mask(value: str) -> str:
    if not value:
        return "（空）"
    return f"{value[:6]}…{value[-4:]}" if len(value) > 12 else "已设置"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", help="向本地助理发一条测试消息并等待回复")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    print("=" * 66)
    print("WorkBuddy 本地助理 · 端到端验证")
    print("=" * 66)

    env = load_env()
    client_id = (env.get("WORKBUDDY_CLIENT_ID") or "").strip()
    client_secret = (env.get("WORKBUDDY_CLIENT_SECRET") or "").strip()
    refresh = (env.get("WORKBUDDY_REFRESH_TOKEN") or "").strip()

    print("\n[1/5] 凭据检查")
    rows = [("WORKBUDDY_CLIENT_ID", client_id), ("WORKBUDDY_CLIENT_SECRET", client_secret),
            ("WORKBUDDY_REFRESH_TOKEN", refresh)]
    missing = [name for name, value in rows if not value]
    for name, value in rows:
        print(f"      {name:26} {mask(value)}")
    if TOKEN_PATH.exists():
        try:
            cached = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
            left = int(cached.get("expires_at", 0)) - int(time.time())
            print(f"      {'本地 token 缓存':26} 存在，{'仍有效 %ds' % left if left > 0 else '已过期，将自动刷新'}")
        except (OSError, ValueError):
            print(f"      {'本地 token 缓存':26} 存在但无法解析")
    if missing and not TOKEN_PATH.exists():
        print(f"\n[阻塞] 缺少 {', '.join(missing)}")
        print("       取得方式：开放平台 → 「硬件接入」类应用 → 应用详情")
        print("       注意：积分兑换类应用不开放本地助理权限")
        return 2

    # 复用适配器自身的客户端，避免验证逻辑和运行逻辑两套实现漂移。
    from easel.harnesses.workbuddy import _Client

    settings = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh,
        "base": (env.get("WORKBUDDY_OPENAPI_BASE") or "https://www.workbuddy.cn/openapi/v2").rstrip("/"),
        "cwd": str(ROOT),
    }
    client = _Client(settings, ROOT)

    print("\n[2/5] 换取 access_token")
    try:
        token = await client.access_token()
    except Exception as error:
        print(f"      [失败] {error}")
        print("       → 到 open.workbuddy.cn 核对 client_id / client_secret，或重新授权")
        return 2
    print(f"      成功，access_token = {mask(token)}")

    print("\n[3/5] 查询本机 WorkBuddy 是否在线")
    try:
        online = await client.online(token)
    except Exception as error:
        print(f"      [失败] {error}")
        return 2
    print(f"      online = {online}")
    if not online:
        print("      → 请打开 WorkBuddy 桌面端并确认已登录，再重试")
        return 2

    print("\n[4/5] Scope 与消息通道")
    if not args.send:
        print("      在线即可调用；如需验证真实往返，加 --send \"只回复 OK\"")
    else:
        def emit(kind, text):
            if kind == "activity":
                print(f"      … {text}")
        try:
            message_id = await client.send(token, args.send)
            print(f"      已提交，message_id = {message_id}")
            reply = await client.await_reply(token, message_id, args.timeout, emit)
        except Exception as error:
            print(f"      [失败] {error}")
            return 2
        print(f"      回复：{reply.strip()[:400]}")

    print("\n[5/5] 结论")
    print("      底座可用。在 Web「设置 → 模型配置 → 对话 → 执行引擎」选择")
    print("      「WorkBuddy 本地助理」，保存后新建对话即可。")
    print(f"      所需 Scope：{SCOPES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
