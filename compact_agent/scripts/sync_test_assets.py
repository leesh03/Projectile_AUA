"""Import the latest dataset without exposing Gold answers to the Agent."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


AGENT_FIELDS = {
    "testcase_id",
    "difficulty",
    "question",
    "request",
    "target_ids",
    "trusted_context",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_array(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"expected an array of objects: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_shop_db(path: Path, cases: list[dict[str, Any]]) -> None:
    """Build a five-table local DB from evaluator PolicyFacts inputs.

    The upstream binary currently contains default rows for many v0.5 cases
    and its CHECK constraints cannot represent invalid-state test inputs.
    Facts are inputs, not Gold decisions, so rebuilding this read-only test DB
    does not leak expected answers into the Agent.
    """

    if path.exists():
        path.unlink()
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE customers (customer_id TEXT, tier TEXT);
            CREATE TABLE products (product_id TEXT, category TEXT, final_sale INTEGER, unit_price_krw INTEGER);
            CREATE TABLE orders (
              order_item_id TEXT, order_id TEXT, customer_id TEXT, product_id TEXT,
              order_snapshot_id TEXT, ordered_at TEXT, status TEXT,
              customer_tier_at_order TEXT, product_category_at_order TEXT,
              product_final_sale_at_order INTEGER, paid_item_amount INTEGER, currency TEXT
            );
            CREATE TABLE shipments (
              shipment_id TEXT, order_item_id TEXT, shipped_at TEXT, delivered_at TEXT,
              package_opened INTEGER, issue_code TEXT, evidence_status TEXT,
              verified_by TEXT, verified_at TEXT, evidence_source TEXT, attested INTEGER
            );
            CREATE TABLE refunds (
              refund_id TEXT, order_item_id TEXT, requested_at TEXT,
              status TEXT, amount INTEGER, currency TEXT
            );
            """
        )
        for case in cases:
            # The nine adapter cases intentionally represent cardinality or
            # cross-record states that the compact SQL schema cannot express.
            if case.get("fact_source") != "SHOP_DB":
                continue
            facts = case["policy_facts"]
            order = facts.get("order")
            customer = facts.get("customer_snapshot")
            product = facts.get("product")
            shipment = facts.get("shipment")
            if customer is not None:
                connection.execute(
                    "INSERT INTO customers VALUES (?, ?)",
                    (customer.get("customer_id"), customer.get("customer_tier_at_order")),
                )
            if product is not None:
                connection.execute(
                    "INSERT INTO products VALUES (?, ?, ?, ?)",
                    (
                        product.get("product_id"),
                        product.get("category"),
                        product.get("final_sale"),
                        order.get("paid_item_amount") if order else None,
                    ),
                )
            if order is not None:
                connection.execute(
                    "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        order.get("order_item_id"),
                        order.get("order_id"),
                        order.get("customer_id"),
                        order.get("product_id"),
                        order.get("order_snapshot_id"),
                        order.get("ordered_at"),
                        order.get("order_status"),
                        customer.get("customer_tier_at_order") if customer else None,
                        product.get("category") if product else None,
                        product.get("final_sale") if product else None,
                        order.get("paid_item_amount"),
                        order.get("currency"),
                    ),
                )
            if shipment is not None:
                evidence = shipment.get("evidence") or {}
                connection.execute(
                    "INSERT INTO shipments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        shipment.get("shipment_id"),
                        shipment.get("order_item_id"),
                        None,
                        shipment.get("delivered_at"),
                        shipment.get("package_opened"),
                        shipment.get("issue_code"),
                        evidence.get("evidence_status"),
                        evidence.get("verified_by"),
                        evidence.get("verified_at"),
                        evidence.get("evidence_source"),
                        evidence.get("provenance_attested"),
                    ),
                )
            elif facts.get("lookup_counts", {}).get("shipment", 0) > 1:
                # Cardinality-only facts intentionally hide the ambiguous
                # records.  Materialize placeholder rows so EvidenceChecker
                # derives count > 1 and keeps shipment=None.
                count = int(facts["lookup_counts"]["shipment"])
                for index in range(count):
                    connection.execute(
                        "INSERT INTO shipments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            f"{case['target_ids']['shipment_id']}-DUP-{index + 1}",
                            case["request"]["order_item_id"],
                            None,
                            None,
                            None,
                            None,
                            "NONE",
                            None,
                            None,
                            None,
                            0,
                        ),
                    )
            for refund in facts.get("refund_history", []):
                connection.execute(
                    "INSERT INTO refunds VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        refund.get("refund_id"),
                        refund.get("order_item_id"),
                        None,
                        refund.get("status"),
                        refund.get("amount"),
                        refund.get("currency"),
                    ),
                )
        connection.commit()
    finally:
        connection.close()


