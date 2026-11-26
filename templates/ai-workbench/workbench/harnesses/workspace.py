"""Workspace instructions shared by native Agent adapters."""
from pathlib import Path
from .base import HarnessError

def workspace_documents(root):
    documents=sorted((root/'agents/workspace').glob('*.md'))
    if not any(p.name=='AGENTS.md' for p in documents):raise HarnessError('缺少工作台 agents/workspace/AGENTS.md')
    return documents

def harness_instructions(request):
    root=request.cwd.resolve()
    docs='\n\n'.join(p.read_text(encoding='utf-8') for p in workspace_documents(root))
    return docs+f"\n工作区：{root}；引擎：{request.env.get('WORKBENCH_AGENT_RUNTIME','')}；权限：{request.sandbox}。\n技能目录：{root/'skills/builtin'}；输出：{root/'outputs/generated'}。先读SKILL.md再执行，不自动安装依赖。凭据不可回显；额外工具权限必须交由用户确认。"
