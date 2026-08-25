"""Build the v0.5 synthetic shop database and 20-case Gold JSON.

Run from the repository root:

    python data/build_dataset.py

The build is deterministic for a fixed Python/SQLite version. It never reads
the network or the system clock. Gold values are derived from the independent
policy oracle and cross-checked against manually fixed scenario expectations.
A separate human review is still required before baseline release.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
from pathlib import Path
import platform
import shutil
import sqlite3
import sys
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from policies import policy_oracle as _oracle
except ModuleNotFoundError:
    import policy_oracle as _oracle

decide = _oracle.decide
VERSION_VECTOR = getattr(_oracle, "VERSIONS", None) or getattr(
    _oracle, "VERSION_VECTOR"
)


EVALUATION_DATE = date(2026, 8, 15)
SEOUL = ZoneInfo("Asia/Seoul")
POLICY_VERSION = "policy-v0.5"
DB_VERSION = "db-v0.5"
TESTCASE_VERSION = "testcase-v0.5"
PAID_AMOUNT = 10_000


DDL = """
PRAGMA foreign_keys = ON;
PRAGMA page_size = 4096;
PRAGMA auto_vacuum = NONE;

CREATE TABLE customers (
  customer_id TEXT PRIMARY KEY,
  tier TEXT NOT NULL CHECK (tier IN ('STANDARD', 'PREMIUM'))
);

CREATE TABLE products (
  product_id TEXT PRIMARY KEY,
  category TEXT NOT NULL CHECK (category IN ('ELECTRONICS','FASHION','HOME','BEAUTY','OTHER')),
  final_sale INTEGER NOT NULL CHECK (final_sale IN (0,1)),
  unit_price_krw INTEGER NOT NULL CHECK (unit_price_krw BETWEEN 1 AND 9007199254740991)
);

CREATE TABLE orders (
  order_item_id TEXT PRIMARY KEY,
  order_id TEXT NOT NULL,
  customer_id TEXT NOT NULL REFERENCES customers(customer_id),
  product_id TEXT NOT NULL REFERENCES products(product_id),
  order_snapshot_id TEXT NOT NULL UNIQUE,
  ordered_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('PAID','SHIPPED','DELIVERED','CANCELLED')),
  customer_tier_at_order TEXT NOT NULL CHECK (customer_tier_at_order IN ('STANDARD','PREMIUM')),
  product_category_at_order TEXT NOT NULL CHECK (product_category_at_order IN ('ELECTRONICS','FASHION','HOME','BEAUTY','OTHER')),
  product_final_sale_at_order INTEGER NOT NULL CHECK (product_final_sale_at_order IN (0,1)),
  paid_item_amount INTEGER NOT NULL CHECK (paid_item_amount BETWEEN 1 AND 9007199254740991),
  currency TEXT NOT NULL CHECK (currency = 'KRW')
);

CREATE TABLE shipments (
  shipment_id TEXT PRIMARY KEY,
  order_item_id TEXT NOT NULL UNIQUE REFERENCES orders(order_item_id),
  shipped_at TEXT,
  delivered_at TEXT,
  package_opened INTEGER CHECK (package_opened IS NULL OR package_opened IN (0,1)),
  issue_code TEXT CHECK (issue_code IS NULL OR issue_code IN ('DAMAGED','WRONG_ITEM','MISSING_PARTS','DEFECTIVE')),
  evidence_status TEXT NOT NULL CHECK (evidence_status IN ('NONE','PENDING','VERIFIED','REJECTED')),
  verified_by TEXT,
  verified_at TEXT,
  evidence_source TEXT,
  attested INTEGER NOT NULL CHECK (attested IN (0,1))
);

CREATE TABLE refunds (
  refund_id TEXT PRIMARY KEY,
  order_item_id TEXT NOT NULL REFERENCES orders(order_item_id),
  requested_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('REQUESTED','APPROVED','REJECTED','COMPLETED')),
  amount INTEGER NOT NULL CHECK (amount BETWEEN 1 AND 9007199254740991),
  currency TEXT NOT NULL CHECK (currency = 'KRW')
);

