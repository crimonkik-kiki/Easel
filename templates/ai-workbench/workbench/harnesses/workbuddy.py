"""WorkBuddy 官方 Open API「本地助理」执行底座。

为什么走这条路线
----------------
WorkBuddy 桌面端安装包里带了一个能说 ACP 的 CLI（``cli/bin/codebuddy --acp``），
协议握手与建会话都通，但它与桌面端自己的 prewarm 进程池共用同一个本地端口和
单例标记：桌面端开着时再起一个实例会拿不到端口、或占不到单例而卡住不应答。
因此「复用桌面登录态」的嵌入式路线在桌面端运行期间不可用。

官方给第三方留的入口是 Open API 的本地助理能力域：走 HTTPS，由云端网关转发到
用户 PC 端已连接的 WorkBuddy，不抢占桌面端的本地资源，也不依赖 CLI 版本。

前置条件（缺一不可）
--------------------
1. 开放平台已启用一个「硬件接入」类应用（积分兑换类不开放本地助理权限）；
2. 该应用勾选并通过 ``user.localassistant.readable`` 与 ``user.localassistant.invokable``；
3. 完成一次 OAuth 2.1 授权，取得 refresh_token。

配置方式（写在项目 .env 或进程环境变量）
----------------------------------------
``WORKBUDDY_CLIENT_ID`` / ``WORKBUDDY_CLIENT_SECRET`` / ``WORKBUDDY_REFRESH_TOKEN``
可选 ``WORKBUDDY_OPENAPI_BASE`` 覆盖服务地址（默认官方 www.workbuddy.cn）。

能力边界（如实声明，不假装对等）
--------------------------------
* 本地助理接口没有 token 级流式输出，只能拿到整段回复，因此本适配器按段落回填；
* 没有独立的会话 ID：消息进入用户桌面端当前会话，AI Workbench 无法隔离出私有原生会话，
  所以与其它底座之间不共享历史，也不支持按原生 ID 续接；
* 不支持在 AI Workbench 侧切换模型（桌面端自己决定），设置模型覆盖会明确报错；
* 工具权限由桌面端自己弹窗确认，AI Workbench 的 ``ask`` 通道本轮不参与。

真实效果以 ``python scripts/check_workbuddy.py`` 的端到端往返为准。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

from .base import Descriptor, HarnessError, RunRequest
from .store import read_json, write_json
from .workspace import harness_instructions

DEFAULT_BASE = "https://www.workbuddy.cn/openapi/v2"
SCOPE_HINT = "user.localassistant.readable user.localassistant.invokable"

# 轮询间隔与上限：本地助理是「发消息 -> 拉历史」的模型，没有推送。
POLL_INTERVAL = 1.0
POLL_MAX_SECONDS = 600

TOKEN_FILE = "workbuddy-token.json"


class WorkBuddyAdapter:
    descriptor = Descriptor(
        "workbuddy",
        "WorkBuddy 本地助理",
        "Open API（HTTPS）",
        "在 .env 配置 WORKBUDDY_CLIENT_ID / WORKBUDDY_CLIENT_SECRET / WORKBUDDY_REFRESH_TOKEN",
    )

    async def run(self, request: RunRequest, emit, ask, bind):
        if request.model:
            raise HarnessError(
                "WorkBuddy 本地助理不支持在 AI Workbench 侧切换模型，请清空模型覆盖，"
                "由桌面端自行决定模型")

        settings = _read_settings(request)
        client = _Client(settings, request.cwd)
        token = await client.access_token()

        online = await client.online(token)
        if not online:
            raise HarnessError(
                "本机 WorkBuddy 桌面端未连接到开放平台：请打开客户端并确认已登录，"
                "然后在授权页完成一次 OAuth 授权")

        prompt = harness_instructions(request) + "\n\n" + request.prompt
        emit("activity", "已提交给本机 WorkBuddy 执行…")
        message_id = await client.send(token, prompt)

        emit("activity", "等待本机执行结果…")
        reply = await client.await_reply(token, message_id, request.timeout, emit)
        if not reply:
            raise HarnessError("WorkBuddy 本轮没有返回内容，请在桌面端确认任务是否仍在执行")

        for chunk in _segments(reply):
            emit("token", chunk)

        # 本地助理没有会话 ID；绑定空串表示「无原生历史可续接」。
        bind("")

    # 说明面板用：不联网，只看凭据是否齐备。
    @staticmethod
    def configured(env: dict[str, str], outputs: Path) -> bool:
        if env.get("WORKBUDDY_CLIENT_ID") and env.get("WORKBUDDY_CLIENT_SECRET"):
            if env.get("WORKBUDDY_REFRESH_TOKEN"):
                return True
            cached = read_json(outputs / "_harness" / TOKEN_FILE)
            if cached.get("refresh_token") or cached.get("access_token"):
                return True
        return False


def _read_settings(request: RunRequest) -> dict[str, str]:
    env = request.env or {}
    client_id = (env.get("WORKBUDDY_CLIENT_ID") or "").strip()
    client_secret = (env.get("WORKBUDDY_CLIENT_SECRET") or "").strip()
    refresh = (env.get("WORKBUDDY_REFRESH_TOKEN") or "").strip()
    base = (env.get("WORKBUDDY_OPENAPI_BASE") or DEFAULT_BASE).strip().rstrip("/")

    cached = read_json(request.cwd / "outputs" / "_harness" / TOKEN_FILE)

    if not client_id or not client_secret:
        raise HarnessError(
            "WorkBuddy 尚未配置：缺少 WORKBUDDY_CLIENT_ID / WORKBUDDY_CLIENT_SECRET。"
            "请在开放平台启用的「硬件接入」应用详情中取得后写入 .env")
    if not refresh and not cached.get("refresh_token") and not cached.get("access_token"):
        raise HarnessError(
            "WorkBuddy 尚未授权：缺少 WORKBUDDY_REFRESH_TOKEN。"
            "请先完成 OAuth 授权（scope 需包含 %s），再运行 scripts/check_workbuddy.py" % SCOPE_HINT)
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh or cached.get("refresh_token", ""),
        "base": base,
        "cwd": str(request.cwd),
    }


def _segments(text: str, size: int = 24) -> list[str]:
    """按可见长度切段，让前端有流式观感（接口本身不流式）。"""
    if len(text) <= size:
        return [text]
    pieces, buffer = [], ""
    for character in text:
        buffer += character
        if len(buffer) >= size or character in "。！？\n":
            pieces.append(buffer)
            buffer = ""
    if buffer:
        pieces.append(buffer)
    return pieces


class _Client:
    def __init__(self, settings: dict[str, str], root: Path):
        self.settings = settings
        self.root = root
        self.base = settings["base"]
        self.token_path = root / "outputs" / "_harness" / TOKEN_FILE

    # ---------------------------------------------------------------- token

    async def access_token(self) -> str:
        cached = read_json(self.token_path)
        token = cached.get("access_token", "")
        expires_at = cached.get("expires_at", 0)
        if token and isinstance(expires_at, (int, float)) and expires_at - 60 > time.time():
            return token
        return await self._refresh(cached.get("refresh_token") or self.settings["refresh_token"])

    async def _refresh(self, refresh_token: str) -> str:
        if not refresh_token:
            raise HarnessError("WorkBuddy 授权已失效且没有 refresh_token，请重新完成 OAuth 授权")
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.settings["client_id"],
            "client_secret": self.settings["client_secret"],
        }
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.post(f"{self.base}/token", data=payload)
            except httpx.HTTPError as error:
                raise HarnessError(f"刷新 WorkBuddy 凭证失败（网络）：{type(error).__name__}") from error
        if response.status_code != 200:
            raise HarnessError(
                "刷新 WorkBuddy 凭证失败：%s。请确认 client_secret 正确，"
                "或重新完成一次 OAuth 授权" % _describe(response))
        data = _json(response)
        access = data.get("access_token", "")
        if not access:
            raise HarnessError("WorkBuddy 换发凭证的响应里没有 access_token")
        expires_in = data.get("expires_in") or 3600
        try:
            expires_in = int(expires_in)
        except (TypeError, ValueError):
            expires_in = 3600
        write_json(self.token_path, {
            "access_token": access,
            "refresh_token": data.get("refresh_token") or refresh_token,
            "expires_at": int(time.time()) + expires_in,
            "scope": data.get("scope", ""),
            "open_id": data.get("open_id", ""),
        })
        _chmod_private(self.token_path)
        return access

    # ----------------------------------------------------------- endpoints

    async def online(self, token: str) -> bool:
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.get(
                    f"{self.base}/localassistant",
                    headers={"Authorization": f"Bearer {token}"})
            except httpx.HTTPError as error:
                raise HarnessError(f"查询 WorkBuddy 本地助理状态失败（网络）：{type(error).__name__}") from error
        if response.status_code != 200:
            raise HarnessError(_failure(response, "查询本地助理在线状态"))
        return bool((_json(response).get("data") or {}).get("online"))

    async def send(self, token: str, content: str) -> str:
        async with httpx.AsyncClient(timeout=60) as client:
            try:
                response = await client.post(
                    f"{self.base}/localassistant/message",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"content": content, "msg_type": "text"})
            except httpx.HTTPError as error:
                raise HarnessError(f"向 WorkBuddy 发送消息失败（网络）：{type(error).__name__}") from error
        if response.status_code != 200:
            raise HarnessError(_failure(response, "发送消息给本地助理"))
        message_id = (_json(response).get("data") or {}).get("message_id", "")
        if not message_id:
            raise HarnessError("WorkBuddy 未返回消息 ID，无法追踪回复")
        return message_id

    async def await_reply(self, token: str, message_id: str, timeout: int, emit) -> str:
        deadline = time.monotonic() + min(timeout or POLL_MAX_SECONDS, POLL_MAX_SECONDS)
        cursor = message_id
        waited = 0.0
        async with httpx.AsyncClient(timeout=60) as client:
            while time.monotonic() < deadline:
                try:
                    response = await client.get(
                        f"{self.base}/localassistant/message",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"message_id": cursor})
                except httpx.HTTPError as error:
                    raise HarnessError(
                        f"拉取 WorkBuddy 回复失败（网络）：{type(error).__name__}") from error
                if response.status_code != 200:
                    raise HarnessError(_failure(response, "查询本地助理消息历史"))

                messages = (_json(response).get("data") or {}).get("messages") or []
                for message in messages:
                    if not isinstance(message, dict):
                        continue
                    cursor = message.get("message_id") or cursor
                    if message.get("role") == "assistant":
                        text = "".join(str(part) for part in (message.get("content") or []))
                        if text.strip():
                            return text
                await asyncio.sleep(POLL_INTERVAL)
                waited += POLL_INTERVAL
                if waited and int(waited) % 15 == 0:
                    emit("activity", f"本机仍在执行…（已等待 {int(waited)} 秒）")
        raise HarnessError("等待 WorkBuddy 回复超时；任务可能仍在桌面端执行，请到客户端查看")


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _describe(response: httpx.Response) -> str:
    payload = _json(response)
    error = payload.get("error")
    if isinstance(error, dict):
        detail = error.get("message") or ""
        code = error.get("code")
        return f"HTTP {response.status_code} {detail}".strip() + (f"（{code}）" if code else "")
    message = payload.get("message") or payload.get("msg") or ""
    return f"HTTP {response.status_code} {message}".strip()


def _failure(response: httpx.Response, action: str) -> str:
    status = response.status_code
    auth_header = response.headers.get("www-authenticate", "") or ""
    if status == 401:
        return f"{action}失败：凭证无效或已过期（HTTP 401）。请重新完成 OAuth 授权"
    if status == 403:
        if "insufficient_scope" in auth_header:
            return (f"{action}失败：Scope 不足（HTTP 403 insufficient_scope）。"
                    f"请确认应用已通过审核并授予 {SCOPE_HINT}")
        if "access_denied" in auth_header:
            return f"{action}失败：用户未授权该应用（HTTP 403 access_denied）。请重新走授权页"
        return (f"{action}失败：本地助理身份缺失（HTTP 403）。"
                f"请确认 PC 端 WorkBuddy 已登录并连上开放平台")
    if status == 429:
        return f"{action}失败：被限流（HTTP 429）。AI Workbench 会稍后重试，请降低调用频率"
    return f"{action}失败：{_describe(response)}"


def _chmod_private(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        # Windows 上 chmod 语义有限；不因权限位设置失败而中断
        pass
