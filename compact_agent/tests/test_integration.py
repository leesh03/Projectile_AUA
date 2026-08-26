from __future__ import annotations

import hashlib
import json
import sqlite3
import unittest
from datetime import date
from pathlib import Path
from zipfile import ZipFile

from agents.policy_agent.nodes.scaffold_adapters import SQLRepairAdapter
from agents.policy_agent.nodes.sql_executor import SQLGuard, SQLGuardError
from agents.policy_agent.nodes.sql_generator import SQLQuery
from agents.policy_agent.nodes.state import AgentConfig, AgentRequest, PolicyAgentState
from agents.policy_agent.scaffolds.llm import ScriptedLLM
from agents.policy_agent.scaffolds.sql_repair import repair_once
from policy_runtime.factory import build_agent
from policy_runtime.runner import SuiteRunner
from scripts.build_submission import build_submission
from scripts.refresh_package_manifest import included


ROOT = Path(__file__).resolve().parents[1]


class CoreIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = build_agent(ROOT, mode="deterministic")
        cls.cases = {
            item["testcase_id"]: item
            for item in json.loads((ROOT / "data" / "agent_cases.json").read_text(encoding="utf-8"))
        }

    def test_database_sql_and_verifier_paths(self) -> None:
        for testcase_id in ("E-001", "E-002", "H-016"):
            with self.subTest(testcase_id=testcase_id):
                request = AgentRequest.from_mapping(self.cases[testcase_id])
                run = self.bundle.graph.run(request)
                self.assertTrue(run.state.task_success, run.state.error_message)
                self.assertEqual("PASS", run.state.verifier_status)
                self.assertIn("VERIFY_REASONING", [trace["node_role"] for trace in run.traces])
                self.assertFalse(run.state.config.as_scaffold_config()["planner"])

    def test_testcase_id_never_changes_facts_or_policy_result(self) -> None:
        former_fixture_ids = (
            "E-002",
            "E-004",
            "E-005",
            "E-008",
            "E-009",
            "E-010",
            "E-011",
            "E-018",
            "E-020",
        )
        for testcase_id in former_fixture_ids:
            with self.subTest(testcase_id=testcase_id):
                original = dict(self.cases[testcase_id])
                renamed = dict(original)
                renamed["testcase_id"] = f"X-{testcase_id}"
                first = self.bundle.graph.run(AgentRequest.from_mapping(original))
                second = self.bundle.graph.run(AgentRequest.from_mapping(renamed))
                self.assertTrue(first.state.task_success, first.state.error_message)
                self.assertTrue(second.state.task_success, second.state.error_message)
                self.assertEqual(first.state.facts, second.state.facts)
                self.assertEqual(first.state.decision, second.state.decision)
                self.assertEqual(first.state.policy_clauses, second.state.policy_clauses)

    def test_regression_database_replaces_testcase_fixture_adapter(self) -> None:
        self.assertFalse((ROOT / "data" / "adapter_fixtures.json").exists())
        self.assertFalse((ROOT / "policy_runtime" / "fixtures.py").exists())
        connection = sqlite3.connect(ROOT / "data" / "shop.db")
        try:
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(orders)").fetchall()
            }
        finally:
            connection.close()
        self.assertTrue({"lookup_order_item_id", "record_present"}.issubset(columns))

    def test_interactive_request_uses_a_valid_date(self) -> None:
        request = AgentRequest.interactive(
            "이 상품을 환불하고 싶어요.",
            order_item_id="OI-E-001",
            evaluation_date="2026-08-15",
            requested_amount=10000,
        )
        self.assertNotEqual("UNSET", request.trusted_context["evaluation_date"])
        run = self.bundle.graph.run(request)
        self.assertTrue(run.state.task_success, run.state.error_message)
        self.assertEqual("APPROVE", run.state.decision)

        default_request = AgentRequest.interactive(
            "이 상품을 환불하고 싶어요.",
            order_item_id="OI-E-001",
            requested_amount=10000,
        )
        date.fromisoformat(default_request.trusted_context["evaluation_date"])
        default_run = self.bundle.graph.run(default_request)
        self.assertTrue(default_run.state.task_success, default_run.state.error_message)
        self.assertNotIn("RFC3339", default_run.state.response)

    def test_state_stub_is_not_present(self) -> None:
        self.assertFalse((ROOT / "agents" / "policy_agent" / "scaffolds" / "_state_stub.py").exists())

    def test_asset_manifest_hashes_are_current_and_lf_stable(self) -> None:
        manifest = json.loads((ROOT / "data" / "asset_manifest.json").read_text(encoding="utf-8"))
        for relative_path, expected_hash in manifest["files"].items():
            path = ROOT / relative_path
            with self.subTest(path=relative_path):
                payload = path.read_bytes()
                self.assertEqual(expected_hash, hashlib.sha256(payload).hexdigest())
                if path.suffix == ".json":
                    self.assertNotIn(b"\r\n", payload)

        source_manifest = json.loads(
            (ROOT / "data" / "source_version_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            manifest["files"]["data/agent_cases.json"],
            source_manifest["artifact_sha256"]["data/agent_cases.json"],
        )

    def test_development_package_manifest_hashes_are_current(self) -> None:
        path = ROOT / "PACKAGE_MANIFEST.json"
        if not path.is_file():
            self.skipTest("development package manifest is intentionally absent")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        listed = {entry["path"] for entry in manifest["files"]}
        current = {
            candidate.relative_to(ROOT).as_posix()
            for candidate in ROOT.rglob("*")
            if candidate.is_file() and included(candidate)
        }
        self.assertEqual(current, listed)
        for entry in manifest["files"]:
            file_path = ROOT / entry["path"]
            with self.subTest(path=entry["path"]):
                payload = file_path.read_bytes()
                self.assertEqual(entry["bytes"], len(payload))
                self.assertEqual(entry["sha256"], hashlib.sha256(payload).hexdigest())

    def test_sql_guard_blocks_writes_and_multiple_statements(self) -> None:
        guard = SQLGuard(("orders",))
        for sql in ("DELETE FROM orders", "SELECT * FROM orders; DROP TABLE orders"):
            with self.subTest(sql=sql), self.assertRaises(SQLGuardError):
                guard.validate(sql)

    def test_real_sql_repair_scaffold_is_wired_by_adapter(self) -> None:
        request = AgentRequest.from_mapping(self.cases["E-001"])
        state = PolicyAgentState(request, config=AgentConfig())
        state.context["database_schema"] = {"orders": ["order_item_id"]}
        llm = ScriptedLLM(["SELECT order_item_id FROM orders WHERE order_item_id = ?"])
        adapter = SQLRepairAdapter(repair_once, llm)
        repaired = adapter(
            state,
            SQLQuery("order", "SELEC * FROM orders", ("OI-E-001",)),
            RuntimeError("syntax error"),
        )
        self.assertTrue(repaired.sql.startswith("SELECT"))
        self.assertEqual(("OI-E-001",), repaired.parameters)
        self.assertEqual(1, llm.call_count)

    def test_runner_persists_trial_results(self) -> None:
        output_root = ROOT / "reports" / "test-runs"
        summary = SuiteRunner(ROOT, self.bundle, output_root=output_root).run(limit=2)
        self.assertEqual(2, summary.total_trials)
        self.assertEqual(2, summary.task_successes)
        self.assertEqual(2, summary.policy_correct)
        self.assertEqual(2, summary.engine_consistency)
        if (ROOT / "evaluation" / "private" / "expected_cases.json").is_file():
            self.assertEqual(2, summary.gold_agreements)
            self.assertEqual(2, summary.oracle_agreements)
        else:
            self.assertIsNone(summary.gold_agreements)
            self.assertIsNone(summary.oracle_agreements)
        payload = json.loads(summary.output_path.read_text(encoding="utf-8"))
        self.assertEqual(2, payload["trial_count"])
        self.assertEqual("subprocess-audit-v1", payload["isolation"])
        self.assertIn("metric_definitions", payload)
        manifest = json.loads(
            (summary.output_path.parent / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            "subprocess-audit-v1",
            manifest["run_metadata"]["isolation"],
        )

    def test_submission_builder_excludes_gold_and_past_results(self) -> None:
        output = ROOT / "reports" / "test-temp" / "compact_agent_submission.zip"
        try:
            output = build_submission(output)
            with ZipFile(output) as archive:
                names = set(archive.namelist())
                self.assertIn("SUBMISSION_MANIFEST.json", names)
                self.assertNotIn("evaluation/private/expected_cases.json", names)
                self.assertFalse(any(name.startswith("reports/") for name in names))
                self.assertFalse(any(Path(name).name == ".env" for name in names))
                public_manifest = json.loads(
                    archive.read("data/asset_manifest.json").decode("utf-8")
                )
                self.assertEqual(
                    "public-submission-no-gold", public_manifest["package_scope"]
                )
        finally:
            output.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
