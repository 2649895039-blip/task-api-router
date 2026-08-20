"""Orchestrator — 把全链路串起来（简化版：无 Feedback 学习）

任务 → 本地筛查 → 必要时廉价分类 → Allocator → 单次执行 → Reporter → RunLog
显式 use_planner=True 时才在 Allocator 前调用 Planner 拆 DAG。

用法：
    r = RouterOrchestrator("config/models.yaml", "data")
    result = r.run("写一篇关于人工智能的科普文章")
"""
from dataclasses import dataclass

from .allocator import Allocator
from .client import ModelClient
from .decision import RouteDecision, TaskScreen
from .executor import DAGExecutor, ExecutionReport
from .models import safe_error_text
from .planner import Planner, Plan, SubTask
from .preclassify import preclassify
from .registry import ModelRegistry
from .reporter import Reporter
from .runlog import RunLog
import logging

log = logging.getLogger(__name__)



@dataclass
class RunResult:
    task: str
    run_id: str
    pre: dict
    plan: Plan
    report: ExecutionReport
    record: dict
    decision: RouteDecision


class RouterOrchestrator:
    def __init__(self, config_path: str, data_dir: str):
        self.config_path = config_path
        self.data_dir = data_dir
        self.registry = ModelRegistry(config_path)
        self.client = ModelClient(self.registry)
        self.reporter = Reporter(f"{data_dir}/history.jsonl")
        self.runlog = RunLog(data_dir)
        self.allocator = Allocator(self.registry)
        self.screen = TaskScreen(self.client, self.registry)
        self.planner = Planner(self.client, self.registry)
        self.executor = DAGExecutor(self.client, self.allocator)

    def run(self, task: str, use_planner: bool = False) -> RunResult:
        # 0) 本地脚本优先；无法确定时只调用一次最便宜 API 做短分类。
        pre = preclassify(task)
        decision = self.screen.decide(task)
        print(f"[路由] {decision.source}: {decision.capability}/{decision.difficulty} "
              f"→ {decision.strategy} | {decision.reason}")

        # 1) 默认单任务直通；只有显式 --plan 才调用 Planner 拆 DAG。
        if use_planner:
            plan = self.planner.plan(task)
        else:
            plan = Plan(tasks=[SubTask(
                id=1, name=task, description=task, depends_on=[],
                capability=decision.capability,
            )], planner_model="local-script", raw_text="")

        # 2) 执行；若发生廉价分类，也计入本次总成本。
        report = self.executor.execute(plan, context=task, strategy=decision.strategy)
        classifier = decision.classifier_response
        report.routing_cost = (classifier.cost if classifier else 0.0) + plan.planning_cost
        report.routing_tokens = (classifier.total_tokens() if classifier else 0) + plan.planning_tokens
        report.compute()

        # 3) Reporter 落统一流水（落盘失败不丢已算出的结果/费用数据）
        record = {}
        try:
            record = self.reporter.emit(plan, report, task=task, decision=decision.to_dict())
        except Exception as e:
            log.warning(f"[WARN] 流水记录写入失败({safe_error_text(e)})，不影响本次结果")

        # 4) RunLog 单独存档（一个任务一个独立文件）
        run_id = ""
        try:
            run_id = self.runlog.save_run(task, plan, report, record)
        except Exception as e:
            log.warning(f"[WARN] 运行日志写入失败({safe_error_text(e)})，不影响本次结果")

        return RunResult(task=task, run_id=run_id, pre=pre, plan=plan, report=report,
                         record=record, decision=decision)
