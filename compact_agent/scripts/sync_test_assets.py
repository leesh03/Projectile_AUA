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
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def build_shop_db(path: Path, cases: list[dict[str, Any]]) -> None:
    """Build the SQL-only local regression database.

    The regression schema deliberately has no uniqueness constraints and keeps
    the requested lookup key separate from the returned record identifiers.
    That lets SQL represent missing, duplicate, and mismatched records without
    selecting prebuilt facts by ``testcase_id``.  This database is a developer
    regression fixture; callers can point the Agent at an official database by
    supplying ``--db-path`` or ``POLICY_AGENT_DB_PATH``.
    """

    if path.exists():
        path.unlink()
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE customers (
              lookup_order_item_id TEXT, record_present INTEGER,
              customer_id TEXT, order_snapshot_id TEXT, tier TEXT, snapshotted_at TEXT
            );
            CREATE TABLE products (
              lookup_order_item_id TEXT, record_present INTEGER,
              product_id TEXT, order_snapshot_id TEXT, category TEXT,
              final_sale INTEGER, snapshotted_at TEXT
            );
            CREATE TABLE orders (
              lookup_order_item_id TEXT, record_present INTEGER,
              order_item_id TEXT, order_id TEXT, customer_id TEXT, product_id TEXT,
              order_snapshot_id TEXT, ordered_at TEXT, status TEXT,
              paid_item_amount INTEGER, currency TEXT
            );
            CREATE TABLE shipments (
              lookup_order_item_id TEXT, record_present INTEGER,
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
            facts = case["policy_facts"]
            lookup_id = facts["request"]["order_item_id"]
            counts = facts.get("lookup_counts", {})
            order = facts.get("order")
            customer = facts.get("customer_snapshot")
            product = facts.get("product")
            shipment = facts.get("shipment")

            def repeated(section: str, value: Any) -> list[Any]:
                count = int(counts.get(section, 0))
                if count < 0:
                    raise ValueError(f"negative lookup count in {case['testcase_id']}: {section}")
                return [value for _ in range(count)]

            for row in repeated("customer_snapshot", customer):
                connection.execute(
                    "INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        lookup_id,
                        int(row is not None),
                        row.get("customer_id") if row else None,
                        row.get("order_snapshot_id") if row else None,
                        row.get("customer_tier_at_order") if row else None,
                        row.get("snapshotted_at") if row else None,
                    ),
                )
            for row in repeated("product", product):
                connection.execute(
                    "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        lookup_id,
                        int(row is not None),
                        row.get("product_id") if row else None,
                        row.get("order_snapshot_id") if row else None,
                        row.get("category") if row else None,
                        row.get("final_sale") if row else None,
                        row.get("snapshotted_at") if row else None,
                    ),
                )
            for row in repeated("order_item_order", order):
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
            for row in repeated("shipment", shipment):
                evidence = row.get("evidence") if row else {}
                evidence = evidence or {}
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
    expected_cases: list[dict[str, Any]] = []
    for case in test_cases:
        testcase_id = str(case["testcase_id"])
        expected_cases.append(
            {
                "testcase_id": testcase_id,
                "policy_facts": case["policy_facts"],
                "expected_result": case["expected_result"],
            }
        )
    data_root = project_root / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    build_shop_db(data_root / "shop.db", test_cases)
    write_json(data_root / "agent_cases.json", agent_cases)
    obsolete_fixture = data_root / "adapter_fixtures.json"
    if obsolete_fixture.exists():
        obsolete_fixture.unlink()
    write_json(
        project_root / "evaluation" / "private" / "expected_cases.json",
        expected_cases,
    )
    version_manifest = json.loads((source_data / "version_manifest.json").read_text(encoding="utf-8"))
    artifact_hashes = version_manifest.get("artifact_sha256")
    if not isinstance(artifact_hashes, dict):
        raise ValueError("source version manifest is missing artifact_sha256")
    artifact_hashes["data/agent_cases.json"] = sha256(data_root / "agent_cases.json")
    write_json(data_root / "source_version_manifest.json", version_manifest)

    outputs = [
        data_root / "shop.db",
        data_root / "agent_cases.json",
        data_root / "source_version_manifest.json",
        project_root / "evaluation" / "private" / "expected_cases.json",
    ]
    write_json(
        data_root / "asset_manifest.json",
        {
            "schema": "local-test-assets-v1",
            "source_commit": source_commit,
            "case_count": 60,
            "adapter_fixture_count": 0,
            "database_source": (
                "developer regression DB rebuilt from PolicyFacts inputs; "
                "contains no Gold outputs and is replaceable with the official DB"
            ),
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
    print("synced 60 SQL-only regression cases and the read-only shop database")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
