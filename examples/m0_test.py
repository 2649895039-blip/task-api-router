"""M0 验收脚本：验证 ModelRegistry + ProviderAdapter 能调通所有已配置模型。

用法：cd task-api-router && python examples/m0_test.py
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



from task_router.registry import ModelRegistry
from task_router.client import ModelClient


def main():
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "models.yaml")
    _require_config(cfg_path)
    registry = ModelRegistry(cfg_path)
    client = ModelClient(registry)

    print(f"注册表模型: {registry.list()}\n")

    for model_id in registry.list():
        resp = client.chat(
            model_id,
            [{"role": "user", "content": "只回复两个字：收到"}],
            max_tokens=16,
        )
        if resp.success:
            print(f"[{model_id}] OK  | 内容={resp.content.strip()[:24]!r} | "
                  f"tokens={resp.total_tokens()} | {resp.latency_ms}ms | ${resp.cost:.6f}")
        else:
            print(f"[{model_id}] FAIL| {resp.error}")


if __name__ == "__main__":
    main()