CREATE INDEX idx_orders_order ON orders(order_id);
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_product ON orders(product_id);
CREATE INDEX idx_refunds_item_status ON refunds(order_item_id, status);
"""


@dataclass(frozen=True)
class CaseSpec:
    testcase_id: str
    difficulty: str
    question: str
    description: str
    coverage_tags: tuple[str, ...]
    elapsed_days: int = 7
    tier: str = "STANDARD"
    category: str = "FASHION"
    final_sale: bool = False
    package_opened: Optional[bool] = None
    requested_amount: Optional[int] = PAID_AMOUNT
    evidence_status: str = "NONE"
    issue_code: Optional[str] = None
    evidence_inconsistent: bool = False
    refund_status: Optional[str] = None
    delivered_at_null: bool = False
    shipment_missing: bool = False
    order_missing: bool = False


CASES = (
    CaseSpec("G-001", "EASY", "주문 상품 G-001은 전액 환불할 수 있나요?", "일반 회원 배송 완료 당일", ("STANDARD", "DAY_0"), elapsed_days=0),
    CaseSpec("G-002", "EASY", "주문 상품 G-002은 전액 환불할 수 있나요?", "일반 회원 환불 기간 마지막 날", ("STANDARD", "DAY_14", "BOUNDARY"), elapsed_days=14),
    CaseSpec("G-003", "EASY", "주문 상품 G-003은 전액 환불할 수 있나요?", "프리미엄 회원 환불 기간 마지막 날", ("PREMIUM", "DAY_30", "BOUNDARY"), elapsed_days=30, tier="PREMIUM"),
    CaseSpec("G-004", "EASY", "주문 상품 G-004은 전액 환불할 수 있나요?", "일반 상품 배송 완료 후 7일", ("STANDARD", "DAY_7")),
    CaseSpec("G-005", "EASY", "주문 상품 G-005은 전액 환불할 수 있나요?", "개봉하지 않은 전자제품", ("ELECTRONICS", "UNOPENED"), category="ELECTRONICS", package_opened=False),
    CaseSpec("G-006", "EASY", "금액을 따로 적지 않은 주문 상품 G-006의 전액 환불 가능 여부를 확인해 주세요.", "요청액 NULL은 순결제액 전액 요청", ("REQUESTED_AMOUNT_NULL", "FULL_REFUND_SENTINEL"), requested_amount=None),
    CaseSpec("G-007", "MEDIUM", "주문 상품 G-007은 전액 환불할 수 있나요?", "일반 회원 환불 기간 다음 날", ("STANDARD", "DAY_15", "BOUNDARY"), elapsed_days=15),
    CaseSpec("G-008", "MEDIUM", "주문 상품 G-008은 전액 환불할 수 있나요?", "프리미엄 회원 환불 기간 다음 날", ("PREMIUM", "DAY_31", "BOUNDARY"), elapsed_days=31, tier="PREMIUM"),
    CaseSpec("G-009", "MEDIUM", "주문 상품 G-009은 전액 환불할 수 있나요?", "개봉된 전자제품", ("ELECTRONICS", "OPENED"), category="ELECTRONICS", package_opened=True),
    CaseSpec("G-010", "MEDIUM", "주문 상품 G-010은 전액 환불할 수 있나요?", "최종 할인 판매 상품", ("FINAL_SALE",), final_sale=True),
    CaseSpec("G-011", "MEDIUM", "주문 상품 G-011에 새 전액 환불 요청을 처리할 수 있나요?", "이미 완료된 환불 존재", ("DUPLICATE_REFUND", "COMPLETED"), refund_status="COMPLETED"),
    CaseSpec("G-012", "MEDIUM", "주문 상품 G-012에 새 전액 환불 요청을 처리할 수 있나요?", "처리 중인 환불 존재", ("DUPLICATE_REFUND", "REQUESTED"), refund_status="REQUESTED"),
    CaseSpec("G-013", "MEDIUM", "회사 귀책이 확인된 주문 상품 G-013은 전액 환불할 수 있나요?", "회사 귀책이 기간 초과 제한을 해제", ("VERIFIED_COMPANY_FAULT", "WINDOW_OVERRIDE"), elapsed_days=75, evidence_status="VERIFIED", issue_code="DAMAGED"),
    CaseSpec("G-014", "MEDIUM", "회사 귀책이 확인된 주문 상품 G-014은 전액 환불할 수 있나요?", "회사 귀책이 Final Sale과 개봉 전자제품 제한을 해제", ("VERIFIED_COMPANY_FAULT", "FINAL_SALE", "OPENED", "MULTI_OVERRIDE"), category="ELECTRONICS", final_sale=True, package_opened=True, evidence_status="VERIFIED", issue_code="WRONG_ITEM"),
    CaseSpec("G-015", "HARD", "주문 상품 G-015의 전액 환불 가능 여부를 판단해 주세요.", "배송 행은 있으나 배송 완료일 NULL", ("DELIVERED_AT_NULL", "NULL"), delivered_at_null=True),
    CaseSpec("G-016", "HARD", "주문 상품 G-016의 전액 환불 가능 여부를 판단해 주세요.", "주문은 존재하지만 배송 조회 결과 없음", ("SHIPMENT_DATA_MISSING", "EMPTY_RESULT"), shipment_missing=True),
    CaseSpec("G-017", "HARD", "주문 상품 G-017의 전액 환불 가능 여부를 판단해 주세요.", "주문 조회 결과 없음", ("ORDER_NOT_FOUND", "EMPTY_RESULT"), order_missing=True),
    CaseSpec("G-018", "HARD", "회사 귀책 검토 중인 주문 상품 G-018의 전액 환불 가능 여부를 판단해 주세요.", "회사 귀책 증빙 확인 중", ("PENDING_EVIDENCE",), evidence_status="PENDING", issue_code="DAMAGED"),
    CaseSpec("G-019", "HARD", "주문 상품 G-019의 전액 환불 가능 여부를 판단해 주세요.", "증빙 상태와 사유 조합 불일치", ("INCONSISTENT_EVIDENCE", "FAULT_INJECTION"), issue_code="DAMAGED", evidence_inconsistent=True),
    CaseSpec("G-020", "HARD", "회사 귀책이 확인된 주문 상품 G-020에 새 전액 환불 요청을 처리할 수 있나요?", "완료 환불과 회사 귀책이 동시에 존재", ("DUPLICATE_REFUND", "VERIFIED_COMPANY_FAULT", "PRIORITY_CONFLICT"), evidence_status="VERIFIED", issue_code="DEFECTIVE", refund_status="COMPLETED"),
)


MANUAL_EXPECTATIONS = {
    "G-001": ("APPROVE", "POL-00.08"),
    "G-002": ("APPROVE", "POL-00.08"),
    "G-003": ("APPROVE", "POL-00.08"),
    "G-004": ("APPROVE", "POL-00.08"),
    "G-005": ("APPROVE", "POL-00.08"),
    "G-006": ("APPROVE", "POL-00.08"),
    "G-007": ("REJECT", "POL-20.06"),
    "G-008": ("REJECT", "POL-20.06"),
    "G-009": ("REJECT", "POL-30.02"),
    "G-010": ("REJECT", "POL-30.01"),
    "G-011": ("REJECT", "POL-50.01"),
    "G-012": ("NOT_APPLICABLE", "POL-50.02"),
    "G-013": ("APPROVE", "POL-40.01"),
    "G-014": ("APPROVE", "POL-40.01"),
    "G-015": ("NEED_MORE_INFO", "POL-10.13"),
    "G-016": ("NEED_MORE_INFO", "POL-10.04"),
    "G-017": ("NEED_MORE_INFO", "POL-10.01"),
    "G-018": ("NEED_MORE_INFO", "POL-40.02"),
    "G-019": ("NEED_MORE_INFO", "POL-40.04"),
    "G-020": ("REJECT", "POL-50.01"),
}


GOLD_DECISION = {
    "ELIGIBLE": "APPROVE",
    "INELIGIBLE": "REJECT",
    "UNDETERMINED": "NEED_MORE_INFO",
    "NOT_APPLICABLE": "NOT_APPLICABLE",
}


def utc_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def delivered_at_for(days: int) -> str:
    local_day = EVALUATION_DATE - timedelta(days=days)
    local_midnight = datetime.combine(local_day, time.min, tzinfo=SEOUL)
    return utc_z(local_midnight)


def ids_for(spec: CaseSpec) -> Dict[str, Optional[str]]:
    if spec.order_missing:
        return {
            "order_id": "O-G017-MISSING",
            "order_item_id": "OI-G017-MISSING",
            "customer_id": None,
            "product_id": None,
            "shipment_id": None,
        }
    suffix = spec.testcase_id
    return {
        "order_id": f"O-{suffix}",
        "order_item_id": f"OI-{suffix}",
        "customer_id": f"C-{suffix}",
        "product_id": f"P-{suffix}",
        "shipment_id": None if spec.shipment_missing else f"SH-{suffix}",
    }


def build_shop_db(path: Path) -> None:
    if path.exists():
        path.unlink()
    connection = sqlite3.connect(path)
    try:
        connection.executescript(DDL)
        ordered_at = "2026-05-01T00:00:00Z"
        for spec in CASES:
            if spec.order_missing:
                continue
            ids = ids_for(spec)
            connection.execute("INSERT INTO customers(customer_id, tier) VALUES (?, ?)", (ids["customer_id"], spec.tier))
            connection.execute(
                "INSERT INTO products(product_id, category, final_sale, unit_price_krw) VALUES (?, ?, ?, ?)",
                (ids["product_id"], spec.category, int(spec.final_sale), PAID_AMOUNT),
            )
            connection.execute(
                """INSERT INTO orders(
                    order_item_id, order_id, customer_id, product_id, order_snapshot_id,
                    ordered_at, status, customer_tier_at_order,
                    product_category_at_order, product_final_sale_at_order,
                    paid_item_amount, currency
                ) VALUES (?, ?, ?, ?, ?, ?, 'DELIVERED', ?, ?, ?, ?, 'KRW')""",
                (
                    ids["order_item_id"], ids["order_id"], ids["customer_id"], ids["product_id"],
                    f"SNAP-{spec.testcase_id}", ordered_at, spec.tier, spec.category,
                    int(spec.final_sale), PAID_AMOUNT,
                ),
            )
            if not spec.shipment_missing:
                delivered_at = None if spec.delivered_at_null else delivered_at_for(spec.elapsed_days)
                shipped_at = "2026-05-02T00:00:00Z"
                evidence_status = spec.evidence_status
                if evidence_status in {"VERIFIED", "REJECTED"}:
                    delivered_instant = datetime.fromisoformat((delivered_at or ordered_at).replace("Z", "+00:00"))
                    verified_by = "evidence-service-v2"
                    verified_at = utc_z(delivered_instant + timedelta(hours=1))
                    evidence_source = f"evidence://case/{spec.testcase_id}"
                    attested = 1
                else:
                    verified_by = verified_at = evidence_source = None
                    attested = 0
                if spec.evidence_inconsistent:
                    evidence_status = "NONE"
                connection.execute(
                    """INSERT INTO shipments(
                        shipment_id, order_item_id, shipped_at, delivered_at, package_opened,
                        issue_code, evidence_status, verified_by, verified_at,
                        evidence_source, attested
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        ids["shipment_id"], ids["order_item_id"], shipped_at, delivered_at,
                        None if spec.package_opened is None else int(spec.package_opened),
                        spec.issue_code, evidence_status, verified_by, verified_at,
                        evidence_source, attested,
                    ),
                )
            if spec.refund_status:
                connection.execute(
                    """INSERT INTO refunds(
                        refund_id, order_item_id, requested_at, status, amount, currency
                    ) VALUES (?, ?, ?, ?, ?, 'KRW')""",
                    (
                        f"RH-{spec.testcase_id}", ids["order_item_id"],
                        "2026-08-10T00:00:00Z", spec.refund_status, PAID_AMOUNT,
                    ),
                )
        connection.commit()
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"foreign key violations: {violations}")
        connection.execute("VACUUM")
    finally:
        connection.close()


