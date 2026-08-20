import tempfile
import unittest
from pathlib import Path

import yaml

from task_router.action_guard import ActionGuard, check_action_json
from task_router.allocator import Allocator
from task_router.decision import TaskScreen
from task_router.executor import DAGExecutor
from task_router.models import ModelResponse
from task_router.planner import Plan, SubTask
from task_router.registry import ModelRegistry
from task_router.runlog import RunLog


class FakeClient:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def chat(self, model_id, messages, **kwargs):
        self.calls.append((model_id, messages, kwargs))
        if self.responses:
            return self.responses.pop(0)
        return ModelResponse(model_id=model_id, content="ok", input_tokens=10, output_tokens=2)


def make_registry(tmp: str) -> ModelRegistry:
    path = Path(tmp) / "models.yaml"
    path.write_text(yaml.safe_dump({
        "defaults": {"executor_default": "cheap"},
        "models": {
            "cheap": {
                "base_url": "https://example.test/v1", "api_key": "x",
                "capabilities": ["code", "general", "translation"],
                "cost_per_1k_in": 0.1, "cost_per_1k_out": 0.2,
            },
            "strong": {
                "base_url": "https://example.test/v1", "api_key": "x",
                "capabilities": ["code", "reasoning", "general"],
                "cost_per_1k_in": 1.0, "cost_per_1k_out": 2.0,
            },
        },
    }), encoding="utf-8")
    return ModelRegistry(str(path))


class RoutingTests(unittest.TestCase):
    def test_clear_task_uses_no_classifier_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = make_registry(tmp)
            client = FakeClient()
            decision = TaskScreen(client, registry).decide("写一个 Python 函数")
            self.assertEqual("local_script", decision.source)
            self.assertEqual("code", decision.capability)
            self.assertEqual("cost", decision.strategy)
            self.assertTrue(decision.needs_tools)
            self.assertEqual([], client.calls)

    def test_ambiguous_task_uses_cheapest_api_once(self):
        response = ModelResponse(
            model_id="cheap",
            content='{"capability":"reasoning","difficulty":"medium","needs_tools":false}',
            input_tokens=20, output_tokens=8, cost=0.01,
        )
        with tempfile.TemporaryDirectory() as tmp:
            registry = make_registry(tmp)
            client = FakeClient([response])
            decision = TaskScreen(client, registry).decide("帮我处理一下这个")
            self.assertEqual("cheap_api", decision.source)
            self.assertEqual("cheap", decision.classifier_model)
            self.assertEqual(1, len(client.calls))
            self.assertEqual(96, client.calls[0][2]["max_tokens"])

    def test_executor_circuit_breaker_resets_each_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = make_registry(tmp)
            ranking = Path(tmp) / "ranking.yaml"
            ranking.write_text(yaml.safe_dump({
                "capabilities": {"code": [{"model": "cheap", "rank": 1}]}
            }), encoding="utf-8")
            client = FakeClient([
                ModelResponse.fail("cheap", "temporary"),
                ModelResponse(model_id="strong", content="fallback"),
                ModelResponse(model_id="cheap", content="recovered"),
            ])
            executor = DAGExecutor(client, Allocator(registry, str(ranking)), max_retries=1)
            plan = Plan([SubTask(1, "code", "code", [], "code")])
            executor.execute(plan)
            executor.execute(plan)
            self.assertEqual("cheap", client.calls[-1][0])

    def test_action_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            guard = ActionGuard(tmp)
            self.assertEqual("allow", guard.check("read", {"path": "a.txt"}).decision)
            self.assertEqual("allow", guard.check("write", {"path": "a.txt"}).decision)
            self.assertEqual("confirm", guard.check("write", {"path": "../a.txt"}).decision)
            self.assertEqual("block", guard.check("shell", {"command": "git reset --hard"}).decision)
            self.assertEqual("allow", check_action_json(
                '{"tool_name":"Write","tool_input":{"file_path":"x.txt"}}', tmp
            ).decision)

    def test_runlog_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            rl = RunLog(tmp)
            for evil in ("..\\secret.json", "../secret", "a/b", "..", ".", ""):
                self.assertIsNone(rl.load_run(evil), f"应拒绝 {evil!r}")

    def test_runlog_save_run_unique_and_roundtrip(self):
        from task_router.executor import ExecutionReport
        with tempfile.TemporaryDirectory() as tmp:
            rl = RunLog(tmp)
            plan = Plan([SubTask(1, "t1", "d1", [], "code")])
            report = ExecutionReport(plan, {}, {})
            report.total_cost = 0.1
            report.total_tokens = 50
            ids = {rl.save_run("任务", plan, report, {}) for _ in range(5)}
            self.assertEqual(5, len(ids))
            for rid in ids:
                log = rl.load_run(rid)
                self.assertEqual(rid, log["run_id"])
                self.assertEqual(0.1, log["total_cost"])


if __name__ == "__main__":
    unittest.main()
