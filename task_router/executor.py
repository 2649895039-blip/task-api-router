"""M3: DAG Executor — 按依赖并行执行子任务

无依赖的分支并行跑（asyncio），依赖完成的才进入下一波。
商用级健壮性：
- 上游依赖子任务的产出会传给下游（DAG 不只是控制顺序，还传内容）
- 单个子任务异常不会拖死整个 run（gather return_exceptions）
- 模型调用失败 → 模型级熔断 + 沿榜单回退到下一个可用模型
- 计划里出现坏依赖/死锁 → 显式 WARN，不再静默兜底
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Set

from .allocator import Allocator, Allocation
from .client import ModelClient
from .models import ModelResponse, safe_error_text
from .planner import Plan, SubTask

log = logging.getLogger(__name__)


@dataclass
class TaskResult:
    """单个子任务的执行结果。"""
    subtask_id: int
    model_id: str
    response: ModelResponse
    attempted_model_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        r = self.response
        return {
            "subtask_id": self.subtask_id,
            "model_id": self.model_id,
            "success": r.success,
            "content": (r.content or "")[:500],
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "latency_ms": r.latency_ms,
            "cost": round(r.cost, 6),
            "error": r.error,
        }


@dataclass
class ExecutionReport:
    """一次完整执行的汇总报告（M4 Reporter 的数据来源）。"""
    plan: Plan
    allocations: Dict[int, Allocation]
    results: Dict[int, TaskResult]
    total_cost: float = 0.0
    total_tokens: int = 0
    routing_cost: float = 0.0
    routing_tokens: int = 0

    def compute(self):
        self.total_cost = self.routing_cost + sum(t.response.cost for t in self.results.values())
        self.total_tokens = self.routing_tokens + sum(t.response.total_tokens() for t in self.results.values())
        return self

    def summary(self) -> str:
        lines = [
            f"执行完成：{len(self.results)}/{len(self.plan.tasks)} 个子任务，"
            f"共 {self.total_tokens} tokens，成本 ${self.total_cost:.4f}"
        ]
        for t in self.plan.tasks:
            r = self.results.get(t.id)
            if r is None:
                lines.append(f"  [{t.id}] {t.name} — 未执行")
                continue
            mark = "OK " if r.response.success else "FAIL"
            lines.append(
                f"  [{t.id}] {t.name} → {r.model_id} | {mark} | "
                f"{r.response.latency_ms}ms | {r.response.total_tokens()}t | ${r.response.cost:.6f}"
            )
        return "\n".join(lines)


class DAGExecutor:
    def __init__(self, client: ModelClient, allocator: Allocator, max_retries: int = 2):
        self.client = client
        self.allocator = allocator
        self.max_retries = max_retries      # 失败后最多再沿榜单试几个模型
        # 注意：不在实例上持有跨 run 的熔断状态（execute_async 内部用局部变量），
        # 否则同一个 DAGExecutor 被并发复用时会互相清空/污染熔断记录。

    def execute(self, plan: Plan, context: str = "", strategy: str = "quality") -> ExecutionReport:
        return asyncio.run(self.execute_async(plan, context, strategy))

    async def execute_async(self, plan: Plan, context: str = "", strategy: str = "quality") -> ExecutionReport:
        unhealthy: Set[str] = set()   # 本次 run 内熔断的模型（run 级局部变量，可安全并发复用实例）
        allocations = {t.id: self.allocator.allocate(t, strategy=strategy) for t in plan.tasks}
        results: Dict[int, TaskResult] = {}
        remaining_deps = {t.id: list(t.depends_on) for t in plan.tasks}
        remaining = {t.id: t for t in plan.tasks}

        while remaining:
            ready = [t for tid, t in remaining.items() if not remaining_deps[tid]]
            if not ready:   # 坏依赖/死锁保护：强制取第一个，但必须暴露给用户
                log.warning("计划存在坏依赖或死锁，剩余子任务强制串行执行")
                ready = [remaining[next(iter(remaining))]]

            done = await asyncio.gather(
                *(self._run_task(t, allocations[t.id], context, results, strategy, unhealthy) for t in ready),
                return_exceptions=True,
            )
            for t, raw in zip(ready, done):
                if isinstance(raw, asyncio.CancelledError):
                    raise raw   # 取消必须正常传播，绝不能吞掉（否则超时/取消机制形同虚设）
                if isinstance(raw, BaseException):
                    # 子任务内部异常（不应发生，兜底）：转成失败 TaskResult，别拖死整个 run
                    raw = TaskResult(
                        t.id, allocations[t.id].model_id,
                        ModelResponse.fail(allocations[t.id].model_id,
                                           f"执行异常: {safe_error_text(raw)}"),
                    )
                results[t.id] = raw
                del remaining[t.id]
                for deps in remaining_deps.values():
                    if t.id in deps:
                        deps.remove(t.id)

        return ExecutionReport(plan, allocations, results).compute()

    async def _run_task(self, subtask: SubTask, alloc: Allocation, context: str,
                        results: Dict[int, TaskResult], strategy: str,
                        unhealthy: Set[str]) -> TaskResult:
        # 分配结果没有可用模型（空 id）→ 直接短路失败，不发请求
        if not alloc.model_id:
            return TaskResult(subtask.id, "", ModelResponse.fail("", alloc.reason or "无可用模型"),
                              attempted_model_ids=[])

        messages = self._build_messages(subtask, context, results)
        attempted = [alloc.model_id]

        # 已熔断的模型不再次调用（避免每个子任务都白等一次超时），直接进回退链路
        if alloc.model_id in unhealthy:
            resp = ModelResponse.fail(alloc.model_id, "模型已熔断（本次 run 内先前调用失败）")
        else:
            resp = await asyncio.to_thread(self.client.chat, alloc.model_id, messages, max_tokens=1024)
            if resp.success:
                return TaskResult(subtask.id, alloc.model_id, resp, attempted)

        # 失败 → 熔断该模型，沿榜单/能力回退到下一个可用模型（最多 max_retries 次）
        unhealthy.add(alloc.model_id)
        log.warning("模型 %s 调用失败(%s)，本次 run 后续任务避开它，尝试榜单下一个可用模型",
                    alloc.model_id, resp.error)
        last_mid, last_resp = alloc.model_id, resp
        for _ in range(self.max_retries):
            nxt = self.allocator.allocate(
                subtask, attempted=attempted, unhealthy=unhealthy, strategy=strategy)
            if not nxt.model_id or nxt.model_id in attempted:
                break
            attempted.append(nxt.model_id)
            last_mid, last_resp = nxt.model_id, await asyncio.to_thread(
                self.client.chat, nxt.model_id, messages, max_tokens=1024)
            if last_resp.success:
                return TaskResult(subtask.id, last_mid, last_resp, attempted)
            unhealthy.add(last_mid)
        return TaskResult(subtask.id, last_mid, last_resp, attempted)

    def _build_messages(self, subtask: SubTask, context: str,
                        results: Dict[int, TaskResult]) -> List[dict]:
        """把上游依赖子任务的产出拼进当前子任务，让下游真正基于上游结果继续。"""
        upstream = []
        for dep_id in subtask.depends_on:
            dep = results.get(dep_id)
            if dep and dep.response.success:
                upstream.append(
                    f"[上游子任务{dep_id}] 由 {dep.response.model_id} 产出：\n{dep.response.content}"
                )
        user = f"子任务[{subtask.id}]：{subtask.name}\n要求：{subtask.description}\n请直接完成并输出结果。"
        if upstream:
            user = ("以下是已完成的前置子任务结果，请基于它们继续完成当前子任务：\n\n"
                    + "\n\n".join(upstream) + "\n\n" + user)
        if context:
            return [
                {"role": "system", "content": f"你在完成一个总任务的一部分。总任务：{context}"},
                {"role": "user", "content": user},
            ]
        return [{"role": "user", "content": user}]
