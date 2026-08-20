"""task-api-router 插件入口（兼容旧命令）

推荐用法（等价）：
  python -m task_router "写一个 Python 函数解析 JSON"
  python plugin.py "写一个 Python 函数解析 JSON"
  task-router "写一个 Python 函数解析 JSON"    # pip install -e . 后

实际逻辑在 task_router/cli.py。
"""
import os
import sys

if __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from task_router.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
