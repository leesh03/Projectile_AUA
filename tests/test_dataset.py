"""Integrity, Gold consistency, and reproducibility checks for the active suite."""

from __future__ import annotations

import hashlib
import importlib
import json
import platform
import sqlite3
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from data.build_dataset import build

importlib.import_module("policies.policy_oracle")


ROOT = Path(__file__).parents[1]
DATA = ROOT / "data"
ARTIFACTS = ROOT / "artifacts"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = json.loads((DATA / "test_cases.json").read_text(encoding="utf-8"))
        cls.agent_cases = json.loads((DATA / "agent_cases.json").read_text(encoding="utf-8"))

    def test_exact_case_count_distribution_and_contract(self) -> None:
        self.assertEqual(60, len(self.cases))
        self.assertEqual(60, len({case["testcase_id"] for case in self.cases}))
        self.assertEqual(
            Counter({"EASY": 20, "MEDIUM": 20, "HARD": 20}),
            Counter(case["difficulty"] for case in self.cases),
        )
        for case in self.cases:
            for field in (
                "testcase_id",
                "difficulty",
                "question",
                "target_ids",
                "request",
                "trusted_context",
                "coverage_tags",
                "required_fields",
                "gold_decision",
                "gold_clauses",
                "expected_result",
                "policy_facts",
            ):
                self.assertIn(field, case)
            self.assertTrue(case["question"].strip())
            self.assertIsInstance(case["target_ids"], dict)
            self.assertIsInstance(case["coverage_tags"], list)
            self.assertIsInstance(case["required_fields"], list)
            self.assertIsInstance(case["gold_clauses"], list)
            self.assertIsInstance(case["expected_result"], dict)

    def test_shop_db_has_exactly_five_tables_and_is_valid(self) -> None:
        connection = sqlite3.connect(DATA / "shop.db")
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertEqual(
                {"customers", "orders", "products", "shipments", "refunds"},
                tables,
            )
            self.assertEqual("ok", connection.execute("PRAGMA integrity_check").fetchone()[0])
            self.assertEqual([], connection.execute("PRAGMA foreign_key_check").fetchall())
        finally:
            connection.close()

    def test_answer_key_is_separate_and_complete(self) -> None:
        connection = sqlite3.connect(DATA / "answer_key.db")
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertEqual({"metadata", "gold_test_cases"}, tables)
            self.assertEqual(
                60,
                connection.execute("SELECT COUNT(*) FROM gold_test_cases").fetchone()[0],
            )
            metadata = dict(connection.execute("SELECT key, value FROM metadata"))
            self.assertEqual("60", metadata["record_count"])
            self.assertEqual("DENY", metadata["agent_access"])
            self.assertEqual("PENDING", metadata["independent_human_review"])
            answer_rows = {
                row[0]: row[1:]
                for row in connection.execute(
                    """SELECT
                        testcase_id, coverage_tags_json, required_fields_json,
                        gold_decision, gold_clauses_json, primary_clause,
                        policy_facts_json, expected_result_json
                    FROM gold_test_cases"""
                )
            }
            for source in self.cases:
                row = answer_rows[source["testcase_id"]]
                self.assertEqual(source["coverage_tags"], json.loads(row[0]))
                self.assertEqual(source["required_fields"], json.loads(row[1]))
                self.assertEqual(source["gold_decision"], row[2])
                self.assertEqual(source["gold_clauses"], json.loads(row[3]))
                self.assertEqual(source["expected_result"]["primary_clause"], row[4])
                self.assertEqual(source["policy_facts"], json.loads(row[5]))
                self.assertEqual(source["expected_result"], json.loads(row[6]))
            self.assertEqual("ok", connection.execute("PRAGMA integrity_check").fetchone()[0])
        finally:
            connection.close()

    def test_ids_exist_except_explicit_empty_result_cases(self) -> None:
        connection = sqlite3.connect(DATA / "shop.db")
        try:
            for case in self.cases:
                item_id = case["target_ids"]["order_item_id"]
                order_count = connection.execute(
                    "SELECT COUNT(*) FROM orders WHERE order_item_id=?", (item_id,)
                ).fetchone()[0]
                shipment_count = connection.execute(
                    "SELECT COUNT(*) FROM shipments WHERE order_item_id=?", (item_id,)
                ).fetchone()[0]
                tags = set(case["coverage_tags"])
                if "ORDER_NOT_FOUND" in tags:
                    self.assertEqual((0, 0), (order_count, shipment_count))
                elif "SHIPMENT_DATA_MISSING" in tags:
                    self.assertEqual((1, 0), (order_count, shipment_count))
                else:
                    self.assertEqual((1, 1), (order_count, shipment_count))
        finally:
            connection.close()

    def test_agent_cases_match_suite_without_gold_fields(self) -> None:
        self.assertEqual(
            [case["testcase_id"] for case in self.cases],
            [case["testcase_id"] for case in self.agent_cases],
        )
        allowed = {
            "testcase_id",
            "difficulty",
            "question",
            "target_ids",
            "request",
            "trusted_context",
        }
        for source, agent_case in zip(self.cases, self.agent_cases):
            self.assertEqual(allowed, set(agent_case))
            self.assertEqual(source["difficulty"], agent_case["difficulty"])
            self.assertEqual(source["question"], agent_case["question"])
            self.assertEqual(source["target_ids"], agent_case["target_ids"])
            self.assertEqual(source["request"], agent_case["request"])
            self.assertEqual(source["trusted_context"], agent_case["trusted_context"])

    def test_every_gold_record_matches_latest_oracle(self) -> None:
        for case in self.cases:
            with self.subTest(testcase_id=case["testcase_id"]):
                result = case["expected_result"]
                self.assertIn("eligibility", result)
                self.assertIn("primary_clause", result)
                self.assertIn("matched_clauses", result)
                self.assertIn("required_fields", result)
                self.assertEqual(case["required_fields"], result["required_fields"])
                self.assertEqual(case["gold_clauses"], result["matched_clauses"])

    def test_boundaries_exceptions_and_conflict_priority(self) -> None:
        by_id = {case["testcase_id"]: case for case in self.cases}
        self.assertTrue(any(case_id.startswith("E-") for case_id in by_id))
        self.assertTrue(any(case_id.startswith("M-") for case_id in by_id))
        self.assertTrue(any(case_id.startswith("H-") for case_id in by_id))
        self.assertEqual("APPROVE", by_id["E-001"]["gold_decision"])
        self.assertEqual("NEED_MORE_INFO", by_id["E-020"]["gold_decision"])
        self.assertEqual("NEED_MORE_INFO", by_id["M-010"]["gold_decision"])
        self.assertEqual("NEED_MORE_INFO", by_id["H-020"]["gold_decision"])

    def test_manifest_hashes_and_rebuild_are_reproducible(self) -> None:
        manifest = json.loads((DATA / "version_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(60, manifest["testcase_count"])
        for relative, expected in manifest["artifact_sha256"].items():
            self.assertEqual(expected, sha256(ROOT / relative))

        release_manifest = json.loads(
            (ARTIFACTS / "version_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(60, release_manifest["testcase_count"])
        for relative, expected in release_manifest["artifact_sha256"].items():
            self.assertEqual(expected, sha256(ROOT / relative))

        if platform.python_version() != "3.11.5" or sqlite3.sqlite_version != "3.43.0":
            self.skipTest(
                "exact-byte dataset rebuild requires release Python 3.11.5 / SQLite 3.43.0; "
                "runtime integrity hashes were still verified"
            )

        committed = {
            name: sha256(DATA / name)
            for name in ("shop.db", "test_cases.json")
        }
        with tempfile.TemporaryDirectory() as directory:
            rebuilt_root = Path(directory)
            build(rebuilt_root)
            rebuilt = {
                name: sha256(rebuilt_root / "data" / name)
                for name in committed
            }
        self.assertEqual(committed, rebuilt)


if __name__ == "__main__":
    unittest.main()
