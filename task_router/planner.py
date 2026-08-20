"""M1: Planner — 任务拆解器

用户任务 → Meta Router 选规划模型 → LLM 拆解 → 结构化子任务清单（含依赖）
"""
import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Optional

from .client import ModelClient
from .registry import ModelRegistry

log = logging.getLogger(__name__)

MAX_PLAN_TASKS = 10   # 子任务上限：LLM 输出异常时截断，防止执行阶段被拖爆


PLANNER_PROMPT = """你是任务规划专家。把用户任务拆解成多个可独立执行的子任务。

【输出格式】只输出一个 JSON 对象，不要任何多余文字（不要代码块标记）：
{
  "tasks": [
    {
      "id": 1,
      "name": "子任务简短名称",
      "description": "具体要做什么，写清楚",
      "depends_on": [],
      "capability": "code | reasoning | bulk | translation | research"
    }
  ]
}

【规则】
1. 子任务 3~7 个，尽量拆细、可独立执行
2. depends_on 填前置子任务 id 列表（无依赖填 []）
3. capability 是完成该子任务需要的模型能力，从上面枚举里选最贴切的
4. 只输出 JSON"""


@dataclass
class SubTask:
    """单个子任务。"""
    id: int
    name: str
    description: str
    depends_on: List[int] = field(default_factory=list)
    capability: str = "reasoning"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "depends_on": self.depends_on,
            "capability": self.capability,
        }


@dataclass
class Plan:
    """一次任务拆解的结果。"""
    tasks: List[SubTask]
    planner_model: str = ""
    raw_text: str = ""
    planning_cost: float = 0.0
    planning_tokens: int = 0

    def get(self, task_id: int) -> Optional[SubTask]:
        for t in self.tasks:
            if t.id == task_id:
                return t
        return None

    def roots(self) -> List[SubTask]:
        """没有依赖的子任务（M3 DAG 并行执行时从这里起步）"""
        return [t for t in self.tasks if not t.depends_on]

    def summary(self) -> str:
        lines = [f"规划完成（{len(self.tasks)} 个子任务，规划模型 {self.planner_model}）:"]
        for t in self.tasks:
            dep = f" 依赖:{t.depends_on}" if t.depends_on else ""
            lines.append(f"  [{t.id}] {t.name} ({t.capability}){dep}")
        return "\n".join(lines)


class MetaRouter:
    """轻量打分函数，选择 Planner 用哪个模型。

    M1 阶段：从配置读 planner_model（默认 DeepSeek，规划是高价值任务）。
    M4 阶段：结合历史效果表打分，这里逻辑不变，只改 _pick()。
    """

    def __init__(self, registry: ModelRegistry):
        self.registry = registry

    def _pick(self) -> str:
        return self.registry.default("planner_model", "deepseek-v4-flash")

    def pick_planner(self) -> str:
        model_id = self._pick()
        if self.registry.has(model_id) and self.registry.configured(model_id):
            return model_id
        # 配置的模型不可用时，回退到第一个配置完整的模型
        for m in self.registry.list():
            if self.registry.configured(m):
                return m
        return model_id  # 最后兜底，调用时再报错


