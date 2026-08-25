"""Synchronize the active 60-case dataset from the protected answer key.

The protected ``data/answer_key.db`` is the source of truth for testcase IDs,
questions, Gold decisions, clauses, policy facts, and expected results. The
checked-in JSON files are retained as templates for agent-visible identifiers
and release labels, then validated and synchronized against the answer key.

Run from the repository root:

    python data/build_dataset.py

Use ``--output-root`` to reproduce the suite in a separate directory without
modifying the checked-in artifacts.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import shutil
import sqlite3
from typing import Any, Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DATA_DIR = REPO_ROOT / "data"
EXPECTED_CASE_COUNT = 60
EXPECTED_DIFFICULTY_COUNTS = Counter(
    {"EASY": 20, "MEDIUM": 20, "HARD": 20}
)
AGENT_FIELDS = (
    "testcase_id",
    "difficulty",
    "question",
    "target_ids",
    "request",
    "trusted_context",
)


def pretty_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(
        isinstance(item, dict) for item in value
    ):
        raise TypeError(f"{path} must contain a JSON list of objects")
    return value


def _load_answer_key(
    answer_db: Path,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    if not answer_db.exists():
        raise FileNotFoundError(f"protected answer key not found: {answer_db}")

    connection = sqlite3.connect(
        f"file:{answer_db.as_posix()}?mode=ro", uri=True
    )
    connection.row_factory = sqlite3.Row
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(
                f"answer key integrity check failed: {integrity}"
            )

        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if tables != {"metadata", "gold_test_cases"}:
            raise RuntimeError(
                f"unexpected answer key tables: {sorted(tables)}"
            )

        metadata = dict(
            connection.execute("SELECT key, value FROM metadata")
        )
        rows = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM gold_test_cases ORDER BY testcase_id"
            )
        ]
    finally:
        connection.close()

    ids = [row["testcase_id"] for row in rows]
    difficulty_counts = Counter(row["difficulty"] for row in rows)
    if len(rows) != EXPECTED_CASE_COUNT or len(set(ids)) != EXPECTED_CASE_COUNT:
        raise RuntimeError(
            f"answer_key.db must contain {EXPECTED_CASE_COUNT} unique cases; "
            f"found {len(rows)} rows and {len(set(ids))} unique IDs"
        )
    if difficulty_counts != EXPECTED_DIFFICULTY_COUNTS:
        raise RuntimeError(
            "answer_key.db difficulty distribution must be "
            f"{dict(EXPECTED_DIFFICULTY_COUNTS)}; "
            f"found {dict(difficulty_counts)}"
        )
    if metadata.get("record_count") != str(EXPECTED_CASE_COUNT):
        raise RuntimeError(
            "answer_key.db metadata record_count must be "
            f"{EXPECTED_CASE_COUNT}; found {metadata.get('record_count')!r}"
        )
    return rows, metadata


def _json_column(row: Mapping[str, Any], name: str) -> Any:
    try:
        return json.loads(row[name])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"{row.get('testcase_id', '<unknown>')}: invalid {name}"
        ) from exc


def _derive_target_ids(
    row: Mapping[str, Any], facts: Mapping[str, Any]
) -> dict[str, Any]:
    testcase_id = row["testcase_id"]
    order = facts.get("order") or {}
    customer = facts.get("customer_snapshot") or {}
    product = facts.get("product") or {}
    shipment = facts.get("shipment") or {}
    return {
        "customer_id": (
            order.get("customer_id")
            or customer.get("customer_id")
            or f"C-{testcase_id}"
        ),
        "order_id": row.get("order_id") or f"O-{testcase_id}",
        "order_item_id": row["order_item_id"],
        "product_id": (
            order.get("product_id")
            or product.get("product_id")
            or f"P-{testcase_id}"
        ),
        "shipment_id": shipment.get("shipment_id") or f"SH-{testcase_id}",
    }


def _record_from_answer(
    row: Mapping[str, Any], template: Mapping[str, Any] | None
) -> dict[str, Any]:
    facts = _json_column(row, "policy_facts_json")
    expected = _json_column(row, "expected_result_json")
    coverage_tags = _json_column(row, "coverage_tags_json")
    required_fields = _json_column(row, "required_fields_json")
    gold_clauses = _json_column(row, "gold_clauses_json")

    if expected.get("facts") != facts:
        raise RuntimeError(
            f"{row['testcase_id']}: expected_result facts differ from "
            "policy_facts"
        )
    if expected.get("primary_clause") != row["primary_clause"]:
        raise RuntimeError(
            f"{row['testcase_id']}: primary clause differs inside "
            "answer_key.db"
        )

    # Preserve template-only release fields such as fact_source and
    # adapter_fixture while replacing all protected Gold fields from the DB.
    record: dict[str, Any] = dict(template or {})
    record.update(
        {
            "testcase_id": row["testcase_id"],
            "difficulty": row["difficulty"],
            "question": row["question"],
            "request": facts["request"],
            "target_ids": dict(
                (template or {}).get("target_ids")
                or _derive_target_ids(row, facts)
            ),
            "trusted_context": facts["trusted_context"],
            "description": row["description"],
            "coverage_tags": coverage_tags,
            "policy_facts": facts,
            "expected_result": expected,
            "required_fields": required_fields,
            "gold_decision": row["gold_decision"],
            "gold_clauses": gold_clauses,
            "policy_version": row["policy_version"],
            # The checked-in 60-case suite uses full-coverage release labels,
            # while answer_key.db stores base schema labels. Preserve release
            # labels when a validated template is available.
            "db_version": (template or {}).get(
                "db_version", row["db_version"]
            ),
            "testcase_version": (template or {}).get(
                "testcase_version", row["testcase_version"]
            ),
        }
    )

    target_ids = record["target_ids"]
    if target_ids.get("order_item_id") != row["order_item_id"]:
        raise RuntimeError(
            f"{row['testcase_id']}: template order_item_id differs from "
            "answer_key.db"
        )
    if target_ids.get("order_id") != row["order_id"]:
        raise RuntimeError(
            f"{row['testcase_id']}: template order_id differs from "
            "answer_key.db"
        )
    return record


def _materialize_records(
    rows: Iterable[Mapping[str, Any]],
    template_cases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    answer_rows = list(rows)
    answer_by_id = {row["testcase_id"]: row for row in answer_rows}
    template_by_id = {
        case.get("testcase_id"): case
        for case in template_cases
        if isinstance(case.get("testcase_id"), str)
    }
    if (
        len(template_by_id) == EXPECTED_CASE_COUNT
        and set(template_by_id) == set(answer_by_id)
    ):
        ordered_rows = [
            answer_by_id[case["testcase_id"]] for case in template_cases
        ]
    else:
        ordered_rows = answer_rows
    records = [
        _record_from_answer(row, template_by_id.get(row["testcase_id"]))
        for row in ordered_rows
    ]
    if len(records) != EXPECTED_CASE_COUNT:
        raise RuntimeError(
            f"expected {EXPECTED_CASE_COUNT} materialized records"
        )
    return records


def _build_agent_records(
    records: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {field: record[field] for field in AGENT_FIELDS}
        for record in records
    ]


def _copy_if_different(source: Path, target: Path) -> None:
    if source.resolve() == target.resolve():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _write_or_copy_json(
    source: Path,
    target: Path,
    source_value: list[dict[str, Any]],
    synchronized_value: list[dict[str, Any]],
) -> None:
    if source_value == synchronized_value:
        _copy_if_different(source, target)
        return
    target.write_bytes(pretty_json_bytes(synchronized_value))


def build(output_root: Path = REPO_ROOT) -> dict[str, str]:
    output_root = output_root.resolve()
    data_dir = output_root / "data"
    artifacts_dir = output_root / "artifacts"
    data_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    source_answer_db = SOURCE_DATA_DIR / "answer_key.db"
    source_shop_db = SOURCE_DATA_DIR / "shop.db"
    source_cases_path = SOURCE_DATA_DIR / "test_cases.json"
    source_agent_cases_path = SOURCE_DATA_DIR / "agent_cases.json"

    rows, metadata = _load_answer_key(source_answer_db)
    source_cases = _read_json_list(source_cases_path)
    records = _materialize_records(rows, source_cases)
    agent_records = _build_agent_records(records)
    source_agent_records = _read_json_list(source_agent_cases_path)

    target_shop_db = data_dir / "shop.db"
    target_answer_db = data_dir / "answer_key.db"
    target_cases_path = data_dir / "test_cases.json"
    target_agent_cases_path = data_dir / "agent_cases.json"

    _copy_if_different(source_shop_db, target_shop_db)
    _copy_if_different(source_answer_db, target_answer_db)
    _write_or_copy_json(
        source_cases_path, target_cases_path, source_cases, records
    )
    _write_or_copy_json(
        source_agent_cases_path,
        target_agent_cases_path,
        source_agent_records,
        agent_records,
    )

    files = {
        "data/shop.db": sha256_file(target_shop_db),
        "data/test_cases.json": sha256_file(target_cases_path),
        "data/agent_cases.json": sha256_file(target_agent_cases_path),
        "data/answer_key.db": sha256_file(target_answer_db),
    }

    first_facts = _json_column(rows[0], "policy_facts_json")
    first_expected = _json_column(rows[0], "expected_result_json")
    manifest = {
        "release_profile": "BASE",
        "baseline_status": (
            "CANDIDATE_PENDING_INDEPENDENT_HUMAN_REVIEW"
        ),
        "policy_version": metadata.get(
            "policy_version", rows[0]["policy_version"]
        ),
        "db_version": metadata.get("db_version", rows[0]["db_version"]),
        "testcase_version": metadata.get(
            "testcase_version", rows[0]["testcase_version"]
        ),
        "core_version_vector": first_expected.get("versions", {}),
        "testcase_count": len(records),
        "difficulty_counts": dict(
            sorted(
                Counter(
                    record["difficulty"] for record in records
                ).items()
            )
        ),
        "evaluation_date": first_facts["trusted_context"][
            "evaluation_date"
        ],
        "timezone": first_facts["trusted_context"]["timezone"],
        "python_version": platform.python_version(),
        "sqlite_version": sqlite3.sqlite_version,
        "artifact_sha256": files,
        "source_policy_spec": "policies/refund_policy_spec_v0.5.md",
    }
    (data_dir / "version_manifest.json").write_bytes(
        pretty_json_bytes(manifest)
    )
    (artifacts_dir / "version_manifest.json").write_bytes(
        pretty_json_bytes(manifest)
    )
    return files


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()
    hashes = build(args.output_root)
    print(
        json.dumps(
            hashes, ensure_ascii=False, sort_keys=True, indent=2
        )
    )


if __name__ == "__main__":
    main()
