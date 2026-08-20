"""task-api-router 插件 CLI — 按"对话"为单位收任务/执行/记日志

用法:
  python -m task_router "写一个 Python 函数解析 JSON"      # 单条任务
  python -m task_router                          # 交互模式（每条输入=一次任务）
  python -m task_router --list                   # 列出所有运行日志
  python -m task_router --show <run_id>          # 查看某个运行日志
  python -m task_router --models                 # 列出已注册模型
  python -m task_router --version                # 版本号

默认链路: 本地筛查(0token) → 必要时廉价分类 → 静态路由 → 单次执行 → 独立日志
只有显式 --plan 才会额外调用 Planner 拆分复杂任务。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from . import __version__

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))


def _default_config() -> str:
    """解析默认模型注册表路径。

    pip install -e .（或直接在源码目录跑）时，仓库根 config/ 存在 → 用它；
    纯 pip install 到 site-packages 后没有仓库 config/ → 回退到随包安装的模板。
    """
    for p in (
        os.path.join(BASE, "config", "models.yaml"),
        os.path.join(BASE, "config", "models.example.yaml"),
        os.path.join(PACKAGE_DIR, "config", "models.example.yaml"),
    ):
        if os.path.exists(p):
            return p
    return os.path.join(PACKAGE_DIR, "config", "models.example.yaml")


def _auto_keys() -> None:
    """从本地 JSON 补 API key（仅当用户显式设置 TASK_ROUTER_API_CONFIG）。

    开源版不内置任何本机路径或具体 provider，避免读取到意外文件/暴露内部细节。
    只认环境变量；设了 TASK_ROUTER_API_CONFIG 才读，且会打印提示。

    JSON 格式（可选字段 api_key_env，缺省按 provider 名大写推导）：
      {"deepseek": {"api_key": "sk-...", "api_key_env": "DEEPSEEK_API_KEY"}, ...}
    """
    cfg_path = os.environ.get("TASK_ROUTER_API_CONFIG")
    if not cfg_path or not os.path.exists(cfg_path):
        return
    print(f"[提示] 从 {cfg_path} 加载本地 API key（TASK_ROUTER_API_CONFIG）")
    try:
        with open(cfg_path, encoding="utf-8") as handle:
            cfg = json.load(handle)
        loaded = 0
        for provider, info in cfg.items():
            if not isinstance(info, dict):
                continue
            env_name = info.get("api_key_env") or f"{provider.upper()}_API_KEY"
            if not os.environ.get(env_name) and info.get("api_key"):
                os.environ[env_name] = info["api_key"]
                loaded += 1
        if loaded:
            print(f"[提示] 已补齐 {loaded} 个 API key 环境变量")
    except Exception as exc:
        print(f"[警告] 读取 {cfg_path} 失败: {exc}")


def _print_result(r) -> None:
    print("\n" + "=" * 60)
    print(f"✅ 任务完成: {r.task}")
    print(f"📄 运行日志: {r.run_id}")
    print(f"📊 token: {r.report.total_tokens:,} | 成本: ${r.report.total_cost:.6f}")
    print(f"   子任务: {len(r.plan.tasks)} 个")
    for t in r.plan.tasks:
        tr = r.report.results.get(t.id)
        if tr is None:
            continue
        mark = "OK " if tr.response.success else "FAIL"
        print(f"     [{t.id}] {t.name} -> {tr.model_id} | {mark} | {tr.response.total_tokens()}t | "
              f"${tr.response.cost:.6f}")
    print("=" * 60)


def _make_orchestrator(config: str, data: str):
    from .orchestrator import RouterOrchestrator

    os.makedirs(data, exist_ok=True)
    return RouterOrchestrator(config, data)


def _cmd_list(orch) -> None:
    runs = orch.runlog.list_runs()
    print(f"运行日志目录 data/runs/ ({len(runs)} 个):")
    for rid in runs:
        log = orch.runlog.load_run(rid)
        if log:
            print(f"   {rid}  | {log['task'][:40]} | {log['total_tokens']}t | ${log['total_cost']:.6f}")


def _cmd_show(orch, run_id: str) -> None:
    log = orch.runlog.load_run(run_id)
    if not log:
        print(f"找不到 {run_id}")
        return
    print(f"run_id: {log['run_id']}")
    print(f"任务: {log['task']}")
    print(f"token: {log['total_tokens']} | 成本: ${log['total_cost']:.6f}")
    for res in log.get("results", []):
        mark = "OK " if res["success"] else "FAIL"
        print(f"  [{res['subtask_id']}] {res['name']} -> {res['model_id']} | {mark} | "
              f"{res['tokens']}t | ${res['cost']:.6f}")


def _cmd_models(orch) -> None:
    print("已注册模型:")
    for mid in orch.registry.list():
        cfg = orch.registry.get(mid)
        ok = "✅" if orch.registry.configured(mid) else "⚠️ 缺配置"
        print(f"  {mid:18s} {ok}  [{', '.join(cfg.capabilities)}]")


def _interactive(orch) -> None:
    print("🧠 task-api-router 插件 — 交互模式（按对话收任务）")
    print("   输入任务回车执行；/list 看日志；/show <id> 看详情；/models 看模型；Ctrl+C 退出")
    print("-" * 60)
    try:
        while True:
            task = input("你> ").strip()
            if not task:
                continue
            if task in ("/quit", "/exit", "quit", "exit", "q", "退出"):
                print("退出")
                break
            if task == "/list":
                _cmd_list(orch)
                continue
            if task.startswith("/show "):
                run_arg = task.split(" ", 1)[1].strip()
                _cmd_show(orch, run_arg)
                continue
            if task == "/models":
                _cmd_models(orch)
                continue
            try:
                r = orch.run(task)
            except Exception as exc:
                print(f"[错误] 任务执行失败: {exc}")
                continue
            _print_result(r)
    except (KeyboardInterrupt, EOFError):
        print("\n退出")


def main(argv: list[str] | None = None) -> int:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    # CLI 默认展示 WARNING 级日志（库被 import 时不影响宿主）
    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(
        prog="task-router",
        description="任务级 AI 模型调度插件：自动为任务选择最合适的模型",
    )
    parser.add_argument("task", nargs="*", help="任务文本（留空则进入交互模式）")
    parser.add_argument("--config", default=_default_config(), help="模型注册表路径")
    parser.add_argument("--data", default=os.path.join(BASE, "data"), help="数据目录（运行日志/流水）")
    parser.add_argument("--list", action="store_true", help="列出所有运行日志")
    parser.add_argument("--show", metavar="RUN_ID", help="查看某个运行日志")
    parser.add_argument("--models", action="store_true", help="列出已注册模型")
    parser.add_argument("--plan", action="store_true", help="显式调用 Planner 拆分复杂任务（默认不调用）")
    parser.add_argument("--check-action", metavar="JSON", help="本地检查 Agent 工具动作；传 - 时从 stdin 读取")
    parser.add_argument("--workspace", default=os.getcwd(), help="动作检查允许写入的工作区")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    if args.check_action is not None:
        from .action_guard import check_action_json
        payload = sys.stdin.read() if args.check_action == "-" else args.check_action
        try:
            decision = check_action_json(payload, args.workspace)
        except (ValueError, json.JSONDecodeError) as exc:
            print(json.dumps({"decision": "block", "risk": "invalid", "reason": str(exc),
                              "exit_code": 3}, ensure_ascii=False))
            return 3
        print(json.dumps(decision.to_dict(), ensure_ascii=False))
        return decision.exit_code

    _auto_keys()
    orch = _make_orchestrator(args.config, args.data)

    if args.list:
        _cmd_list(orch)
        return 0
    if args.show:
        _cmd_show(orch, args.show)
        return 0
    if args.models:
        _cmd_models(orch)
        return 0
    if args.task:
        task = " ".join(args.task)
        print(f"📥 任务: {task}")
        try:
            r = orch.run(task, use_planner=args.plan)
        except Exception as exc:
            print(f"[错误] 任务执行失败: {exc}")
            return 1
        _print_result(r)
        return 0

    _interactive(orch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
