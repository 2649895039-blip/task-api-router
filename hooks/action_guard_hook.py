#!/usr/bin/env python3
"""Claude Code PreToolUse hook → task-api-router 动作守卫。

Claude Code 在工具执行前调用本脚本，把工具名/参数转发给
task_router.action_guard 做本地检查（不消耗 token）。

Hook 输出使用 Claude Code 原生的 hookSpecificOutput.permissionDecision：
  allow = 允许，ask = 请求用户确认，deny = 阻止。
阻止动作同时返回退出码 2，兼容只理解退出码的宿主。
脚本异常或无法加载 task_router 时返回 ask（exit 0），避免静默放行未知动作。
"""
from __future__ import annotations

import json
import os
import sys

# 让"未 pip install"的仓库本地也能 import（插件根在 hooks/ 的上一级）
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)


def main() -> int:
    payload = sys.stdin.read() or "{}"
    try:
        data = json.loads(payload)
    except Exception:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": "动作参数不是有效 JSON，请确认后再执行",
            }
        }, ensure_ascii=True))
        return 0

    try:
        from task_router.action_guard import check_action_json
    except Exception as exc:
        print(f"[task-api-router] 动作守卫未加载，已转为确认（{type(exc).__name__}）", file=sys.stderr)
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": "动作守卫未加载，请确认后再执行",
            }
        }, ensure_ascii=True))
        return 0

    # 工作区优先级：payload.cwd > CLAUDE_PROJECT_DIR > 当前目录
    workspace = (
        data.get("cwd")
        or os.environ.get("CLAUDE_PROJECT_DIR")
        or os.getcwd()
    )
    try:
        decision = check_action_json(payload, workspace)
    except Exception as exc:
        print(f"[task-api-router] 动作守卫解析失败，已转为确认（{type(exc).__name__}）", file=sys.stderr)
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": "动作参数无法解析，请确认后再执行",
            }
        }, ensure_ascii=True))
        return 0

    print(f"[task-api-router] {decision.risk} 风险: {decision.reason}", file=sys.stderr)
    permission = {"allow": "allow", "confirm": "ask", "block": "deny"}.get(
        decision.decision, "ask"
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": permission,
            "permissionDecisionReason": decision.reason,
        }
    }, ensure_ascii=True))
    return decision.exit_code if decision.decision == "block" else 0


if __name__ == "__main__":
    raise SystemExit(main())
