from __future__ import annotations

import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path

from policy_runtime.access_guard import (
    AgentAccessViolation,
    agent_execution_guard,
)


ROOT = Path(__file__).resolve().parents[1]


class AgentAccessIsolationTests(unittest.TestCase):
    def test_agent_can_read_public_database_and_policy(self) -> None:
        with agent_execution_guard(ROOT):
            self.assertTrue((ROOT / "policies" / "policy_rules.json").read_text(encoding="utf-8"))
            connection = sqlite3.connect(ROOT / "data" / "shop.db")
            try:
                self.assertEqual(1, connection.execute("SELECT 1").fetchone()[0])
            finally:
                connection.close()

    def test_agent_cannot_read_gold_or_oracle_assets(self) -> None:
        forbidden = (
            ROOT / "evaluation" / "private" / "expected_cases.json",
            ROOT / "정책" / "GPT_정책" / "data" / "answer_key.db",
            ROOT / "정책" / "GPT_정책" / "data" / "test_cases.json",
            ROOT / "정책" / "GPT_정책" / "policies" / "policy_oracle.py",
        )
        with agent_execution_guard(ROOT):
            for path in forbidden:
                with self.subTest(path=path), self.assertRaises(AgentAccessViolation):
                    path.read_bytes()

    def test_agent_cannot_spawn_a_bypass_process(self) -> None:
        with agent_execution_guard(ROOT), self.assertRaises(AgentAccessViolation):
            subprocess.run(
                [sys.executable, "-c", "print('should not run')"],
                check=False,
                capture_output=True,
            )

    def test_evaluator_can_read_gold_after_guard_exits(self) -> None:
        gold = ROOT / "evaluation" / "private" / "expected_cases.json"
        with agent_execution_guard(ROOT):
            with self.assertRaises(AgentAccessViolation):
                gold.read_text(encoding="utf-8")
        self.assertTrue(gold.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