def one_or_none(rows: list[sqlite3.Row]) -> Optional[sqlite3.Row]:
    return rows[0] if len(rows) == 1 else None


def adapt_policy_facts(connection: sqlite3.Connection, spec: CaseSpec) -> dict:
    connection.row_factory = sqlite3.Row
    ids = ids_for(spec)
    item_id = ids["order_item_id"]
    order_rows = connection.execute("SELECT * FROM orders WHERE order_item_id = ? ORDER BY order_item_id", (item_id,)).fetchall()
    order_row = one_or_none(order_rows)
    if order_row is None:
        customer_rows: list[sqlite3.Row] = []
        product_rows: list[sqlite3.Row] = []
    else:
        customer_rows = connection.execute("SELECT * FROM customers WHERE customer_id = ?", (order_row["customer_id"],)).fetchall()
        product_rows = connection.execute("SELECT * FROM products WHERE product_id = ?", (order_row["product_id"],)).fetchall()
    shipment_rows = connection.execute("SELECT * FROM shipments WHERE order_item_id = ? ORDER BY shipment_id", (item_id,)).fetchall()
    refund_rows = connection.execute("SELECT * FROM refunds WHERE order_item_id = ? ORDER BY refund_id", (item_id,)).fetchall()
    customer_row = one_or_none(customer_rows)
    product_row = one_or_none(product_rows)
    shipment_row = one_or_none(shipment_rows)

    order = None
    if order_row is not None:
        order = {
            "order_id": order_row["order_id"],
            "order_item_id": order_row["order_item_id"],
            "customer_id": order_row["customer_id"],
            "product_id": order_row["product_id"],
            "order_snapshot_id": order_row["order_snapshot_id"],
            "ordered_at": order_row["ordered_at"],
            "order_status": order_row["status"],
            "paid_item_amount": order_row["paid_item_amount"],
            "currency": order_row["currency"],
        }
    customer_snapshot = None
    if customer_row is not None and order_row is not None:
        customer_snapshot = {
            "customer_id": order_row["customer_id"],
            "order_snapshot_id": order_row["order_snapshot_id"],
            "customer_tier_at_order": order_row["customer_tier_at_order"],
            "snapshotted_at": order_row["ordered_at"],
        }
    product = None
    if product_row is not None and order_row is not None:
        product = {
            "product_id": order_row["product_id"],
            "order_snapshot_id": order_row["order_snapshot_id"],
            "category": order_row["product_category_at_order"],
            "final_sale": bool(order_row["product_final_sale_at_order"]),
            "snapshotted_at": order_row["ordered_at"],
        }
    shipment = None
    if shipment_row is not None:
        shipment = {
            "shipment_id": shipment_row["shipment_id"],
            "order_item_id": shipment_row["order_item_id"],
            "delivered_at": shipment_row["delivered_at"],
            "package_opened": None if shipment_row["package_opened"] is None else bool(shipment_row["package_opened"]),
            "issue_code": shipment_row["issue_code"],
            "evidence": {
                "evidence_status": shipment_row["evidence_status"],
                "verified_by": shipment_row["verified_by"],
                "verified_at": shipment_row["verified_at"],
                "evidence_source": shipment_row["evidence_source"],
                "provenance_attested": bool(shipment_row["attested"]),
            },
        }
    refund_history = [
        {
            "refund_id": row["refund_id"],
            "order_item_id": row["order_item_id"],
            "status": row["status"],
            "amount": row["amount"],
            "currency": row["currency"],
        }
        for row in refund_rows
    ]
    return {
        "trusted_context": {"evaluation_date": EVALUATION_DATE.isoformat(), "timezone": "Asia/Seoul"},
        "request": {
            "refund_request_id": f"RR-{spec.testcase_id}",
            "order_item_id": item_id,
            "requested_amount": spec.requested_amount,
            "currency": "KRW",
        },
        "lookup_counts": {
            "order_item_order": len(order_rows),
            "customer_snapshot": len(customer_rows),
            "product": len(product_rows),
            "shipment": len(shipment_rows),
        },
        "order": order,
        "customer_snapshot": customer_snapshot,
        "product": product,
        "shipment": shipment,
        "refund_history": refund_history,
    }


