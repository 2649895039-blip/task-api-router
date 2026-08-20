"""M1 验收：Planner 拆解任务，输出带依赖的子任务清单。

用法：cd task-api-router && python examples/m1_test.py
"""
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




from task_router.client import ModelClient
from task_router.planner import Planner
from task_router.registry import ModelRegistry


def main():
    cfg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "models.yaml")
    _require_config(cfg)
    registry = ModelRegistry(cfg)
    client = ModelClient(registry)
    planner = Planner(client, registry)

    task = "写一个 Flask 待办事项 API，包含增删改查接口和单元测试"
    print(f"任务：{task}\n")

    plan = planner.plan(task)
    print(plan.summary())

    print("\n无依赖子任务（可并行）:")
    for t in plan.roots():
        print(f"  [{t.id}] {t.name}")


if __name__ == "__main__":
    main()