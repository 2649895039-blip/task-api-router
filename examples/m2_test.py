"""M2 验收：M1 拆解 → M2 分配，展示每个子任务该用哪个模型。

用法：cd task-api-router && python examples/m2_test.py
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




from task_router.allocator import Allocator
from task_router.client import ModelClient
from task_router.planner import Planner
from task_router.registry import ModelRegistry


def main():
    cfg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "models.yaml")
    _require_config(cfg)
    registry = ModelRegistry(cfg)
    client = ModelClient(registry)

    task = "写一个 Flask 待办事项 API，包含增删改查接口和单元测试"
    plan = Planner(client, registry).plan(task)
    allocator = Allocator(registry)

    print(f"任务：{task}\n")
    for t in plan.tasks:
        a = allocator.allocate(t)
        dep = f" 依赖{t.depends_on}" if t.depends_on else ""
        print(f"[{t.id}] {t.name}")
        print(f"     capability={t.capability} → model={a.model_id} ({a.reason}){dep}")


if __name__ == "__main__":
    main()