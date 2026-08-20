"""M5 验收：RunLog 独立运行日志（不做自动记忆匹配）

用户决策（2026-08-03）：项目记忆自动匹配不可预测 → 改为每个任务一次运行
独立落一个日志文件。本测试验证：
1. 跑两个任务 → data/runs/ 里有两个互不干扰的独立日志
2. 每个日志内容完整（任务/子任务/各模型/token/成本），可单独读取
用法：cd task-api-router && python examples/m5_test.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def _require_config(path: str):
    """models.yaml 缺失时给友好提示（新用户先复制模板）"""
    if not os.path.exists(path):
        alt = path[:-5] + ".example.yaml"
        if os.path.exists(alt):
            print(f"[提示] 未找到 {path}，请先复制模板：\n"
                  f"  cp {alt} {path}\n"
                  f"然后填入你的模型和 API key（环境变量）。")
        else:
            print(f"[提示] 未找到 {path}，请先安装/配置模型。")
        raise SystemExit(1)




from task_router.orchestrator import RouterOrchestrator


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    root = os.path.join(base, "..")
    cfg = os.path.join(root, "config", "models.yaml")
    _require_config(cfg)
    data = os.path.join(root, "data")
    os.makedirs(data, exist_ok=True)

    orch = RouterOrchestrator(cfg, data)

    # ---- 两个独立任务 ----
    task1 = "调研人工智能在医疗领域的应用趋势"
    task2 = "把下面这段文字翻译成英文：人工智能正在改变医疗行业"

    print(f"① 任务1：{task1}")
    r1 = orch.run(task1)
    print(f"   独立日志: {r1.run_id}")
    print(f"   子任务: {[t.name for t in r1.plan.tasks]}")

    print(f"② 任务2：{task2}")
    r2 = orch.run(task2)
    print(f"   独立日志: {r2.run_id}")

    # ---- 展示：两个任务各自成档 ----
    runs = orch.runlog.list_runs()
    print(f"\n运行日志目录 data/runs/ ({len(runs)} 个独立日志):")
    for rid in runs:
        print(f"   {rid}")

    # ---- 单独读取任务2的日志 ----
    log2 = orch.runlog.load_run(r2.run_id)
    print(f"\n[OK] 任务2日志可单独读取: {r2.run_id}")
    print(f"     任务: {log2['task']}")
    print(f"     token: {log2['total_tokens']} | 成本: ${log2['total_cost']:.6f}")
    print(f"     子任务: {len(log2['subtasks'])} 个 | 结果: {len(log2['results'])} 条")
    for res in log2["results"]:
        mark = "OK " if res["success"] else "FAIL"
        print(f"       [{res['subtask_id']}] {res['name']} -> {res['model_id']} | {mark} | {res['tokens']}t | ${res['cost']:.6f}")


if __name__ == "__main__":
    main()
