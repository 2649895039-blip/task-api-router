"""M4: Reporter — 统一运行记录（数据中台）

把每次执行变成一条 JSON 记录落盘，同时是 Feedback 和 RunLog 的数据来源。
"""
import json
import os
import time
import hashlib
from typing import Dict

from .executor import ExecutionReport
from .planner import Plan


class Reporter:
    def __init__(self, history_path: str, include_content: bool = False):
        self.history_path = history_path
        self.include_content = include_content
        parent = os.path.dirname(history_path)
        os.makedirs(parent, exist_ok=True)
        try:
            os.chmod(parent, 0o700)
            if os.path.exists(history_path):
                os.chmod(history_path, 0o600)
        except OSError:
            pass

    def emit(self, plan: Plan, report: ExecutionReport, task: str = "", decision: dict = None) -> dict:
        """把一次执行写成一条运行记录，追加到 JSONL。返回记录本身。"""
        tasks = []
        for t in plan.tasks:
            r = report.results.get(t.id)
            if r is None:
                continue
            resp = r.response
            tasks.append({
                "subtask_id": t.id,
                "name": t.name if self.include_content else "[redacted]",
                "capability": t.capability,
                "depends_on": t.depends_on,
                "model_id": r.model_id,
                "success": resp.success,
                "latency_ms": resp.latency_ms,
                "cost": round(resp.cost, 6),
                "tokens": resp.total_tokens(),
                "error": resp.error,
            })

        record = {
            "timestamp": time.time(),
            "task": task if self.include_content else "[redacted]",
            "task_sha256": hashlib.sha256(task.encode("utf-8")).hexdigest(),
            "total_cost": round(report.total_cost, 6),
            "total_tokens": report.total_tokens,
            "routing": decision or {},
            "tasks": tasks,
        }
        # 二进制追加 + 整行一次 write()：O_APPEND 下内核保证"偏移定位+写入"原子，
        # 单条 JSONL 记录跨进程并发追加不会互相交叉写坏。
        line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
        fd = os.open(self.history_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
        return record
