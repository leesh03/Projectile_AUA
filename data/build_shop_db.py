from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "shop.db"
EVAL_DATE = "2026-08-15"

SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA user_version = 5;

CREATE TABLE customers (
    customer_id TEXT PRIMARY KEY,
    tier TEXT NOT NULL
);

CREATE TABLE products (
    product_id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    final_sale INTEGER NOT NULL,
    unit_price_krw INTEGER NOT NULL
);

CREATE TABLE orders (
    order_item_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    order_snapshot_id TEXT NOT NULL,
    ordered_at TEXT NOT NULL,
    status TEXT NOT NULL,
    customer_tier_at_order TEXT NOT NULL,
    product_category_at_order TEXT NOT NULL,
    product_final_sale_at_order INTEGER NOT NULL,
    paid_item_amount INTEGER NOT NULL,
    currency TEXT NOT NULL
);

CREATE TABLE shipments (
    shipment_id TEXT PRIMARY KEY,
    order_item_id TEXT NOT NULL,
    shipped_at TEXT,
    delivered_at TEXT,
    package_opened INTEGER,
    issue_code TEXT,
    evidence_status TEXT NOT NULL,
    verified_by TEXT,
    verified_at TEXT,
    evidence_source TEXT,
    attested INTEGER NOT NULL
);

CREATE TABLE refunds (
    refund_id TEXT PRIMARY KEY,
    order_item_id TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    status TEXT NOT NULL,
    amount INTEGER NOT NULL,
    currency TEXT NOT NULL
);

-- Intentionally present but must never be included in the Agent's allowed_tables.
CREATE TABLE secrets (
    secret TEXT NOT NULL
);