def sync(source_root: Path, project_root: Path, source_commit: str) -> None:
    project_root = project_root.resolve()
    source_data = source_root.resolve() / "data"
    required = ["shop.db", "agent_cases.json", "test_cases.json", "version_manifest.json"]
    missing = [name for name in required if not (source_data / name).is_file()]
    if missing:
        raise FileNotFoundError(f"dataset is missing files: {missing}")

    agent_cases = read_array(source_data / "agent_cases.json")
    if len(agent_cases) != 60:
        raise ValueError(f"expected 60 Agent cases, found {len(agent_cases)}")
    for case in agent_cases:
        if set(case) != AGENT_FIELDS:
            raise ValueError(
                f"Agent case {case.get('testcase_id')} leaked or omitted fields: "
                f"{sorted(set(case) ^ AGENT_FIELDS)}"
            )

    test_cases = read_array(source_data / "test_cases.json")
    if len(test_cases) != 60:
        raise ValueError(f"expected 60 evaluator cases, found {len(test_cases)}")
    fixtures: dict[str, dict[str, Any]] = {}
    expected_cases: list[dict[str, Any]] = []
    for case in test_cases:
        testcase_id = str(case["testcase_id"])
        if case.get("fact_source") != "SHOP_DB" or case.get("adapter_fixture") is not None:
            fixtures[testcase_id] = case["policy_facts"]
        expected_cases.append(
            {
                "testcase_id": testcase_id,
                "policy_facts": case["policy_facts"],
                "expected_result": case["expected_result"],
            }
        )
    if len(fixtures) != 9:
        raise ValueError(f"expected 9 adapter fixtures, found {len(fixtures)}")

    data_root = project_root / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    build_shop_db(data_root / "shop.db", test_cases)
    write_json(data_root / "agent_cases.json", agent_cases)
    write_json(
        data_root / "adapter_fixtures.json",
        {
            "schema": "policy-facts-fixtures-v1",
            "source_commit": source_commit,
            "description": "Facts only; contains no expected decision or Gold clauses.",
            "cases": fixtures,
        },
    )
    write_json(
        project_root / "evaluation" / "private" / "expected_cases.json",
        expected_cases,
    )
    version_manifest = json.loads((source_data / "version_manifest.json").read_text(encoding="utf-8"))
    write_json(data_root / "source_version_manifest.json", version_manifest)

    outputs = [
        data_root / "shop.db",
        data_root / "agent_cases.json",
        data_root / "adapter_fixtures.json",
        data_root / "source_version_manifest.json",
        project_root / "evaluation" / "private" / "expected_cases.json",
    ]
    write_json(
        data_root / "asset_manifest.json",
        {
            "schema": "local-test-assets-v1",
            "source_commit": source_commit,
            "case_count": 60,
            "adapter_fixture_count": 9,
            "database_source": "rebuilt from PolicyFacts inputs; no Gold outputs",
            "files": {
                str(path.relative_to(project_root)).replace("\\", "/"): sha256(path)
                for path in outputs
            },
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    sync(args.source, args.project, args.source_commit)
    print("synced 60 cases, 9 fact-only adapter fixtures, and the read-only shop database")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
