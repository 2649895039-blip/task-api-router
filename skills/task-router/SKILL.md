---
name: task-router
description: 任务级 AI 模型路由与成本调度。当用户需要写代码/写脚本、翻译、调研、批量处理，或想自动选择最合适、最省钱的模型来执行任务时，使用 `task-router "任务"` 完成任务并按模型路由；需要拆分复杂任务时用 `task-router --plan`。
---

# Task Router

`task-router` 是 task-api-router 插件的命令行入口：一条任务输入 → 自动选择最合适模型 → 执行 → 记录独立运行日志与成本。

## 何时使用

- 用户要写代码、写脚本、修 bug、做翻译、调研、批量生成等具体任务
- 用户想控制 token/成本，让路由自动选"便宜够用"的模型
- 用户明确提到模型路由、多模型、省钱执行

## 用法

```bash
# 单条任务（自动路由 + 执行 + 记日志）
task-router "写一个 Python 函数解析 JSON"

# 明确需要拆分的复杂任务（才会调用 Planner）
task-router --plan "重构整个项目"

# 查看已配置可用的模型
task-router --models

# 查看历史运行日志 / 某个运行详情
task-router --list
task-router --show <run_id>

# 动作守卫（宿主在工具执行前调用，本地零 token）
task-router --check-action '{"tool":"shell","arguments":{"command":"git reset --hard"}}' --workspace .
```

## 关键约定

- 不配置 key 时模型会显示"缺配置"，请让用户按 README 设置环境变量（如 `DEEPSEEK_API_KEY`），key 绝不写进代码或仓库。
- 路由只在本机已配置的模型里选，按 `config/ranking.yaml` 的相对排序取第一个可用。
- 默认不拆任务；只有显式 `--plan` 才拆 DAG。
- 动作守卫是本地尽力而为的弱校验：只拦截明显破坏性命令（`rm -rf`、`git reset --hard` 等）和给出风险提示，不是完整沙箱。
