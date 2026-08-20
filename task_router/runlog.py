"""M5: RunLog — 每个任务一次运行 = 一个独立日志文件

用户决策（2026-08-03）：不做"项目记忆"自动匹配（模糊匹配不可预测），
改为每次任务运行单独落一个日志文件，随时可单独查看。

目录结构：
  data/runs/<run_id>.json   独立运行日志（一个任务一个文件，完整可读）
  data/history.jsonl        统一流水（Reporter，供 Feedback 学习）
"""
import json
import os
import re
import time
from typing import List, Optional

from .executor import ExecutionReport
from .planner import Plan
import logging

log = logging.getLogger(__name__)



class RunLog:
    def __init__(self, data_dir: str):
        self.runs_dir = os.path.join(data_dir, "runs")
        os.makedirs(self.runs_dir, exist_ok=True)

    def save_run(self, task: str, plan: Plan, report: ExecutionReport, record: dict) -> str:
        """把一次运行写成独立 JSON 日志，返回 run_id。

        并发安全：用 O_CREAT|O_EXCL 原子建文件，已存在则追加序号重试，
        绝不覆盖已有日志（先查后写有 TOCTOU 竞态）。
        """
        base = self._new_run_id(task)
        run_id, n = base, 0
        # 先用 O_EXCL 原子占住一个文件名（防 TOCTOU 竞态覆盖），拿到最终 run_id
        # 后再构造内容写入。已存在则追加序号重试。
        while True:
            try:
                fd = os.open(self._path(run_id), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
                break
            except FileExistsError:
                n += 1
                run_id = f"{base}-{n}"
        entry = {
            "run_id": run_id,
            "timestamp": time.time(),
            "task": task,
            "total_cost": round(report.total_cost, 6),
            "total_tokens": report.total_tokens,
            "routing": record.get("routing", {}),
            "subtasks": [
                {"id": t.id, "name": t.name, "capability": t.capability, "depends_on": t.depends_on}
                for t in plan.tasks
            ],
            "results": record.get("tasks", []),
        }
        try:
            os.write(fd, (json.dumps(entry, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
        return run_id

    def list_runs(self) -> List[str]:
        """列出所有 run_id，新的在前。"""
        names = [f[:-5] for f in os.listdir(self.runs_dir) if f.endswith(".json")]
        return sorted(names, reverse=True)

    def load_run(self, run_id: str) -> Optional[dict]:
        # 防路径穿越：run_id 可能来自用户输入(--show / 交互 /show)，只允许"纯文件名"，
        # 含 / \ .. 或非文件名的都拒绝，绝不拼进路径去 open。
        if not isinstance(run_id, str) or not run_id.strip() or run_id != os.path.basename(run_id):
            log.warning(f"[WARN] 非法 run_id: {run_id!r}，拒绝读取（防路径穿越）")
            return None
        path = os.path.join(self.runs_dir, f"{run_id}.json")
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _path(self, run_id: str) -> str:
        return os.path.join(self.runs_dir, f"{run_id}.json")

    @staticmethod
    def _new_run_id(task: str) -> str:
        """run_id = 时间戳(秒+毫秒) + 任务片段，天然唯一且可读。"""
        ts = time.strftime("%Y%m%d-%H%M%S", time.localtime())
        millis = f"{int(time.time() * 1000) % 1000:03d}"
        slug = re.sub(r"[_\W]+", "_", task, flags=re.UNICODE)[:20].strip("_")
        if not slug:
            slug = "task"
        return f"{ts}-{millis}-{slug}"
