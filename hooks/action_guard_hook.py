#!/usr/bin/env python3
"""Claude Code PreToolUse hook → task-api-router 动作守卫。

Claude Code 在工具执行前调用本脚本，把工具名/参数转发给
task_router.action_guard 做本地检查（不消耗 token）。

退出码语义（与 Claude Code PreToolUse 约定一致）：
  0 = 允许
  2 = 允许但给模型反馈警告（命中"需确认"规则，如工作区外写入）
  3 = 阻止（命中破坏性命令）
脚本异常或无法加载 task_router 时一律放行（exit 0），避免误伤宿主。
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
        return 0  # 解析失败放行

    try:
        from task_router.action_guard import check_action_json
    except Exception as exc:
        print(f"[task-api-router] 动作守卫未加载，已放行（{type(exc).__name__}）", file=sys.stderr)
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
        print(f"[task-api-router] 动作守卫解析失败，已放行（{type(exc).__name__}）", file=sys.stderr)
        return 0

    print(f"[task-api-router] {decision.risk} 风险: {decision.reason}", file=sys.stderr)
    return decision.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
