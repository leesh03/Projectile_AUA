"""Build the SQL-only 60-case regression database from PolicyFacts.

The pulled Core queries only public SQLite tables. Missing, duplicate, and
reference-mismatch cases therefore have to be representable in SQL instead of
being injected by a testcase-aware adapter. ``lookup_order_item_id`` is the
trusted lookup key, while ``record_present`` says whether a returned lookup row
materializes into the canonical PolicyFacts object.

Run from the repository root:

    python data/build_shop_db.py
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES_PATH = REPO_ROOT / "data" / "test_cases.json"
DEFAULT_DB_PATH = REPO_ROOT / "data" / "shop.db"

SCHEMA = """
PRAGMA user_version = 5;

CREATE TABLE customers (
    lookup_order_item_id TEXT,
    record_present INTEGER,
    customer_id TEXT,
    order_snapshot_id TEXT,
    tier TEXT,
    snapshotted_at TEXT
);

CREATE TABLE products (
    lookup_order_item_id TEXT,
    record_present INTEGER,
    product_id TEXT,
    order_snapshot_id TEXT,
    category TEXT,
    final_sale INTEGER,
    snapshotted_at TEXT
);

CREATE TABLE orders (
    lookup_order_item_id TEXT,
    record_present INTEGER,
    order_item_id TEXT,
    order_id TEXT,
    customer_id TEXT,
    product_id TEXT,
    order_snapshot_id TEXT,
    ordered_at TEXT,
    status TEXT,
    paid_item_amount INTEGER,
    currency TEXT
);

CREATE TABLE shipments (
    lookup_order_item_id TEXT,
    record_present INTEGER,
    shipment_id TEXT,
    order_item_id TEXT,
    shipped_at TEXT,
    delivered_at TEXT,
    package_opened INTEGER,
    issue_code TEXT,
    evidence_status TEXT,
    verified_by TEXT,
    verified_at TEXT,
    evidence_source TEXT,
    attested INTEGER
);

CREATE TABLE refunds (
    refund_id TEXT,
    order_item_id TEXT,
    requested_at TEXT,
    status TEXT,
    amount INTEGER,
    currency TEXT
);

CREATE INDEX idx_customers_lookup ON customers(lookup_order_item_id);
CREATE INDEX idx_products_lookup ON products(lookup_order_item_id);
CREATE INDEX idx_orders_lookup ON orders(lookup_order_item_id);
CREATE INDEX idx_shipments_lookup ON shipments(lookup_order_item_id);
CREATE INDEX idx_refunds_order_item ON refunds(order_item_id);
"""


def read_cases(path: Path = DEFAULT_CASES_PATH) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise TypeError(f"{path} must contain a JSON array of objects")
    if len(value) != 60:
        raise ValueError(f"expected 60 test cases, found {len(value)}")
    return value


def _repeat_count(case: Mapping[str, Any], section: str) -> int:
    count = int(case["policy_facts"].get("lookup_counts", {}).get(section, 0))
    if count < 0:
        raise ValueError(f"{case.get('testcase_id')}: negative lookup count for {section}")
    return count


def _synthetic_duplicate(
    case: Mapping[str, Any], section: str, index: int, value: Any
) -> Any:
    """Keep one identifier-addressable row for legacy integrity checks.

    Duplicate one-to-one lookups have a canonical object value of ``None``.
    The pulled Core determines that from the two lookup rows, not their payload.
    Materializing only the first row keeps direct ``order_item_id`` integrity
    checks useful without changing the Core-visible PolicyFacts.
    """

    count = _repeat_count(case, section)
    if value is not None or count < 2 or index != 0:
        return value
    target = case["target_ids"]
    lookup_id = case["request"]["order_item_id"]
    if section == "order_item_order":
        return {
            "order_item_id": lookup_id,
            "order_id": target.get("order_id"),
            "customer_id": target.get("customer_id"),
            "product_id": target.get("product_id"),
            "order_snapshot_id": f"AMBIGUOUS-{case['testcase_id']}",
            "ordered_at": None,
            "order_status": None,
            "paid_item_amount": None,
            "currency": None,
        }
    if section == "shipment":
        return {
            "shipment_id": target.get("shipment_id"),
            "order_item_id": lookup_id,
            "delivered_at": None,
            "package_opened": None,
            "issue_code": None,
            "evidence": {},
        }
    return value


def build_database(path: Path, cases: list[dict[str, Any]]) -> Path:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    connection = sqlite3.connect(path)
    try:
        connection.executescript(SCHEMA)
        for case in cases:
            facts = case["policy_facts"]
            lookup_id = facts["request"]["order_item_id"]

            customer = facts.get("customer_snapshot")
            for _ in range(_repeat_count(case, "customer_snapshot")):
                connection.execute(
                    "INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        lookup_id,
                        int(customer is not None),
                        customer.get("customer_id") if customer else None,
                        customer.get("order_snapshot_id") if customer else None,
                        customer.get("customer_tier_at_order") if customer else None,
                        customer.get("snapshotted_at") if customer else None,
                    ),
                )

            product = facts.get("product")
            for _ in range(_repeat_count(case, "product")):
                connection.execute(
                    "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        lookup_id,
                        int(product is not None),
                        product.get("product_id") if product else None,
                        product.get("order_snapshot_id") if product else None,
                        product.get("category") if product else None,
                        product.get("final_sale") if product else None,
                        product.get("snapshotted_at") if product else None,
                    ),
                )

            order = facts.get("order")
            for index in range(_repeat_count(case, "order_item_order")):
                row = _synthetic_duplicate(case, "order_item_order", index, order)
                connection.execute(
                    "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        lookup_id,
                        int(row is not None),
                        row.get("order_item_id") if row else None,
                        row.get("order_id") if row else None,
                        row.get("customer_id") if row else None,
                        row.get("product_id") if row else None,
                        row.get("order_snapshot_id") if row else None,
                        row.get("ordered_at") if row else None,
                        row.get("order_status") if row else None,
                        row.get("paid_item_amount") if row else None,
                        row.get("currency") if row else None,
                    ),
                )

            shipment = facts.get("shipment")
            for index in range(_repeat_count(case, "shipment")):
                row = _synthetic_duplicate(case, "shipment", index, shipment)
                evidence = (row or {}).get("evidence") or {}
                connection.execute(
                    "INSERT INTO shipments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        lookup_id,
                        int(row is not None),
                        row.get("shipment_id") if row else None,
                        row.get("order_item_id") if row else None,
                        None,
                        row.get("delivered_at") if row else None,
                        row.get("package_opened") if row else None,
                        row.get("issue_code") if row else None,
                        evidence.get("evidence_status"),
                        evidence.get("verified_by"),
                        evidence.get("verified_at"),
                        evidence.get("evidence_source"),
                        evidence.get("provenance_attested"),
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
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("generated shop.db failed SQLite integrity_check")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        expected_tables = {"customers", "orders", "products", "refunds", "shipments"}
        if tables != expected_tables:
            raise RuntimeError(f"unexpected generated tables: {sorted(tables)}")
    finally:
        connection.close()
    return path


def build(
    path: Path = DEFAULT_DB_PATH, cases_path: Path = DEFAULT_CASES_PATH
) -> Path:
    return build_database(path, read_cases(cases_path))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    args = parser.parse_args()
    output = build(args.output, args.cases)
    print(f"created SQL-only 60-case regression database: {output}")


if __name__ == "__main__":
    main()
