"""Deterministic offline value benchmark for README and smoke testing."""
from __future__ import annotations
import json
from pathlib import Path
from demo_route import MODELS, estimate_cost

TASKS = (
    ("code_simple", "deepseek-v4-flash", 220, 300),
    ("code_complex", "claude-sonnet", 700, 1100),
    ("translation", "deepseek-v4-flash", 900, 1100),
    ("research", "deepseek-v4-flash", 800, 700),
    ("bulk", "deepseek-v4-flash", 1200, 600),
)

def build_report() -> dict:
    routed = sum(estimate_cost(MODELS[m], i, o) for _, m, i, o in TASKS)
    baseline = sum(estimate_cost(MODELS["claude-sonnet"], i, o) for _, _, i, o in TASKS)
    return {"mode": "illustrative_offline", "task_count": len(TASKS),
            "routed_cost_usd": round(routed, 6), "baseline_cost_usd": round(baseline, 6),
            "estimated_saving_percent": round((baseline-routed)/baseline*100, 1),
            "tasks": [{"id": k, "model": m, "input_tokens": i, "output_tokens": o} for k,m,i,o in TASKS],
            "limitations": "This is not a production benchmark: tasks, token counts, prices, and routing are fixed fixtures. Measure your own workload before making savings claims."}

def main() -> None:
    report = build_report()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    Path("benchmark-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\nWrote benchmark-report.json (offline; no API calls)")

if __name__ == "__main__":
    main()
