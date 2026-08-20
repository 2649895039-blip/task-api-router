"""免费关键词预判（0 token，只做参考）

用户决策（2026-08-03）：先做一次简单的对话分析，不消耗 token，
只用脚本几个明显词语（写代码/翻译/调研等）给个参考方向。
真正精准的路由在执行时（Allocator 静态 ranking）才算数。
"""
import re
from typing import Dict, List

# capability → 关键词（中文优先，英文兜底）
KEYWORDS: Dict[str, List[str]] = {
    "code": [
        "写代码", "写脚本", "写个", "代码", "调试", "爬虫", "抓取", "修复", "bug",
        "开发", "编程", "实现", "函数", "脚本", "报错", "异常", "重构",
        "code", "script", "debug", "crawler", "python", "api", "fix", "error",
    ],
    "reasoning": [
        "分析", "总结", "对比", "评估", "方案", "建议", "设计", "架构", "策略",
        "计划", "为什么", "利弊", "怎么选", "是否值得",
        "analysis", "strategy", "design", "compare", "evaluate", "plan",
    ],
    "translation": [
        "翻译", "润色", "改写", "翻译成", "译成", "英文", "中文", "文案",
        "印尼语", "泰语", "越南语", "马来语", "英语",
        "translate", "rewrite", "localize",
    ],
    "research": [
        "调研", "研究", "调查", "市场", "竞品", "趋势", "资料", "查", "行情",
        "research", "market", "trend", "competitor", "survey",
    ],
    "bulk": [
        "批量", "大量", "批量生成", "100个", "200个", "500个", "1000个", "全部", "列表",
        "循环", "逐个", "每一条",
        "batch", "bulk", "all", "generate all", "loop",
    ],
}

# 预判出来的 capability → 建议方向（只做提示，不绑定任何具体模型，
# 实际以 Allocator 静态 ranking 从你本机已配置的模型里选）
CAPABILITY_MODEL_HINT = {
    "code": "按你的配置选高推理模型",
    "reasoning": "按你的配置选高推理模型",
    "planning": "按你的配置选高推理模型",
    "translation": "按你的配置选性价比模型",
    "research": "按你的配置选性价比模型",
    "bulk": "按你的配置选性价比模型",
}


def preclassify(task: str) -> dict:
    """输入任务文本，输出免费预判结果（0 token）。

    返回:
      {
        "capability": 命中的能力标签（或 "general"）,
        "score": 置信度 0~1,
        "hits": 命中的关键词列表,
        "model_hint": 建议模型（只做参考）,
      }
    """
    text = (task or "").lower()
    best_cap, best_hits, best_n = "general", [], 0
    for cap, kws in KEYWORDS.items():
        hits = [kw for kw in kws if kw.lower() in text]
        # 命中越多权重越高；单个高信息量关键词也值得注意
        if len(hits) > best_n:
            best_cap, best_hits, best_n = cap, hits, len(hits)
    score = min(1.0, best_n / 3)  # 3 个关键词就算高置信
    return {
        "capability": best_cap,
        "score": round(score, 2),
        "hits": best_hits,
        "model_hint": CAPABILITY_MODEL_HINT.get(best_cap, "按你的配置选（默认性价比优先）"),
    }