def pretty_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rebuild_shop_db_from_cases(shop_db: Path, records: list[dict]) -> None:
    if shop_db.exists():
        shop_db.unlink()
    connection = sqlite3.connect(shop_db)
    try:
        connection.executescript(DDL)
        for record in records:
            ids = record["target_ids"]
            customer_id = ids.get("customer_id")
            product_id = ids.get("product_id")
            order_id = ids.get("order_id")
            order_item_id = ids.get("order_item_id")
            shipment_id = ids.get("shipment_id")
            tags = set(record.get("coverage_tags", []))

            if customer_id is not None and product_id is not None and order_id is not None:
                connection.execute(
                    "INSERT INTO customers(customer_id, tier) VALUES (?, ?)",
                    (customer_id, "STANDARD"),
                )
                connection.execute(
                    "INSERT INTO products(product_id, category, final_sale, unit_price_krw) VALUES (?, ?, ?, ?)",
                    (product_id, "FASHION", 0, PAID_AMOUNT),
                )

            if order_id is not None and order_item_id is not None and customer_id is not None and product_id is not None:
                connection.execute(
                    """INSERT INTO orders(
                        order_item_id, order_id, customer_id, product_id, order_snapshot_id,
                        ordered_at, status, customer_tier_at_order,
                        product_category_at_order, product_final_sale_at_order,
                        paid_item_amount, currency
                    ) VALUES (?, ?, ?, ?, ?, ?, 'DELIVERED', ?, ?, ?, ?, 'KRW')""",
                    (
                        order_item_id,
                        order_id,
                        customer_id,
                        product_id,
                        f"SNAP-{record['testcase_id']}",
                        "2026-05-01T00:00:00Z",
                        "STANDARD",
                        "FASHION",
                        0,
                        PAID_AMOUNT,
                    ),
                )

            if shipment_id is not None and "SHIPMENT_DATA_MISSING" not in tags:
                connection.execute(
                    """INSERT INTO shipments(
                        shipment_id, order_item_id, shipped_at, delivered_at, package_opened,
                        issue_code, evidence_status, verified_by, verified_at,
                        evidence_source, attested
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        shipment_id,
                        order_item_id,
                        "2026-05-02T00:00:00Z",
                        "2026-08-15T00:00:00Z",
                        0,
                        None,
                        "NONE",
                        None,
                        None,
                        None,
                        0,
                    ),
                )

        connection.commit()
        connection.execute("PRAGMA foreign_key_check").fetchall()
        connection.execute("VACUUM")
    finally:
        connection.close()


def rebuild_answer_key_from_cases(answer_db: Path, records: list[dict]) -> None:
    if answer_db.exists():
        answer_db.unlink()
    connection = sqlite3.connect(answer_db)
    try:
        connection.executescript(
            """
            PRAGMA page_size = 4096;
            PRAGMA auto_vacuum = NONE;
            CREATE TABLE metadata (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE gold_test_cases (
              testcase_id TEXT PRIMARY KEY,
              difficulty TEXT NOT NULL CHECK (difficulty IN ('EASY','MEDIUM','HARD')),
              question TEXT NOT NULL,
              order_id TEXT,
              order_item_id TEXT NOT NULL,
              description TEXT NOT NULL,
              coverage_tags_json TEXT NOT NULL,
              required_fields_json TEXT NOT NULL,
              gold_decision TEXT NOT NULL CHECK (gold_decision IN ('APPROVE','REJECT','NEED_MORE_INFO','NOT_APPLICABLE')),
              gold_clauses_json TEXT NOT NULL,
              primary_clause TEXT NOT NULL,
              policy_facts_json TEXT NOT NULL,
              expected_result_json TEXT NOT NULL,
              policy_version TEXT NOT NULL,
              db_version TEXT NOT NULL,
              testcase_version TEXT NOT NULL,
              manual_review_status TEXT NOT NULL
            );
            """
        )
        metadata = {
            "policy_version": POLICY_VERSION,
            "db_version": DB_VERSION,
            "testcase_version": TESTCASE_VERSION,
            "record_count": str(len(records)),
            "difficulty_distribution": "EASY=20,MEDIUM=20,HARD=20",
            "independent_human_review": "PENDING",
            "agent_access": "DENY",
        }
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            sorted(metadata.items()),
        )
        for record in records:
            ids = record["target_ids"]
            expected = record["expected_result"]
            connection.execute(
                """INSERT INTO gold_test_cases(
                    testcase_id, difficulty, question, order_id, order_item_id,
                    description, coverage_tags_json, required_fields_json,
                    gold_decision, gold_clauses_json, primary_clause,
                    policy_facts_json, expected_result_json, policy_version,
                    db_version, testcase_version, manual_review_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record["testcase_id"],
                    record["difficulty"],
                    record["question"],
                    ids.get("order_id"),
                    ids["order_item_id"],
                    record.get("description", record["question"]),
                    json.dumps(record["coverage_tags"], ensure_ascii=False, separators=(",", ":")),
                    json.dumps(record["required_fields"], ensure_ascii=False, separators=(",", ":")),
                    record["gold_decision"],
                    json.dumps(record["gold_clauses"], ensure_ascii=False, separators=(",", ":")),
                    expected["primary_clause"],
                    json.dumps(record["policy_facts"], ensure_ascii=False, separators=(",", ":")),
                    json.dumps(expected, ensure_ascii=False, separators=(",", ":")),
                    POLICY_VERSION,
                    DB_VERSION,
                    TESTCASE_VERSION,
                    "PENDING_INDEPENDENT_HUMAN_REVIEW",
                ),
            )
        connection.commit()
    finally:
        connection.close()


def build_test_cases(shop_db: Path) -> list[dict]:
    connection = sqlite3.connect(shop_db)
    try:
        records = []
        for spec in CASES:
            facts = adapt_policy_facts(connection, spec)
            expected = decide(facts)
            gold_decision = GOLD_DECISION[expected["eligibility"]]
            manual_decision, manual_primary = MANUAL_EXPECTATIONS[spec.testcase_id]
            if (gold_decision, expected["primary_clause"]) != (manual_decision, manual_primary):
                raise AssertionError(
                    f"{spec.testcase_id}: Oracle {(gold_decision, expected['primary_clause'])} "
                    f"!= GOLD-10 scenario expectation {(manual_decision, manual_primary)}"
                )
            records.append(
                {
                    "testcase_id": spec.testcase_id,
                    "difficulty": spec.difficulty,
                    "question": spec.question,
                    "target_ids": ids_for(spec),
                    "description": spec.description,
                    "coverage_tags": list(spec.coverage_tags),
                    "required_fields": expected["required_fields"],
                    "gold_decision": gold_decision,
                    "gold_clauses": expected["matched_clauses"],
                    "policy_facts": facts,
                    "expected_result": expected,
                    "policy_version": POLICY_VERSION,
                    "db_version": DB_VERSION,
                    "testcase_version": TESTCASE_VERSION,
                    "versions": dict(VERSION_VECTOR),
                    "manual_review": {
                        "gold10_scenario_cross_check": "PASSED",
                        "expected_primary_clause": manual_primary,
                        "independent_human_review": "PENDING",
                    },
                }
            )
        return records
    finally:
        connection.close()


def build(output_root: Path = REPO_ROOT) -> Dict[str, str]:
    data_dir = output_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    source_dir = REPO_ROOT / "data"
    for name in ("shop.db", "test_cases.json", "agent_cases.json", "answer_key.db"):
        source = source_dir / name
        if source.exists():
            shutil.copy2(source, data_dir / name)

    test_cases_path = data_dir / "test_cases.json"
    records = json.loads(test_cases_path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise TypeError("test_cases.json must contain a list of records")

    files = {
        "data/shop.db": sha256_file(data_dir / "shop.db"),
        "data/test_cases.json": sha256_file(test_cases_path),
        "data/agent_cases.json": sha256_file(data_dir / "agent_cases.json"),
        "data/answer_key.db": sha256_file(data_dir / "answer_key.db"),
    }
    manifest = {
        "release_profile": "BASE",
        "baseline_status": "CANDIDATE_PENDING_INDEPENDENT_HUMAN_REVIEW",
        "policy_version": POLICY_VERSION,
        "db_version": DB_VERSION,
        "testcase_version": TESTCASE_VERSION,
        "core_version_vector": dict(VERSION_VECTOR),
        "testcase_count": len(records),
        "difficulty_counts": dict(Counter(record["difficulty"] for record in records)),
        "evaluation_date": EVALUATION_DATE.isoformat(),
        "timezone": "Asia/Seoul",
        "python_version": platform.python_version(),
        "sqlite_version": sqlite3.sqlite_version,
        "artifact_sha256": files,
        "source_policy_spec": "policies/refund_policy_spec_v0.5.md",
    }
    (data_dir / "version_manifest.json").write_bytes(pretty_json_bytes(manifest))
    return files


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()
    hashes = build(args.output_root.resolve())
    print(json.dumps(hashes, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
