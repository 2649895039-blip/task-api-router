---
name: task-router
description: 任务级 AI 模型路由与成本调度。当用户需要写代码/写脚本、翻译、调研、批量处理，或想自动选择最合适、最省钱的模型来执行任务时，调用 `task-router "任务"`；需要拆分复杂任务时用 `task-router --plan`。动作守卫 `task-router --check-action` 可在工具执行前拦截危险命令。
---

# Task Router（OpenClaw）

`task-router` 是 task-api-router 的命令行入口：一条任务 → 自动选择最合适模型 → 执行 → 记录独立运行日志与成本。

## 安装

把本仓库复制到 OpenClaw 工作区，或在 `workspace/skills/` 下建立软链/拷贝本 skill 目录：

```bash
# 在 OpenClaw workspace 下
mkdir -p skills/task-router
cp -r <repo>/openclaw/skills/task-router/SKILL.md skills/task-router/
pip install -e <repo>    # 安装 task-router 命令（或直接 python <repo>/plugin.py）
```

## 用法

```bash
task-router "写一个 Python 函数解析 JSON"      # 单条任务
task-router --plan "重构整个项目"              # 拆 DAG（显式才拆）
task-router --models                          # 查看已配置模型
task-router --check-action '{"tool":"write","arguments":{"path":"/etc/hosts"}}' --workspace .
```

## 工具动作拦截（给 OpenClaw 的 hook 适配）

OpenClaw 可在调用工具前执行同一守卫，统一判断：

```bash
task-router --check-action <json> --workspace <工作区>
```

- 输出 JSON，退出码 `0=allow`、`2=confirm`、`3=block`
- 只读动作直接允许；工作区内写入允许；工作区外写入/未知工具/外部副作用要求确认；破坏性命令阻止
- 该接口只做本地弱校验，不是完整沙箱

## 约定

- key 只放环境变量（`DEEPSEEK_API_KEY` / `ANTHROPIC_API_KEY` 等），不写进代码/仓库
- 路由只在本机已配置模型里选，按 `config/ranking.yaml` 相对排序
- 默认不拆任务，只有 `--plan` 才调 Planner
