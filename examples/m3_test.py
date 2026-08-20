"""M3 验收：全流程 规划→分配→并行执行→报告。

用法：cd task-api-router && python examples/m3_test.py
"""
import os
import sys
import time

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




from task_router.allocator import Allocator
from task_router.client import ModelClient
from task_router.executor import DAGExecutor
from task_router.planner import Planner
from task_router.registry import ModelRegistry


def main():
    cfg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "models.yaml")
    _require_config(cfg)
    registry = ModelRegistry(cfg)
    client = ModelClient(registry)
    planner = Planner(client, registry)
    executor = DAGExecutor(client, Allocator(registry))

    task = "写一个 Flask 待办事项 API，包含增删改查接口和单元测试"
    print(f"任务：{task}\n")

    t0 = time.time()
    plan = planner.plan(task)
    print(plan.summary(), "\n")

    report = executor.execute(plan, context=task)
    elapsed = time.time() - t0
    print(report.summary())
    print(f"\n总耗时 {elapsed:.1f}s（含规划）")


if __name__ == "__main__":
    main()