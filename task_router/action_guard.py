"""Local pre-tool action guard shared by agent integrations."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


READ_TOOLS = {"read", "search", "grep", "glob", "list", "websearch", "web_search", "fetch"}
WRITE_TOOLS = {"write", "edit", "patch", "create", "move", "rename"}
SHELL_TOOLS = {"bash", "shell", "terminal", "exec", "run", "powershell"}
DESTRUCTIVE = re.compile(
    r"(?:\brm\s+-[^\n]*r|\bdel\s+/[sq]|remove-item[^\n]*(?:-recurse|-force)|"
    r"git\s+(?:reset\s+--hard|clean\s+-[^\n]*f)|\bformat\b|\bshutdown\b)", re.I)
EXTERNAL_EFFECT = re.compile(
    r"(?:curl|wget|invoke-webrequest).*(?:-x\s+(?:post|put|delete)|--data|upload)|"
    r"\b(?:publish|deploy|send|message|payment|purchase)\b", re.I)


@dataclass
class ActionDecision:
    decision: str
    risk: str
    reason: str
    exit_code: int

    def to_dict(self) -> dict:
        return asdict(self)


class ActionGuard:
    def __init__(self, workspace: str):
        self.workspace = Path(workspace).resolve()

    def check(self, tool: str, arguments: Any = None) -> ActionDecision:
        name = (tool or "").lower().replace("-", "_")
        args = arguments if isinstance(arguments, dict) else {"value": arguments}
        if name in READ_TOOLS or any(name.startswith(item) for item in READ_TOOLS):
            return ActionDecision("allow", "low", "只读动作", 0)
        if name in WRITE_TOOLS or name.endswith("edit") or name.endswith("write"):
            return self._check_write(args)
        if name in SHELL_TOOLS or any(name.startswith(item) for item in SHELL_TOOLS):
            return self._check_shell(args)
        return ActionDecision("confirm", "unknown", "未知工具，交给用户或宿主 Agent 确认", 2)

    def _check_write(self, args: dict) -> ActionDecision:
        raw_path = next((args.get(k) for k in ("path", "file_path", "target", "destination")
                         if args.get(k)), None)
        if not raw_path:
            return ActionDecision("confirm", "medium", "写入动作没有明确目标路径", 2)
        target = Path(str(raw_path))
        if not target.is_absolute():
            target = self.workspace / target
        try:
            target.resolve().relative_to(self.workspace)
        except ValueError:
            return ActionDecision("confirm", "high", "目标位于工作区之外", 2)
        return ActionDecision("allow", "medium", "工作区内的明确写入", 0)

    def _check_shell(self, args: dict) -> ActionDecision:
        command = str(args.get("command") or args.get("cmd") or args.get("value") or "")
        if not command.strip():
            return ActionDecision("confirm", "medium", "命令内容为空或无法识别", 2)
        if DESTRUCTIVE.search(command):
            return ActionDecision("block", "high", "检测到破坏性命令", 3)
        if EXTERNAL_EFFECT.search(command):
            return ActionDecision("confirm", "high", "命令可能向外部系统发送数据或产生副作用", 2)
        return ActionDecision("allow", "medium", "未命中本地高风险规则", 0)


def check_action_json(payload: str, workspace: str) -> ActionDecision:
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("动作 JSON 必须是对象")
    # Accept native hook payloads without making each host integration rewrite JSON.
    tool = data.get("tool") or data.get("tool_name") or data.get("name") or ""
    arguments = (data.get("arguments") or data.get("tool_input") or
                 data.get("input") or data.get("args") or {})
    return ActionGuard(workspace).check(str(tool), arguments)