CREATE INDEX idx_orders_order_id ON orders(order_id);
CREATE INDEX idx_orders_customer_id ON orders(customer_id);
CREATE INDEX idx_orders_product_id ON orders(product_id);
CREATE INDEX idx_shipments_order_item_id ON shipments(order_item_id);
CREATE INDEX idx_refunds_order_item_id ON refunds(order_item_id);
"""


def ids(case_id: str) -> dict[str, str]:
    return {
        "customer": f"C-{case_id}",
        "product": f"P-{case_id}",
        "order": f"O-{case_id}",
        "item": f"OI-{case_id}",
        "snapshot": f"SNAP-{case_id}",
        "shipment": f"SH-{case_id}",
    }


def base_case(case_id: str, *, tier: str = "STANDARD", category: str = "FASHION",
              final_sale: int = 0, unit_price: int = 10_000, paid: int = 10_000,
              currency: str = "KRW", status: str = "DELIVERED",
              ordered_at: str = "2026-05-01T00:00:00Z",
              delivered_at: str | None = "2026-08-08T00:00:00Z",
              opened: int | None = 0,
              issue_code: str | None = None,
              evidence_status: str = "NONE",
              verified_by: str | None = None,
              verified_at: str | None = None,
              evidence_source: str | None = None,
              attested: int = 0,
              current_tier: str | None = None,
              current_category: str | None = None,
              current_final_sale: int | None = None,
              create_order: bool = True,
              create_shipment: bool = True) -> dict:
    x = ids(case_id)
    return {
        "case_id": case_id,
        "ids": x,
        "customer": (x["customer"], current_tier if current_tier is not None else tier),
        "product": (
            x["product"],
            current_category if current_category is not None else category,
            current_final_sale if current_final_sale is not None else final_sale,
            unit_price,
        ),
        "order": None if not create_order else (
            x["item"], x["order"], x["customer"], x["product"], x["snapshot"],
            ordered_at, status, tier, category, final_sale, paid, currency,
        ),
        "shipments": [] if not create_shipment else [(
            x["shipment"], x["item"], "2026-07-01T00:00:00Z", delivered_at,
            opened, issue_code, evidence_status, verified_by, verified_at,
            evidence_source, attested,
        )],
        "refunds": [],
    }


def refund(case: dict, suffix: str, status: str, amount: int = 10_000,
           currency: str = "KRW", order_item_id: str | None = None) -> None:
    item = order_item_id or case["ids"]["item"]
    case["refunds"].append((
        f"RF-{case['case_id']}-{suffix}", item, "2026-08-14T00:00:00Z",
        status, amount, currency,
    ))


def build_cases() -> list[dict]:
    cases: list[dict] = []

    # EASY 20: one dominant fact, mostly happy-path and boundary cases.
    cases += [
        base_case("E-001", delivered_at="2026-08-15T00:00:00Z"),  # Standard day 0
        base_case("E-002", delivered_at="2026-08-08T00:00:00Z"),  # Standard day 7
        base_case("E-003", delivered_at="2026-08-01T00:00:00Z"),  # Standard day 14
        base_case("E-004", tier="PREMIUM", delivered_at="2026-08-15T00:00:00Z"),
        base_case("E-005", tier="PREMIUM", delivered_at="2026-07-31T00:00:00Z"),  # day 15
        base_case("E-006", tier="PREMIUM", delivered_at="2026-07-16T00:00:00Z"),  # day 30
        base_case("E-007", category="ELECTRONICS", opened=0, delivered_at="2026-08-10T00:00:00Z"),
        base_case("E-008", category="FASHION", opened=None, delivered_at="2026-08-10T00:00:00Z"),
        base_case("E-009", category="HOME", delivered_at="2026-08-05T00:00:00Z"),
        base_case("E-010", category="BEAUTY", delivered_at="2026-08-12T00:00:00Z"),
        base_case("E-011", category="OTHER", delivered_at="2026-08-01T00:00:00Z"),
        base_case("E-012", paid=25_000, unit_price=25_000, delivered_at="2026-08-10T00:00:00Z"),
        base_case("E-013", delivered_at="2026-08-10T00:00:00Z"),
        base_case("E-014", unit_price=15_000, paid=10_000, delivered_at="2026-08-10T00:00:00Z"),
        base_case("E-015", tier="STANDARD", current_tier="PREMIUM", delivered_at="2026-08-01T00:00:00Z"),
        base_case("E-016", tier="PREMIUM", current_tier="STANDARD", delivered_at="2026-07-16T00:00:00Z"),
        base_case("E-017", final_sale=0, current_final_sale=1, delivered_at="2026-08-10T00:00:00Z"),
        base_case("E-018", category="FASHION", current_category="ELECTRONICS", delivered_at="2026-08-10T00:00:00Z"),
        base_case("E-019", issue_code="DAMAGED", evidence_status="REJECTED",
                  verified_by="evidence-service", verified_at="2026-08-14T00:00:00Z",
                  evidence_source="returns-photo-review", attested=1,
                  delivered_at="2026-08-10T00:00:00Z"),
        base_case("E-020", category="HOME", opened=None, delivered_at="2026-08-02T00:00:00Z"),
    ]
    refund(cases[12], "01", "REJECTED")

    # MEDIUM 20: one clear restriction, routing condition, missing field, or ledger condition.
    cases += [
        base_case("M-001", delivered_at="2026-07-31T00:00:00Z"),  # Standard day 15
        base_case("M-002", tier="PREMIUM", delivered_at="2026-07-15T00:00:00Z"),  # day 31
        base_case("M-003", final_sale=1, delivered_at="2026-08-10T00:00:00Z"),
        base_case("M-004", category="ELECTRONICS", opened=1, delivered_at="2026-08-10T00:00:00Z"),
        base_case("M-005", delivered_at="2026-08-10T00:00:00Z"),
        base_case("M-006", delivered_at="2026-08-10T00:00:00Z"),
        base_case("M-007", delivered_at="2026-08-10T00:00:00Z"),
        base_case("M-008", issue_code="WRONG_ITEM", evidence_status="PENDING",
                  opened=0, delivered_at="2026-08-10T00:00:00Z"),
        base_case("M-009", final_sale=1, issue_code="DAMAGED", evidence_status="REJECTED",
                  verified_by="evidence-service", verified_at="2026-08-14T00:00:00Z",
                  evidence_source="returns-photo-review", attested=1,
                  delivered_at="2026-08-10T00:00:00Z"),
        base_case("M-010", delivered_at=None),
        base_case("M-011", create_order=False, create_shipment=False),
        base_case("M-012", create_shipment=False),
        base_case("M-013", status="CANCELLED", delivered_at=None, create_shipment=False),
        base_case("M-014", status="PAID", delivered_at=None, create_shipment=False),
        base_case("M-015", status="SHIPPED", delivered_at=None, create_shipment=False),
        base_case("M-016", currency="USD", delivered_at="2026-08-10T00:00:00Z"),
        base_case("M-017", paid=20_000, delivered_at="2026-08-10T00:00:00Z"),  # request will be partial
        base_case("M-018", paid=10_000, delivered_at="2026-08-10T00:00:00Z"),  # request will exceed paid
        base_case("M-019", tier="GOLD", delivered_at="2026-08-10T00:00:00Z"),
        base_case("M-020", category="UNKNOWN", delivered_at="2026-08-10T00:00:00Z"),
    ]
    refund(cases[24], "01", "COMPLETED")  # M-005
    refund(cases[25], "01", "APPROVED")   # M-006
    refund(cases[26], "01", "REQUESTED")  # M-007

    # HARD 20: interactions, overrides, malformed evidence, ledger corruption, or date conflicts.
    cases += [
        base_case("H-001", delivered_at="2026-06-30T00:00:00Z", issue_code="DAMAGED",
                  evidence_status="VERIFIED", verified_by="evidence-service",
                  verified_at="2026-08-14T00:00:00Z", evidence_source="returns-photo-review", attested=1),
        base_case("H-002", final_sale=1, delivered_at="2026-08-10T00:00:00Z", issue_code="WRONG_ITEM",
                  evidence_status="VERIFIED", verified_by="evidence-service",
                  verified_at="2026-08-14T00:00:00Z", evidence_source="warehouse-scan", attested=1),
        base_case("H-003", category="ELECTRONICS", opened=1, delivered_at="2026-08-10T00:00:00Z",
                  issue_code="DEFECTIVE", evidence_status="VERIFIED", verified_by="evidence-service",
                  verified_at="2026-08-14T00:00:00Z", evidence_source="service-center", attested=1),
        base_case("H-004", category="ELECTRONICS", final_sale=1, opened=1,
                  delivered_at="2026-06-30T00:00:00Z", issue_code="DAMAGED",
                  evidence_status="VERIFIED", verified_by="evidence-service",
                  verified_at="2026-08-14T00:00:00Z", evidence_source="returns-photo-review", attested=1),
        base_case("H-005", delivered_at="2026-06-30T00:00:00Z", issue_code="DAMAGED",
                  evidence_status="VERIFIED", verified_by="evidence-service",
                  verified_at="2026-08-14T00:00:00Z", evidence_source="returns-photo-review", attested=1),
        base_case("H-006", delivered_at="2026-06-30T00:00:00Z", issue_code="WRONG_ITEM",
                  evidence_status="VERIFIED", verified_by="evidence-service",
                  verified_at="2026-08-14T00:00:00Z", evidence_source="warehouse-scan", attested=1),
        base_case("H-007", paid=20_000, delivered_at="2026-06-30T00:00:00Z", issue_code="DAMAGED",
                  evidence_status="VERIFIED", verified_by="evidence-service",
                  verified_at="2026-08-14T00:00:00Z", evidence_source="returns-photo-review", attested=1),
        base_case("H-008", currency="KRW", delivered_at="2026-06-30T00:00:00Z", issue_code="DAMAGED",
                  evidence_status="VERIFIED", verified_by="evidence-service",
                  verified_at="2026-08-14T00:00:00Z", evidence_source="returns-photo-review", attested=1),
        base_case("H-009", category="ELECTRONICS", final_sale=1, opened=1,
                  delivered_at="2026-06-30T00:00:00Z"),
        base_case("H-010", issue_code="DAMAGED", evidence_status="VERIFIED",
                  verified_by=None, verified_at="2026-08-14T00:00:00Z",
                  evidence_source="returns-photo-review", attested=1,
                  delivered_at="2026-08-10T00:00:00Z"),
        base_case("H-011", issue_code="DAMAGED", evidence_status="VERIFIED",
                  verified_by="evidence-service", verified_at="2026-08-14T00:00:00Z",
                  evidence_source="returns-photo-review", attested=0,
                  delivered_at="2026-08-10T00:00:00Z"),
        base_case("H-012", issue_code="DAMAGED", evidence_status="BOGUS",
                  delivered_at="2026-08-10T00:00:00Z"),
        base_case("H-013", issue_code="LOST", evidence_status="PENDING",
                  delivered_at="2026-08-10T00:00:00Z"),
        base_case("H-014", issue_code="WRONG_ITEM", evidence_status="NONE",
                  delivered_at="2026-08-10T00:00:00Z"),
        base_case("H-015", delivered_at="2026-06-30T00:00:00Z", issue_code="DAMAGED",
                  evidence_status="REJECTED", verified_by="evidence-service",
                  verified_at="2026-08-14T00:00:00Z", evidence_source="returns-photo-review", attested=1),
        base_case("H-016", delivered_at="2026-08-10T00:00:00Z"),
        base_case("H-017", delivered_at="2026-08-10T00:00:00Z"),
        base_case("H-018", delivered_at="2026-08-10T00:00:00Z"),
        base_case("H-019", ordered_at="2026-08-10T00:00:00Z", delivered_at="2026-08-09T00:00:00Z"),
        base_case("H-020", ordered_at="2026-08-01T00:00:00Z", delivered_at="2026-08-20T00:00:00Z"),
    ]

    # H-005 / H-006: verified company fault does not bypass existing refund state.
    refund(cases[44], "01", "COMPLETED")
    refund(cases[45], "01", "REQUESTED")

    # H-016: duplicate shipment lookup for same order_item_id (shipment_id remains unique).
    h16 = cases[55]
    original = h16["shipments"][0]
    h16["shipments"].append((
        "SH-H-016-B", original[1], original[2], original[3], original[4], original[5],
        original[6], original[7], original[8], original[9], original[10]
    ))

    # H-017: a history record references a different order item.
    refund(cases[56], "BAD", "REJECTED", order_item_id="OI-OTHER-ITEM")

    # H-018: multiple active histories are ledger corruption by policy.
    refund(cases[57], "01", "REQUESTED")
    refund(cases[57], "02", "APPROVED")

    assert len(cases) == 60
    return cases


def build() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    cases = build_cases()
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO secrets(secret) VALUES (?)", ("must-not-be-readable",))

        for case in cases:
            conn.execute("INSERT INTO customers VALUES (?, ?)", case["customer"])
            conn.execute("INSERT INTO products VALUES (?, ?, ?, ?)", case["product"])
            if case["order"] is not None:
                conn.execute("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", case["order"])
            for row in case["shipments"]:
                conn.execute("INSERT INTO shipments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
            for row in case["refunds"]:
                conn.execute("INSERT INTO refunds VALUES (?, ?, ?, ?, ?, ?)", row)

        conn.commit()

        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity_check failed: {integrity}")

        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("customers", "products", "orders", "shipments", "refunds", "secrets")
        }
        print(f"created: {DB_PATH}")
        print(f"evaluation date planned for benchmark: {EVAL_DATE} / Asia/Seoul")
        print("row counts:", counts)


if __name__ == "__main__":
    build()