class Planner:
    def __init__(self, client: ModelClient, registry: ModelRegistry):
        self.client = client
        self.registry = registry
        self.meta_router = MetaRouter(registry)

    def plan(self, task: str, max_retries: int = 2) -> Plan:
        """拆解任务。失败时兜底为单任务直通（不会让调用方崩溃）。"""
        planner_model = self.meta_router.pick_planner()
        messages = [
            {"role": "system", "content": PLANNER_PROMPT},
            {"role": "user", "content": f"任务：{task}"},
        ]
        planning_cost = 0.0
        planning_tokens = 0

        for attempt in range(max_retries + 1):
            resp = self.client.chat(planner_model, messages, max_tokens=1024)
            planning_cost += resp.cost
            planning_tokens += resp.total_tokens()
            if not resp.success:
                continue
            tasks = self._parse(resp.content)
            if tasks:
                tasks = self._sanitize_deps(tasks)
                if len(tasks) > MAX_PLAN_TASKS:
                    log.warning(f"[WARN] 规划输出子任务 {len(tasks)} 个，超过上限 {MAX_PLAN_TASKS}，已截断")
                    tasks = tasks[:MAX_PLAN_TASKS]
                return Plan(tasks=tasks, planner_model=planner_model, raw_text=resp.content,
                            planning_cost=planning_cost, planning_tokens=planning_tokens)
            # 没解析出 JSON，把上一轮回复补成 assistant 再追加纠错（避免连续两条 user，
            # 部分上游 API 对相邻同角色消息会报错或语义漂移），然后重试。
            if resp.content:
                messages.append({"role": "assistant", "content": resp.content[:2000]})
            messages.append({
                "role": "user",
                "content": "你刚才的输出不是合法 JSON。只输出 {\"tasks\": [...]} 格式，不要任何多余文字。",
            })

        # 兜底：单任务直通
        return Plan(
            tasks=[SubTask(id=1, name=task, description=task, depends_on=[], capability="reasoning")],
            planner_model=planner_model,
            planning_cost=planning_cost,
            planning_tokens=planning_tokens,
        )

    @staticmethod
    def _sanitize_deps(tasks: List[SubTask]) -> List[SubTask]:
        """校验并修复 LLM 拆出的依赖：坏 id 移除、环断开、重复 id 重编号，并显式 WARN。

        商用要求：计划本身有问题必须暴露，不能静默兜底。
        """
        ids = {t.id for t in tasks}
        changed = False

        # 0) 重复 id 修复：LLM 可能让两个子任务共用同一 id，executor 按 id 建字典时
        #    会静默覆盖、少跑一个子任务。保留首次出现的 id，后续重复项重新编号。
        seen: set = set()
        for t in tasks:
            if t.id in seen:
                new_id = max(ids) + 1
                while new_id in seen or new_id in ids:
                    new_id += 1
                log.warning(f"[WARN] 子任务 id 重复({t.id})，重新编号为 {new_id}，避免静默覆盖")
                t.id = new_id
                ids.add(new_id)
                changed = True
            seen.add(t.id)

        # 1) 移除引用不存在子任务的依赖
        for t in tasks:
            bad = [d for d in t.depends_on if d not in ids]
            if bad:
                t.depends_on = [d for d in t.depends_on if d in ids]
                log.warning(f"[WARN] 子任务[{t.id}] 依赖了不存在的子任务 {bad}，已移除")
                changed = True

        # 2) 拓扑排序检测环；环上节点清空依赖（降级为可并行根任务）
        indeg = {t.id: 0 for t in tasks}
        adj: dict = defaultdict(list)
        for t in tasks:
            for d in t.depends_on:
                adj[d].append(t.id)
                indeg[t.id] += 1
        queue = [tid for tid, deg in indeg.items() if deg == 0]
        topo = []
        while queue:
            cur = queue.pop()
            topo.append(cur)
            for nxt in adj[cur]:
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    queue.append(nxt)

        if len(topo) != len(ids):
            in_cycle = set(ids) - set(topo)
            for t in tasks:
                if t.id in in_cycle:
                    log.warning(f"[WARN] 子任务[{t.id}] 参与依赖环，已清空依赖改为可并行执行")
                    t.depends_on = []
            changed = True

        if changed:
            log.warning("[WARN] 规划依赖已修复，继续执行")
        return tasks

    def _parse(self, text: str) -> Optional[List[SubTask]]:
        text = (text or "").strip()
        m = re.search(r"\{.*\}", text, re.S)   # 容忍 LLM 输出多余文字/代码块
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
        raw_tasks = data.get("tasks")
        if not isinstance(raw_tasks, list):
            return None
        tasks: List[SubTask] = []
        used: set = set()   # 已占用的 id，无 id 任务自动选最小空闲号，避免撞显式 id
        for rt in raw_tasks:
            if not isinstance(rt, dict):
                continue
            default_id = 1
            while default_id in used:
                default_id += 1
            try:
                st = self._parse_task(rt, default_id)
            except (ValueError, TypeError):
                # LLM 输出本质不可信：id 写成 "task-1"、depends_on 塞字符串都算正常偏差。
                # 单条解析失败不能崩整个 plan()，跳过该条并 WARN，让上层重试/兜底生效。
                log.warning(f"[WARN] 子任务字段解析失败已跳过: id={rt.get('id')!r} name={rt.get('name')!r}")
                continue
            tasks.append(st)
            used.add(st.id)
        return tasks or None

    @staticmethod
    def _parse_task(rt: dict, default_id: int) -> SubTask:
        """单条子任务字段强转集中在这里。

        - id 非法 → 抛 ValueError，由 _parse 捕获（该条跳过，不崩 plan()）
        - depends_on 里混入非数字 → 过滤掉并 WARN，尽量保住这条任务本身
        """
        raw_id = rt.get("id")
        tid = int(raw_id) if raw_id not in (None, "") else default_id
        deps = []
        for x in (rt.get("depends_on") or []):
            try:
                deps.append(int(x))
            except (ValueError, TypeError):
                log.warning(f"[WARN] 子任务[{tid}] 依赖项非法已忽略: {x!r}")
        return SubTask(
            id=tid,
            name=str(rt.get("name", "")).strip(),
            description=str(rt.get("description", "")).strip(),
            depends_on=deps,
            capability=str(rt.get("capability", "reasoning")).strip() or "reasoning",
        )
