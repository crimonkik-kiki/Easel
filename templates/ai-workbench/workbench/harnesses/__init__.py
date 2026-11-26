"""Easel-derived private stdio / desktop Agent adapters."""
from .base import HarnessError, RunRequest
from .codex import CodexAdapter
from .acp import ACPAdapter, OpenCodeAdapter
from .workbuddy import WorkBuddyAdapter
ADAPTERS = {a.descriptor.id: a for a in (CodexAdapter(), OpenCodeAdapter(), ACPAdapter(), WorkBuddyAdapter())}
def adapter(runtime):
    if runtime not in ADAPTERS: raise HarnessError("此执行引擎未注册")
    return ADAPTERS[runtime]
