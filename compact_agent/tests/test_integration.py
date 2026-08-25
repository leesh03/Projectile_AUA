from __future__ import annotations

import json
import unittest
from pathlib import Path

from agents.policy_agent.nodes.scaffold_adapters import SQLRepairAdapter
from agents.policy_agent.nodes.sql_executor import SQLGuard, SQLGuardError
from agents.policy_agent.nodes.sql_generator import SQLQuery
from agents.policy_agent.nodes.state import AgentConfig, AgentRequest, PolicyAgentState
from agents.policy_agent.scaffolds.llm import ScriptedLLM
from agents.policy_agent.scaffolds.sql_repair import repair_once
from policy_runtime.factory import build_agent
from policy_runtime.runner import SuiteRunner


ROOT = Path(__file__).resolve().parents[1]


class CoreIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = build_agent(ROOT, mode="deterministic")
        cls.cases = {
            item["testcase_id"]: item
            for item in json.loads((ROOT / "data" / "agent_cases.json").read_text(encoding="utf-8"))
        }

    def test_database_fixture_and_verifier_paths(self) -> None:
        for testcase_id in ("E-001", "E-002", "H-016"):
            with self.subTest(testcase_id=testcase_id):
                request = AgentRequest.from_mapping(self.cases[testcase_id])
                run = self.bundle.graph.run(request)
                self.assertTrue(run.state.task_success, run.state.error_message)
                self.assertEqual("PASS", run.state.verifier_status)
                self.assertIn("VERIFY_REASONING", [trace["node_role"] for trace in run.traces])
                self.assertFalse(run.state.config.as_scaffold_config()["planner"])

    def test_state_stub_is_not_present(self) -> None:
        self.assertFalse((ROOT / "agents" / "policy_agent" / "scaffolds" / "_state_stub.py").exists())

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
        payload = json.loads(summary.output_path.read_text(encoding="utf-8"))
        self.assertEqual(2, payload["trial_count"])
        self.assertEqual("subprocess-audit-v1", payload["isolation"])
        manifest = json.loads(
            (summary.output_path.parent / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            "subprocess-audit-v1",
            manifest["run_metadata"]["isolation"],
        )


if __name__ == "__main__":
    unittest.main()
