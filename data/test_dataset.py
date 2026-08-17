"""Integrity, Gold consistency, and reproducibility checks for data v0.5."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from data.build_dataset import build

try:
    from policies.policy_oracle import decide
except ModuleNotFoundError:
    from policy_oracle import decide


ROOT = Path(__file__).parents[1]
DATA = ROOT / "data"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = json.loads((DATA / "test_cases.json").read_text(encoding="utf-8"))

    def test_exact_case_count_distribution_and_contract(self) -> None:
        self.assertEqual(20, len(self.cases))
        self.assertEqual(20, len({case["testcase_id"] for case in self.cases}))
        self.assertEqual(
            Counter({"EASY": 6, "MEDIUM": 8, "HARD": 6}),
            Counter(case["difficulty"] for case in self.cases),
        )
        for case in self.cases:
            for field in (
                "question",
                "required_fields",
                "gold_decision",
                "gold_clauses",
                "difficulty",
            ):
                self.assertIn(field, case)
            self.assertTrue(case["question"].strip())
            self.assertIsInstance(case["required_fields"], list)
            self.assertIsInstance(case["gold_clauses"], list)

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

    def test_every_gold_record_matches_latest_oracle(self) -> None:
        for case in self.cases:
            with self.subTest(testcase_id=case["testcase_id"]):
                actual = decide(case["policy_facts"])
                self.assertEqual(case["expected_result"], actual)
                self.assertEqual(case["required_fields"], actual["required_fields"])
                self.assertEqual(case["gold_clauses"], actual["matched_clauses"])

    def test_boundaries_exceptions_and_conflict_priority(self) -> None:
        by_id = {case["testcase_id"]: case for case in self.cases}
        self.assertEqual("APPROVE", by_id["G-002"]["gold_decision"])
        self.assertEqual("REJECT", by_id["G-007"]["gold_decision"])
        self.assertEqual("APPROVE", by_id["G-003"]["gold_decision"])
        self.assertEqual("REJECT", by_id["G-008"]["gold_decision"])
        self.assertEqual("POL-40.01", by_id["G-014"]["expected_result"]["primary_clause"])
        self.assertEqual(
            ["POL-30.01", "POL-30.02"],
            by_id["G-014"]["expected_result"]["overridden_clauses"],
        )
        self.assertEqual("POL-50.01", by_id["G-020"]["expected_result"]["primary_clause"])

    def test_manifest_hashes_and_rebuild_are_reproducible(self) -> None:
        manifest = json.loads((DATA / "version_manifest.json").read_text(encoding="utf-8"))
        for relative, expected in manifest["artifact_sha256"].items():
            self.assertEqual(expected, sha256(ROOT / relative))

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
