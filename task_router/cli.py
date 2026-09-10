"""task-api-router 插件 CLI — 按"对话"为单位收任务/执行/记日志

用法:
  python -m task_router "写一个 Python 函数解析 JSON"      # 单条任务
  python -m task_router                          # 交互模式（每条输入=一次任务）
  python -m task_router --list                   # 列出所有运行日志
  python -m task_router --show <run_id>          # 查看某个运行日志
  python -m task_router --models                 # 列出已注册模型
  python -m task_router --route "翻译一段文案"     # 只试算路由，不执行、不调 API
  python -m task_router --doctor                 # 安装/配置自检
  python -m task_router --stats                  # 本地成本/路由汇总
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
    print(f"[提示] 从 {cfg_path} 加载本地 API key（TASK_ROUTER_API_CONFIG）", file=sys.stderr)
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
            print(f"[提示] 已补齐 {loaded} 个 API key 环境变量", file=sys.stderr)
    except Exception as exc:
        print(f"[警告] 读取 {cfg_path} 失败: {exc}", file=sys.stderr)


def _print_result(r) -> None:
    print("\n" + "=" * 60)
    print(f"✅ 任务完成: {r.task}")
    print(f"📄 运行日志: {r.run_id}")
    print(f"📊 token: {r.report.total_tokens:,} | 成本: ${r.report.total_cost:.6f}")
    print(f"   子任务: {len(r.plan.tasks)} 个")
    if r.report.budget_exhausted:
        print("⚠️ 已达到本次运行预算软上限，后续任务已跳过")
    for t in r.plan.tasks:
        tr = r.report.results.get(t.id)
        if tr is None:
            continue
        mark = "OK " if tr.response.success else "FAIL"
        print(f"     [{t.id}] {t.name} -> {tr.model_id} | {mark} | {tr.response.total_tokens()}t | "
              f"${tr.response.cost:.6f}")
    print("=" * 60)


def _make_orchestrator(config: str, data: str, **kwargs):
    from .orchestrator import RouterOrchestrator

    os.makedirs(data, exist_ok=True)
    return RouterOrchestrator(config, data, **kwargs)


def _cmd_list(orch) -> None:
    runs = orch.runlog.list_runs()
    print(f"运行日志目录 data/runs/ ({len(runs)} 个):")
    for rid in runs:
        log = orch.runlog.load_run(rid)
        if log:
            task = log.get("task", "[redacted]")
            print(f"   {rid}  | {task[:40]} | {log['total_tokens']}t | ${log['total_cost']:.6f}")


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


def compute_stats(history_path: str, registry=None) -> dict:
    """Aggregate local history.jsonl into a cost/routing summary. No provider calls."""
    from collections import Counter, defaultdict
    import math

    summary = {
        "runs": 0,
        "total_cost_usd": 0.0,
        "total_tokens": 0,
        "success_subtasks": 0,
        "failed_subtasks": 0,
        "skipped_records": 0,
        "by_capability": defaultdict(lambda: {"runs": 0, "cost_usd": 0.0, "tokens": 0}),
        "by_model": defaultdict(lambda: {"runs": 0, "cost_usd": 0.0, "tokens": 0}),
        "by_strategy": Counter(),
        "by_source": Counter(),
        "history_path": history_path,
    }
    if not os.path.exists(history_path):
        summary["error"] = "no_history"
        return summary

    with open(history_path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                summary["skipped_records"] += 1
                continue
            if not isinstance(record, dict):
                summary["skipped_records"] += 1
                continue
            try:
                cost = float(record.get("total_cost") or 0.0)
                tokens = int(record.get("total_tokens") or 0)
            except (TypeError, ValueError, OverflowError):
                summary["skipped_records"] += 1
                continue
            if not math.isfinite(cost) or cost < 0 or tokens < 0:
                summary["skipped_records"] += 1
                continue
            summary["runs"] += 1
            summary["total_cost_usd"] += cost
            summary["total_tokens"] += tokens
            routing = record.get("routing") or {}
            if not isinstance(routing, dict):
                routing = {}
            cap = str(routing.get("capability") or "unknown")
            summary["by_capability"][cap]["runs"] += 1
            summary["by_capability"][cap]["cost_usd"] += cost
            summary["by_capability"][cap]["tokens"] += tokens
            strategy = str(routing.get("strategy") or "unknown")
            source = str(routing.get("source") or "unknown")
            summary["by_strategy"][strategy] += 1
            summary["by_source"][source] += 1
            tasks = record.get("tasks") or []
            if not isinstance(tasks, list):
                tasks = []
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                model_id = str(task.get("model_id") or "unknown")
                try:
                    task_cost = float(task.get("cost") or 0.0)
                    task_tokens = int(task.get("tokens") or 0)
                except (TypeError, ValueError, OverflowError):
                    continue
                if not math.isfinite(task_cost) or task_cost < 0 or task_tokens < 0:
                    continue
                summary["by_model"][model_id]["runs"] += 1
                summary["by_model"][model_id]["cost_usd"] += task_cost
                summary["by_model"][model_id]["tokens"] += task_tokens
                if task.get("success"):
                    summary["success_subtasks"] += 1
                else:
                    summary["failed_subtasks"] += 1

    # Illustrative baseline: if every subtask had used the most expensive configured model.
    # This is NOT a production savings claim — only a local comparison using history tokens.
    if registry is not None and summary["runs"] > 0:
        configured = [registry.get(mid) for mid in registry.list() if registry.configured(mid)]
        if configured:
            baseline_unit = max(
                max(c.cost_per_1k_in, c.cost_per_1k_out) for c in configured
            )
            # History stores blended cost, not split in/out tokens; use a conservative
            # estimate that treats total_tokens as if they were billed at that unit rate.
            summary["illustrative_baseline_cost_usd"] = round(
                baseline_unit * summary["total_tokens"] / 1000.0, 6
            )
            baseline = summary["illustrative_baseline_cost_usd"]
            summary["illustrative_delta_usd"] = round(baseline - summary["total_cost_usd"], 6)
    summary["total_cost_usd"] = round(summary["total_cost_usd"], 6)
    summary["by_capability"] = {k: {
        "runs": v["runs"],
        "cost_usd": round(v["cost_usd"], 6),
        "tokens": v["tokens"],
    } for k, v in sorted(summary["by_capability"].items())}
    summary["by_model"] = {k: {
        "runs": v["runs"],
        "cost_usd": round(v["cost_usd"], 6),
        "tokens": v["tokens"],
    } for k, v in sorted(summary["by_model"].items(), key=lambda kv: -kv[1]["cost_usd"])}
    summary["by_strategy"] = dict(summary["by_strategy"])
    summary["by_source"] = dict(summary["by_source"])
    return summary


def _cmd_stats(orch, as_json: bool = False) -> int:
    history = os.path.join(orch.data_dir, "history.jsonl")
    stats = compute_stats(history, orch.registry)
    if as_json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0
    if stats.get("error") == "no_history":
        print("暂无运行记录（history.jsonl 不存在）。先执行一条真实任务，或运行 demo_route.py。")
        return 0
    print("\n" + "=" * 60)
    print("📈 本地成本汇总（仅统计 history.jsonl，不调用任何 API）")
    print(f"运行次数: {stats['runs']}")
    print(f"总成本:   ${stats['total_cost_usd']:.6f}")
    print(f"总 token: {stats['total_tokens']:,}")
    print(f"子任务:   成功 {stats['success_subtasks']} / 失败 {stats['failed_subtasks']}")
    if stats.get("skipped_records"):
        print(f"跳过坏记录: {stats['skipped_records']}")
    print("按能力:")
    for cap, row in stats["by_capability"].items():
        print(f"  {cap:12s}  {row['runs']:4d} 次  ${row['cost_usd']:.6f}  {row['tokens']:,}t")
    print("按模型:")
    for mid, row in stats["by_model"].items():
        print(f"  {mid:18s}  {row['runs']:4d} 次  ${row['cost_usd']:.6f}  {row['tokens']:,}t")
    if stats.get("by_source"):
        print("分类来源: " + ", ".join(f"{k}={v}" for k, v in stats["by_source"].items()))
    if "illustrative_baseline_cost_usd" in stats:
        print("对比参考（示意，非生产承诺）:")
        print(f"  按最高单项 token 费率估算上界: ${stats['illustrative_baseline_cost_usd']:.6f}")
        print(f"  实际路由成本:             ${stats['total_cost_usd']:.6f}")
        print(f"  示意差额:                 ${stats.get('illustrative_delta_usd', 0):.6f}")
        print("  注：未知输入/输出拆分时按最高单项费率估算，仅作量级上界参考。")
    print("=" * 60)
    return 0


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
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
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
    parser.add_argument("--route", metavar="TASK", help="只试算路由结果，不执行、不调用任何 API")
    parser.add_argument("--doctor", action="store_true", help="安装/配置自检（无需 API key）")
    parser.add_argument("--stats", action="store_true", help="汇总本地 history.jsonl 成本/路由统计")
    parser.add_argument("--json", action="store_true", help="与 --route / --doctor / --stats 一起用，输出 JSON")
    parser.add_argument("--plan", action="store_true", help="显式调用 Planner 拆分复杂任务（默认不调用）")
    parser.add_argument("--max-concurrency", type=int, default=4, help="模型调用最大并发数（默认 4）")
    parser.add_argument("--max-cost", type=float, help="单次运行成本软上限（美元，达到后停止下一批任务）")
    parser.add_argument("--max-tokens", type=int, help="单次运行 token 软上限（达到后停止下一批任务）")
    parser.add_argument("--log-content", action="store_true", help="在本地日志保存任务原文（默认脱敏）")
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

    if args.doctor:
        from .doctor import format_doctor, run_doctor
        checks = run_doctor(args.config, args.data, package_dir=PACKAGE_DIR)
        if args.json:
            print(json.dumps(
                [{"name": c.name, "ok": c.ok, "detail": c.detail, "fix": c.fix} for c in checks],
                ensure_ascii=False, indent=2,
            ))
            return 0 if all(c.ok for c in checks) else 1
        text, failed = format_doctor(checks)
        print(text)
        return 1 if failed else 0

    _auto_keys()
    if args.max_concurrency < 1 or args.max_concurrency > 64:
        parser.error("--max-concurrency 必须在 1..64 之间")
    if args.max_cost is not None and args.max_cost <= 0:
        parser.error("--max-cost 必须大于 0")
    if args.max_tokens is not None and args.max_tokens <= 0:
        parser.error("--max-tokens 必须大于 0")
    orch = _make_orchestrator(
        args.config, args.data, max_concurrency=args.max_concurrency,
        max_cost_usd=args.max_cost, max_total_tokens=args.max_tokens,
        log_content=args.log_content,
    )

    if args.list:
        _cmd_list(orch)
        return 0
    if args.show:
        _cmd_show(orch, args.show)
        return 0
    if args.models:
        _cmd_models(orch)
        return 0
    if args.stats:
        return _cmd_stats(orch, as_json=args.json)
    if args.route is not None:
        try:
            preview = orch.route_only(args.route)
        except Exception as exc:
            print(f"[错误] 路由试算失败: {exc}")
            return 1
        if args.json:
            print(json.dumps(preview.to_dict(), ensure_ascii=False, indent=2))
            return 0
        d = preview.decision
        print("\n" + "=" * 60)
        print("🧭 路由试算（未执行，0 token）")
        print(f"📥 任务: {preview.task}")
        print(f"🏷  能力/难度: {d.capability} / {d.difficulty}")
        print(f"📊 策略: {d.strategy}  |  来源: {d.source}")
        print(f"💡 理由: {d.reason}")
        target = preview.model_id or ("待在线短分类后确定" if preview.classifier_would_call else "(无可用模型)")
        print(f"🎯 路由目标: {target}")
        print(f"   分配说明: {preview.allocation_reason}")
        if preview.classifier_would_call:
            print("⚠️  真实执行时会先用最便宜的已配置模型做一次短分类（最多 96 tokens）")
        if preview.pre.get("hits"):
            print(f"🔍 关键词命中: {', '.join(preview.pre['hits'])}")
        print("=" * 60)
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
