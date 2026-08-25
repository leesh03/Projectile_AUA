from __future__ import annotations

import json
import unittest
from pathlib import Path

from policy_runtime.engine import InputContractError, PolicyEngine


ROOT = Path(__file__).resolve().parents[1]


class PolicyEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = PolicyEngine.from_path(ROOT / "policies" / "policy_rules.json")
        gold_path = ROOT / "evaluation" / "private" / "expected_cases.json"
        cls.cases = (
            json.loads(gold_path.read_text(encoding="utf-8"))
            if gold_path.is_file()
            else []
        )

    def test_canonical_policy_has_47_clauses(self) -> None:
        self.assertEqual(47, len(self.engine.rules.clauses))
        self.assertTrue((ROOT / "policies" / "source" / "refund_policy_spec_v0.5.md").is_file())

    def test_all_60_policy_facts_match_expected_results(self) -> None:
        if not self.cases:
            self.skipTest("private Gold is intentionally absent from this package")
        keys = (
            "eligibility",
            "case_status",
            "next_action",
            "primary_clause",
            "matched_clauses",
            "overridden_clauses",
            "required_fields",
        )
        failures: list[str] = []
        for case in self.cases:
            actual = self.engine.evaluate(case["policy_facts"]).value
            expected = case["expected_result"]
            differing = [key for key in keys if actual.get(key) != expected.get(key)]
            if differing:
                failures.append(f"{case['testcase_id']}: {differing}")
        self.assertEqual([], failures)

    def test_unknown_top_level_field_is_rejected(self) -> None:
        if not self.cases:
            self.skipTest("private evaluator facts are intentionally absent from this package")
        facts = dict(self.cases[0]["policy_facts"])
        facts["gold_decision"] = "APPROVE"
        with self.assertRaises(InputContractError):
            self.engine.evaluate(facts)


if __name__ == "__main__":
    unittest.main()
