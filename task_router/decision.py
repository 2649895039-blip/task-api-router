"""Zero-cost task screening with one cheap-model fallback for ambiguous tasks."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

from .client import ModelClient
from .models import ModelResponse
from .preclassify import KEYWORDS, preclassify
from .registry import ModelRegistry


CAPABILITIES = {"code", "reasoning", "planning", "translation", "research", "bulk", "general"}
COMPLEX_MARKERS = (
    "整个项目", "完整实现", "系统设计", "架构", "重构", "多步骤", "端到端",
    "先", "然后", "再", "最后", "并且", "依赖", "迁移",
    "architecture", "refactor", "end-to-end", "migration", "multiple steps",
)
TOOL_MARKERS = (
    "写代码", "写脚本", "修改", "编辑", "创建文件", "删除", "运行", "命令",
    "搜索", "查找", "调研", "读取", "打开", "抓取", "爬虫",
    "write", "edit", "create", "delete", "run", "shell", "search", "read", "crawl",
)
CLASSIFIER_PROMPT = """Classify one task for an API router. Return JSON only:
{"capability":"code|reasoning|planning|translation|research|bulk|general",
 "difficulty":"simple|medium|complex", "needs_tools":true|false}
Do not solve the task. Do not explain."""


@dataclass
class RouteDecision:
    capability: str
    difficulty: str
    needs_tools: bool
    strategy: str
    source: str
    reason: str
    classifier_model: str = ""
    classifier_response: Optional[ModelResponse] = None

    def to_dict(self) -> dict:
        response = self.classifier_response
        return {
            "capability": self.capability,
            "difficulty": self.difficulty,
            "needs_tools": self.needs_tools,
            "strategy": self.strategy,
            "source": self.source,
            "reason": self.reason,
            "classifier_model": self.classifier_model,
            "classifier_tokens": response.total_tokens() if response else 0,
            "classifier_cost": round(response.cost, 6) if response else 0.0,
        }


class TaskScreen:
    def __init__(self, client: ModelClient, registry: ModelRegistry):
        self.client = client
        self.registry = registry

    def decide(self, task: str) -> RouteDecision:
        local = self._local_decision(task)
        if local is not None:
            return local
        cheapest = self._cheapest_model()
        if not cheapest:
            return self._fallback(task, "脚本无法确定，且没有可用的分类 API")
        response = self.client.chat(
            cheapest,
            [{"role": "system", "content": CLASSIFIER_PROMPT},
             {"role": "user", "content": task}],
            max_tokens=96,
            temperature=0,
        )
        parsed = self._parse(response.content) if response.success else None
        if not parsed:
            fallback = self._fallback(task, "廉价分类失败，使用本地保守判断")
            fallback.classifier_model = cheapest
            fallback.classifier_response = response
            return fallback
        capability, difficulty, needs_tools = parsed
        return RouteDecision(
            capability, difficulty, needs_tools, self._strategy(capability, difficulty),
            "cheap_api", "本地规则无法确定，由最便宜的已配置 API 做一次短分类",
            cheapest, response,
        )

    def _local_decision(self, task: str) -> Optional[RouteDecision]:
        pre = preclassify(task)
        text = (task or "").lower()
        hit_caps = [cap for cap, keywords in KEYWORDS.items()
                    if any(keyword.lower() in text for keyword in keywords)]
        if not hit_caps or (len(hit_caps) > 1 and pre["score"] <= 0.34):
            return None
        marker_count = sum(1 for marker in COMPLEX_MARKERS if marker in text)
        difficulty = ("complex" if len(text) > 240 or marker_count >= 2
                      else "simple" if len(text) <= 80 and marker_count == 0 else "medium")
        capability = pre["capability"]
        needs_tools = capability in {"code", "research"} or any(marker in text for marker in TOOL_MARKERS)
        return RouteDecision(
            capability, difficulty, needs_tools, self._strategy(capability, difficulty),
            "local_script", f"本地关键词命中: {', '.join(pre['hits'])}",
        )

    def _fallback(self, task: str, reason: str) -> RouteDecision:
        text = (task or "").lower()
        return RouteDecision("general", "medium", any(m in text for m in TOOL_MARKERS),
                             "quality", "fallback", reason)

    def _cheapest_model(self) -> str:
        candidates = [self.registry.get(mid) for mid in self.registry.list()
                      if self.registry.configured(mid)]
        if not candidates:
            return ""
        return min(candidates, key=lambda c: (c.cost_per_1k_in + c.cost_per_1k_out, c.id)).id

    @staticmethod
    def _strategy(capability: str, difficulty: str) -> str:
        return "cost" if difficulty == "simple" or capability in {"bulk", "translation"} else "quality"

    @staticmethod
    def _parse(text: str):
        match = re.search(r"\{.*?\}", text or "", re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except (TypeError, json.JSONDecodeError):
            return None
        capability = str(data.get("capability", "")).lower()
        difficulty = str(data.get("difficulty", "")).lower()
        needs_tools = data.get("needs_tools")
        if capability not in CAPABILITIES or difficulty not in {"simple", "medium", "complex"}:
            return None
        if not isinstance(needs_tools, bool):
            return None
        return capability, difficulty, needs_tools
