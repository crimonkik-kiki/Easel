"""Atomic local harness settings and durable session ownership."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from .base import HarnessError

IDS = ("api", "opencode", "codex", "acp", "workbuddy")


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (OSError, ValueError) as error:
        raise HarnessError("Agent 设置或会话记录损坏，请检查本地文件；不会自动新建会话丢失历史") from error


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def settings(outputs: Path, env: dict[str, str]) -> dict:
    data=read_json(outputs/'_harness/config.json')
    runtime=env.get('WORKBENCH_AGENT_RUNTIME',data.get('runtime','api'))
    if runtime not in IDS: raise HarnessError('执行引擎未注册')
    return {'runtime':runtime,'models':data.get('models',{}),'sandbox':'workspace-write','codex_auto_approve':False}


def binding_path(sessions: Path, key: str) -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return sessions / "harness" / f"{digest}.json"


def binding(sessions: Path, key: str) -> dict:
    record = read_json(binding_path(sessions, key))
    if record and (record.get("runtime") not in IDS
                   or not isinstance(record.get("native_id"), str)):
        raise HarnessError("Agent 会话记录格式无效，不会自动重置历史")
    return record


def bind(sessions: Path, key: str, runtime: str, native_id: str = "") -> None:
    if runtime not in IDS or not isinstance(native_id, str):
        raise HarnessError("Agent 会话绑定无效")
    current = binding(sessions, key)
    if current and current.get("runtime") != runtime:
        raise HarnessError("此会话属于其他 Agent 底座，请新建对话")
    if current.get("native_id") and current["native_id"] != native_id:
        raise HarnessError("Agent 返回了不同的原生会话 ID，不会替换已有历史")
    write_json(binding_path(sessions, key), {"runtime": runtime, "native_id": native_id})
