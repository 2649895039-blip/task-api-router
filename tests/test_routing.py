import tempfile
import unittest
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import yaml

from task_router.action_guard import ActionGuard, check_action_json
from task_router.allocator import Allocator
from task_router.decision import TaskScreen
from task_router.executor import DAGExecutor
from task_router.models import ModelResponse
from task_router.models import provider_error_metadata
from task_router.planner import Plan, SubTask
from task_router.registry import ModelRegistry
from task_router.runlog import RunLog
from task_router.reporter import Reporter


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
    def test_offline_benchmark_is_deterministic_and_explicitly_illustrative(self):
        from benchmark_route import build_report
        report = build_report()
        self.assertEqual(report["task_count"], 5)
        self.assertEqual(report["mode"], "illustrative_offline")
        self.assertGreater(report["baseline_cost_usd"], report["routed_cost_usd"])
        self.assertIn("not a production benchmark", report["limitations"])
        self.assertEqual(report, build_report())

    def test_orchestrator_rejects_empty_or_oversized_tasks_before_provider_call(self):
        from task_router.orchestrator import RouterOrchestrator
        with tempfile.TemporaryDirectory() as tmp:
            registry = make_registry(tmp)
            orch = RouterOrchestrator(registry._path if hasattr(registry, '_path') else str(Path(tmp) / 'models.yaml'), tmp)
            with self.assertRaisesRegex(ValueError, "任务不能为空"):
                orch.run("   ")
            with self.assertRaisesRegex(ValueError, "任务过长"):
                orch.run("x" * 100001)

    def test_release_manifest_validator_accepts_current_repository(self):
        from scripts.verify_release import validate_repository
        errors = validate_repository(Path(__file__).parents[1])
        self.assertEqual([], errors)

    def test_release_contains_identity_and_attribution_notices(self):
        root = Path(__file__).parents[1]
        self.assertTrue((root / "NOTICE").is_file())
        self.assertTrue((root / "TRADEMARKS.md").is_file())
        self.assertIn("2649895039-blip/task-api-router", (root / "TRADEMARKS.md").read_text(encoding="utf-8"))

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

    def test_hook_uses_native_permission_decisions(self):
        hook = Path(__file__).parents[1] / "hooks" / "action_guard_hook.py"
        payload = {"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}}
        result = subprocess.run(
            [sys.executable, str(hook)], input=json.dumps(payload), text=True,
            capture_output=True, check=False, encoding="utf-8", errors="replace",
            env={**__import__("os").environ, "PYTHONUTF8": "1"},
        )
        self.assertEqual(2, result.returncode)
        output = json.loads(result.stdout)
        self.assertEqual("deny", output["hookSpecificOutput"]["permissionDecision"])

        payload["tool_input"]["command"] = "echo hello"
        result = subprocess.run(
            [sys.executable, str(hook)], input=json.dumps(payload), text=True,
            capture_output=True, check=False, encoding="utf-8", errors="replace",
            env={**__import__("os").environ, "PYTHONUTF8": "1"},
        )
        self.assertEqual(0, result.returncode)
        output = json.loads(result.stdout)
        self.assertEqual("allow", output["hookSpecificOutput"]["permissionDecision"])

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
                self.assertEqual("[redacted]", log["task"])

    def test_failed_dependency_is_not_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = make_registry(tmp)
            ranking = Path(tmp) / "ranking.yaml"
            ranking.write_text(yaml.safe_dump({
                "capabilities": {"code": [{"model": "cheap", "rank": 1}]}
            }), encoding="utf-8")
            client = FakeClient([ModelResponse.fail("cheap", "bad request")])
            executor = DAGExecutor(client, Allocator(registry, str(ranking)), max_retries=0)
            plan = Plan([
                SubTask(1, "first", "first", [], "code"),
                SubTask(2, "second", "second", [1], "code"),
            ])
            report = executor.execute(plan)
            self.assertFalse(report.results[1].response.success)
            self.assertFalse(report.results[2].response.success)
            self.assertIn("上游依赖失败", report.results[2].response.error)
            self.assertEqual(1, len(client.calls))

    def test_retryable_failure_retries_same_model_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = make_registry(tmp)
            client = FakeClient([
                ModelResponse.fail("cheap", "rate limited", status_code=429, retryable=True),
                ModelResponse(model_id="cheap", content="ok"),
            ])
            executor = DAGExecutor(client, Allocator(registry), max_retries=0,
                                   retry_base_delay=0)
            report = executor.execute(Plan([SubTask(1, "task", "task", [], "code")]),
                                      strategy="cost")
            self.assertTrue(report.results[1].response.success)
            self.assertEqual(2, len(client.calls))

    def test_concurrency_limit(self):
        class ConcurrentClient(FakeClient):
            def __init__(self):
                super().__init__()
                self.active = 0
                self.peak = 0
                self.lock = threading.Lock()

            def chat(self, model_id, messages, **kwargs):
                with self.lock:
                    self.active += 1
                    self.peak = max(self.peak, self.active)
                time.sleep(0.03)
                with self.lock:
                    self.active -= 1
                return ModelResponse(model_id=model_id, content="ok")

        with tempfile.TemporaryDirectory() as tmp:
            registry = make_registry(tmp)
            client = ConcurrentClient()
            executor = DAGExecutor(client, Allocator(registry), max_concurrency=2)
            tasks = [SubTask(i, f"t{i}", "", [], "code") for i in range(1, 7)]
            executor.execute(Plan(tasks), strategy="cost")
            self.assertLessEqual(client.peak, 2)
            self.assertGreaterEqual(client.peak, 1)

    def test_budget_stops_later_dag_wave(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = make_registry(tmp)
            client = FakeClient([
                ModelResponse(model_id="cheap", content="ok", cost=0.2),
            ])
            executor = DAGExecutor(client, Allocator(registry), max_cost_usd=0.1)
            plan = Plan([
                SubTask(1, "first", "", [], "code"),
                SubTask(2, "second", "", [1], "code"),
            ])
            report = executor.execute(plan, strategy="cost")
            self.assertTrue(report.budget_exhausted)
            self.assertIn("预算", report.results[2].response.error)
            self.assertEqual(1, len(client.calls))

    def test_reporter_redacts_content_by_default(self):
        from task_router.executor import ExecutionReport, TaskResult
        with tempfile.TemporaryDirectory() as tmp:
            plan = Plan([SubTask(1, "secret task", "", [], "code")])
            response = ModelResponse(model_id="cheap", content="secret output")
            report = ExecutionReport(plan, {}, {1: TaskResult(1, "cheap", response)}).compute()
            path = str(Path(tmp) / "history.jsonl")
            record = Reporter(path).emit(plan, report, task="private customer data")
            self.assertEqual("[redacted]", record["task"])
            self.assertEqual("[redacted]", record["tasks"][0]["name"])
            self.assertNotIn("private customer data", Path(path).read_text(encoding="utf-8"))

    def test_registry_rejects_invalid_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.yaml"
            path.write_text(yaml.safe_dump({
                "models": {"bad": {"base_url": "file:///secret", "api_key": "x"}}
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "base_url"):
                ModelRegistry(str(path))

    def test_provider_error_metadata(self):
        class RateLimitError(Exception):
            status_code = 429

        class AuthError(Exception):
            status_code = 401

        self.assertEqual((429, True), provider_error_metadata(RateLimitError()))
        self.assertEqual((401, False), provider_error_metadata(AuthError()))

    def test_supported_sdk_clients_can_be_constructed(self):
        from anthropic import Anthropic
        from openai import OpenAI
        from task_router.adapters.openai_compat import make_http_client
        from task_router.models import ModelConfig

        cfg = ModelConfig(id="test", base_url="https://example.test", api_key="test")
        http_client = make_http_client(cfg)
        client = OpenAI(api_key="test", base_url=cfg.base_url, http_client=http_client)
        client.close()
        http_client = make_http_client(cfg)
        client = Anthropic(api_key="test", base_url=cfg.base_url, http_client=http_client)
        client.close()

    def test_registry_rejects_invalid_environment_variable_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.yaml"
            path.write_text(yaml.safe_dump({
                "models": {"bad": {
                    "base_url": "https://example.test", "api_key_env": "BAD-NAME"
                }}
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "环境变量"):
                ModelRegistry(str(path))

    def test_route_only_is_offline_and_allocates_model(self):
        from task_router.orchestrator import RouterOrchestrator
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "models.yaml"
            config.write_text(yaml.safe_dump({
                "defaults": {"executor_default": "cheap"},
                "models": {
                    "cheap": {
                        "base_url": "https://example.test/v1",
                        "api_key_env": "TEST_ROUTER_KEY",
                        "capabilities": ["code", "general", "translation", "bulk"],
                        "cost_per_1k_in": 0.1, "cost_per_1k_out": 0.2,
                    },
                    "strong": {
                        "base_url": "https://example.test/v1",
                        "api_key_env": "TEST_ROUTER_KEY",
                        "capabilities": ["code", "reasoning", "general"],
                        "cost_per_1k_in": 1.0, "cost_per_1k_out": 2.0,
                    },
                },
            }), encoding="utf-8")
            import os
            os.environ["TEST_ROUTER_KEY"] = "x"
            ranking = Path(tmp) / "ranking.yaml"
            ranking.write_text(yaml.safe_dump({
                "capabilities": {
                    "code": [{"model": "strong", "rank": 1}, {"model": "cheap", "rank": 2}],
                    "translation": [{"model": "cheap", "rank": 1}],
                }
            }), encoding="utf-8")
            orch = RouterOrchestrator(str(config), tmp)
            orch.allocator = __import__("task_router.allocator", fromlist=["Allocator"]).Allocator(
                orch.registry, str(ranking)
            )
            preview = orch.route_only("写一个 Python 函数解析 JSON")
            self.assertFalse(preview.classifier_would_call)
            self.assertEqual("code", preview.decision.capability)
            self.assertEqual("local_script", preview.decision.source)
            # Simple short code tasks use the cost strategy → cheapest configured model.
            self.assertEqual("cost", preview.decision.strategy)
            self.assertEqual("cheap", preview.model_id)

            complex_preview = orch.route_only(
                "重构整个项目代码，先写一个解析模块，然后调试异常，最后修复 bug"
            )
            self.assertEqual("code", complex_preview.decision.capability)
            self.assertEqual("complex", complex_preview.decision.difficulty)
            self.assertEqual("quality", complex_preview.decision.strategy)
            self.assertEqual("strong", complex_preview.model_id)

            ambiguous = orch.route_only("帮我处理一下这个")
            self.assertTrue(ambiguous.classifier_would_call)
            self.assertEqual("general", ambiguous.decision.capability)
            self.assertEqual("", ambiguous.model_id)
            self.assertIn("分类", ambiguous.allocation_reason)

    def test_doctor_reports_core_checks(self):
        from task_router.doctor import run_doctor
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "models.example.yaml"
            config.write_text(yaml.safe_dump({
                "models": {
                    "demo": {
                        "base_url": "https://example.test/v1",
                        "api_key_env": "TEST_ROUTER_KEY_MISSING",
                        "capabilities": ["general"],
                    }
                }
            }), encoding="utf-8")
            ranking = Path(tmp) / "ranking.yaml"
            ranking.write_text("capabilities: {}\n", encoding="utf-8")
            package_dir = Path(__file__).parents[1] / "task_router"
            checks = run_doctor(str(config), str(Path(tmp) / "data"), package_dir=str(package_dir))
            names = {c.name for c in checks}
            self.assertIn("python_version", names)
            self.assertIn("model_config", names)
            self.assertIn("models_registered", names)
            self.assertIn("data_dir", names)
            self.assertIn("offline_demo", names)
            by_name = {c.name: c for c in checks}
            self.assertTrue(by_name["python_version"].ok)
            self.assertTrue(by_name["models_registered"].ok)
            self.assertFalse(by_name["models_configured"].ok)

    def test_doctor_treats_missing_repository_assets_as_normal_for_wheel_install(self):
        from task_router.doctor import run_doctor
        with tempfile.TemporaryDirectory() as tmp:
            package_dir = Path(tmp) / "site" / "task_router"
            config_dir = package_dir / "config"
            config_dir.mkdir(parents=True)
            (config_dir / "models.example.yaml").write_text(yaml.safe_dump({
                "models": {"demo": {
                    "base_url": "https://example.test/v1",
                    "api_key": "test-only",
                    "capabilities": ["general"],
                }}
            }), encoding="utf-8")
            (config_dir / "ranking.yaml").write_text("capabilities: {}\n", encoding="utf-8")
            checks = run_doctor(
                str(config_dir / "models.example.yaml"),
                str(Path(tmp) / "data"),
                package_dir=str(package_dir),
            )
            by_name = {c.name: c for c in checks}
            self.assertTrue(by_name["action_guard_hook"].ok)
            self.assertTrue(by_name["offline_demo"].ok)
            self.assertIn("--route", by_name["offline_demo"].detail)

    def test_route_json_stdout_is_machine_readable_with_auto_key_config(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            key_config = Path(tmp) / "keys.json"
            key_config.write_text(json.dumps({
                "demo": {"api_key": "test-only", "api_key_env": "ROUTER_JSON_TEST_KEY"}
            }), encoding="utf-8")
            env = os.environ.copy()
            env["TASK_ROUTER_API_CONFIG"] = str(key_config)
            env.pop("ROUTER_JSON_TEST_KEY", None)
            result = subprocess.run(
                [sys.executable, "-m", "task_router", "--route", "写一个 Python 函数", "--json"],
                cwd=Path(__file__).parents[1], env=env, capture_output=True, check=False,
            )
            stdout = result.stdout.decode("utf-8")
            stderr = result.stderr.decode("utf-8")
            self.assertEqual(0, result.returncode, stderr)
            payload = json.loads(stdout)
            self.assertEqual("code", payload["capability"])

    def test_stats_aggregates_history_without_provider_calls(self):
        import os
        from task_router.cli import compute_stats
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / "history.jsonl"
            records = [
                {
                    "total_cost": 0.01,
                    "total_tokens": 1000,
                    "routing": {"capability": "code", "strategy": "quality", "source": "local_script"},
                    "tasks": [
                        {"model_id": "strong", "success": True, "cost": 0.01, "tokens": 1000},
                    ],
                },
                {
                    "total_cost": 0.002,
                    "total_tokens": 500,
                    "routing": {"capability": "translation", "strategy": "cost", "source": "local_script"},
                    "tasks": [
                        {"model_id": "cheap", "success": True, "cost": 0.002, "tokens": 500},
                    ],
                },
            ]
            history.write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
                encoding="utf-8",
            )
            registry = make_registry(tmp)
            # Force configured models for baseline comparison
            os.environ["X"] = "x"
            for mid in registry.list():
                cfg = registry.get(mid)
                cfg.api_key = "x"
            stats = compute_stats(str(history), registry)
            self.assertEqual(2, stats["runs"])
            self.assertAlmostEqual(0.012, stats["total_cost_usd"], places=6)
            self.assertEqual(1500, stats["total_tokens"])
            self.assertEqual(2, stats["success_subtasks"])
            self.assertEqual(0, stats["failed_subtasks"])
            self.assertIn("code", stats["by_capability"])
            self.assertIn("translation", stats["by_capability"])
            self.assertIn("strong", stats["by_model"])
            self.assertIn("cheap", stats["by_model"])
            self.assertEqual(2, stats["by_source"].get("local_script"))
            self.assertAlmostEqual(3.0, stats["illustrative_baseline_cost_usd"], places=6)
            missing = compute_stats(str(Path(tmp) / "missing.jsonl"), None)
            self.assertEqual("no_history", missing.get("error"))

    def test_stats_skips_structurally_invalid_history_records(self):
        from task_router.cli import compute_stats
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / "history.jsonl"
            history.write_text(
                '{"total_cost":"bad","total_tokens":100,"routing":{},"tasks":[]}\n'
                '{"total_cost":0.25,"total_tokens":50,"routing":{},"tasks":[]}\n',
                encoding="utf-8",
            )
            stats = compute_stats(str(history))
            self.assertEqual(1, stats["runs"])
            self.assertEqual(1, stats["skipped_records"])
            self.assertEqual(0.25, stats["total_cost_usd"])


if __name__ == "__main__":
    unittest.main()
