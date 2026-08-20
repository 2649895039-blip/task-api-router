"""Allocator — 给子任务分配模型（官方月榜版）

用户决策（2026-08-03）：
- 砍掉 Feedback 学习 / epsilon 探索（动态学习不可预测）
- 全部按官方月榜（config/ranking.yaml，项目每月人工更新）
- 执行时精准路由才是主要的（免费关键词预判只做参考）
输入 SubTask → 静态 ranking → 输出 model_id
"""
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .planner import SubTask
from .registry import ModelRegistry

def _default_ranking_path() -> str:
    """解析默认 ranking 表路径：仓库 config/ 优先，纯 pip 安装则用随包模板。"""
    repo = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "config", "ranking.yaml")
    if os.path.exists(repo):
        return repo
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "ranking.yaml")


DEFAULT_RANKING_PATH = _default_ranking_path()
import logging

log = logging.getLogger(__name__)



@dataclass
class Allocation:
    """分配结果：一个子任务 → 一个 model_id。"""
    subtask_id: int
    model_id: str
    score: float
    reason: str


class Allocator:
    def __init__(self, registry: ModelRegistry, ranking_path: str = DEFAULT_RANKING_PATH):
        self.registry = registry
        self.ranking: Dict[str, List[Tuple[str, float]]] = {}   # capability → [(model_id, score)]
        self.aliases: Dict[str, List[str]] = {}
        self._load_ranking(ranking_path)

    def _load_ranking(self, path: str):
        """读静态 ranking.yaml：capability → 有序模型列表（越靠前越优）"""
        import yaml
        if not os.path.exists(path):
            log.warning("找不到 ranking 表 %s，退回能力标签匹配", path)
            return
        try:
            with open(path, encoding="utf-8") as handle:
                data = yaml.safe_load(handle)
            self.aliases = data.get("aliases", {}) or {}
            caps = data.get("capabilities", {})
            for cap, entries in caps.items():
                ordered = []
                for e in sorted(entries, key=lambda item: (
                    int(item.get("rank", 9999)),
                    -float(item.get("score", 0.0)),
                )):
                    mid = e.get("model")
                    if mid:
                        ordered.append((mid, float(e.get("score", 0.0))))
                if ordered:
                    self.ranking[cap] = ordered
        except Exception as e:
            log.warning("ranking.yaml 解析失败: %s", e)

    def allocate(
        self,
        subtask: SubTask,
        attempted: Optional[List[str]] = None,
        unhealthy: Optional[set] = None,
        strategy: str = "quality",
    ) -> Allocation:
        """为子任务选模型。

        attempted：本次子任务已失败过的模型 id（跳过，用于失败降级重试）。
        unhealthy：本次 run 内已知不可用的模型 id 集合（熔断，后续子任务都跳过）。
        """
        attempted = attempted or []
        skip = set(attempted) | set(unhealthy or ())

        if strategy == "cost":
            matched = [c for c in self.registry.by_capability(subtask.capability)
                       if c.id not in skip and self.registry.configured(c.id)]
            if matched:
                best = min(matched, key=lambda c: (c.cost_per_1k_in + c.cost_per_1k_out, c.id))
                return Allocation(
                    subtask_id=subtask.id, model_id=best.id, score=0.5,
                    reason=f"低成本策略[{subtask.capability}] {best.id}",
                )

        # 1) 静态 ranking 表：按社区共识排名，取第一个配置可用且未跳过/熔断的模型
        for mid, score in self.ranking.get(subtask.capability, []):
            local_id = self._local_model_id(mid)
            if local_id and local_id not in skip:
                return Allocation(
                    subtask_id=subtask.id, model_id=local_id, score=score,
                    reason=f"静态ranking[{subtask.capability}] 官方模型 {mid} → 本地 {local_id}",
                )

        # 2) 没有 ranking 条目或全不可用/已尝试/已熔断 → 能力标签匹配 + 最低成本
        matched = [c for c in self.registry.by_capability(subtask.capability)
                   if c.id not in skip and self.registry.configured(c.id)]
        if matched:
            best = min(matched, key=lambda c: c.cost_per_1k_out)
            return Allocation(
                subtask_id=subtask.id, model_id=best.id, score=0.5,
                reason=f"能力标签[{subtask.capability}] 最低成本 {best.id}",
            )

        # 3) 兜底：默认模型可配置（defaults.executor_default），未设置则取首个可用模型
        fallback = self.registry.default("executor_default", "")
        if fallback and fallback not in skip and self.registry.has(fallback) and self.registry.configured(fallback):
            return Allocation(subtask.id, fallback, 0.0, f"无候选，走默认 {fallback}")
        for m in self.registry.list():
            if m not in skip and self.registry.configured(m):
                return Allocation(subtask.id, m, 0.0, f"无候选，回退首个可用 {m}")

        # 4) 系统内真没有任何可用模型：返回空 model_id，由 Executor 短路为失败，
        #    绝不把一个已知不可用的 model 当结果发出去。
        return Allocation(subtask.id, "", 0.0, "系统内无任何已配置/可用模型")

    def _local_model_id(self, ranked_id: str):
        """将公开榜单模型名映射到本机已有的 provider 配置。"""
        if self.registry.has(ranked_id) and self.registry.configured(ranked_id):
            return ranked_id
        for local_id, public_ids in self.aliases.items():
            if ranked_id in public_ids and self.registry.has(local_id) and self.registry.configured(local_id):
                return local_id
        return None
