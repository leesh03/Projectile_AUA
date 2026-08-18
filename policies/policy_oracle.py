"""Deterministic Order & Refund policy oracle (policy-v0.5).

This module is an independent reference implementation of the policy contract.
It reads only canonical PolicyFacts supplied to :func:`decide`; it does not read
Gold answers, a database, the clock, environment variables, or the network.

The caller (Harness) must reject JSON/schema-invalid input before calling the
oracle.  A small dependency-free S0 validator is retained here so direct calls
fail with InputContractError instead of producing a DecisionResult.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import re
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo


SAFE_INTEGER = 9_007_199_254_740_991
SEOUL = ZoneInfo("Asia/Seoul")
RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

VERSION_VECTOR = {
    "policy_version": "policy-v0.5",
    "input_schema_version": "input-schema-v0.5",
    "output_schema_version": "output-schema-v0.5",
    "rule_registry_version": "registry-v0.5",
    "adapter_version": "adapter-v0.5",
    "evidence_validator_version": "evidence-validator-v2",
    "oracle_version": "oracle-v0.5",
    "gold_version": "gold-v0.5",
    "suite_version": "suite-v0.5",
    "evaluator_version": "evaluator-v0.5",
}


class InputContractError(ValueError):
    """Raised when a direct caller violates the SCHEMA-10/S0 contract."""

    def __init__(self, paths: Iterable[str]):
        self.paths = tuple(sorted(set(paths)))
        super().__init__("SCHEMA-10 input contract rejected: " + ", ".join(self.paths))


def _entry(
    priority: int,
    reason: str,
    terminal: bool,
    outcome: Optional[Tuple[str, str, str]] = None,
) -> Dict[str, Any]:
    return {
        "priority": priority,
        "reason_code": reason,
        "terminal": terminal,
        "outcome": outcome,
    }


INFO = ("UNDETERMINED", "WAITING", "REQUEST_INFO")
CANCEL = ("NOT_APPLICABLE", "OUT_OF_SCOPE", "ROUTE_TO_CANCEL")
COMPLETED_NONE = ("NOT_APPLICABLE", "COMPLETED", "NONE")
ALREADY_DONE = ("INELIGIBLE", "COMPLETED", "NONE")
WAIT_EXISTING = ("NOT_APPLICABLE", "WAITING", "WAIT_EXISTING_REQUEST")
REJECT = ("INELIGIBLE", "READY", "REJECT_REFUND")
MANUAL = ("NOT_APPLICABLE", "OUT_OF_SCOPE", "ROUTE_TO_MANUAL_REVIEW")
APPROVE = ("ELIGIBLE", "READY", "APPROVE_REFUND")


# REG-20 is the only priority source.  Nonterminal entries intentionally have
# no outcome and can never become primary.
REGISTRY: Dict[str, Dict[str, Any]] = {
    "POL-10.14": _entry(110, "INCONSISTENT_LOOKUP_RESULT", True, INFO),
    "POL-10.15": _entry(111, "ENTITY_REFERENCE_MISMATCH", True, INFO),
    "POL-10.16": _entry(112, "SNAPSHOT_REFERENCE_MISMATCH", True, INFO),
    "POL-10.01": _entry(120, "ORDER_NOT_FOUND", True, INFO),
    "POL-10.09": _entry(121, "NON_UNIQUE_ORDER", True, INFO),
    "POL-10.02": _entry(130, "CUSTOMER_DATA_MISSING", True, INFO),
    "POL-10.10": _entry(131, "NON_UNIQUE_CUSTOMER", True, INFO),
    "POL-10.03": _entry(140, "PRODUCT_DATA_MISSING", True, INFO),
    "POL-10.11": _entry(141, "NON_UNIQUE_PRODUCT", True, INFO),
    "POL-10.04": _entry(150, "SHIPMENT_DATA_MISSING", True, INFO),
    "POL-10.12": _entry(151, "NON_UNIQUE_SHIPMENT", True, INFO),
    "POL-10.07": _entry(160, "INVALID_ORDER_STATUS", True, INFO),
    "POL-10.08": _entry(161, "INCONSISTENT_ORDER_SHIPMENT_STATE", True, INFO),
    "POL-10.05": _entry(170, "CANCEL_FLOW_REQUIRED", True, CANCEL),
    "POL-10.06": _entry(171, "ORDER_CANCELLED", True, COMPLETED_NONE),
    "POL-50.10": _entry(200, "INVALID_REFUND_HISTORY_RECORD", True, INFO),
    "POL-50.03": _entry(201, "INVALID_REFUND_STATUS", True, INFO),
    "POL-50.01": _entry(210, "ALREADY_REFUNDED", True, ALREADY_DONE),
    "POL-50.02": _entry(211, "REFUND_IN_PROGRESS", True, WAIT_EXISTING),
    "POL-50.11": _entry(212, "REFUND_REQUEST_ID_REUSED", True, COMPLETED_NONE),
    "POL-50.09": _entry(300, "CURRENCY_MISMATCH", True, INFO),
    "POL-50.08": _entry(301, "UNSUPPORTED_CURRENCY", True, INFO),
    "POL-50.04": _entry(310, "INVALID_REFUND_AMOUNT", True, INFO),
    "POL-50.05": _entry(311, "REFUND_AMOUNT_EXCEEDS_PAID", True, REJECT),
    "POL-50.06": _entry(312, "PARTIAL_REFUND_OUT_OF_SCOPE", True, MANUAL),
    "POL-50.07": _entry(320, "FULL_REFUND_AMOUNT_VALID", False),
    "POL-40.07": _entry(400, "INVALID_EVIDENCE_STATUS", True, INFO),
    "POL-40.04": _entry(401, "INCONSISTENT_FAULT_EVIDENCE", True, INFO),
    "POL-40.05": _entry(402, "INVALID_ISSUE_CODE", True, INFO),
    "POL-40.02": _entry(403, "FAULT_EVIDENCE_REQUIRED", True, INFO),
    "POL-40.06": _entry(404, "EVIDENCE_PROVENANCE_MISSING", True, INFO),
    "POL-40.08": _entry(405, "UNTRUSTED_EVIDENCE_PROVENANCE", True, INFO),
    "POL-40.03": _entry(410, "EVIDENCE_REJECTED_NO_OVERRIDE", False),
    "POL-20.03": _entry(500, "INVALID_CUSTOMER_TIER", True, INFO),
    "POL-30.03": _entry(501, "INVALID_PRODUCT_CATEGORY", True, INFO),
    "POL-30.05": _entry(502, "FINAL_SALE_UNKNOWN", True, INFO),
    "POL-30.04": _entry(503, "PACKAGE_OPENED_UNKNOWN", True, INFO),
    "POL-20.05": _entry(510, "INVALID_DATE_FORMAT", True, INFO),
    "POL-20.04": _entry(511, "INVALID_DATE_ORDER", True, INFO),
    "POL-10.13": _entry(512, "DELIVERED_AT_MISSING", True, INFO),
    "POL-20.01": _entry(520, "STANDARD_TIER_RULE_SELECTED", False),
    "POL-20.02": _entry(521, "PREMIUM_TIER_RULE_SELECTED", False),
    "POL-40.01": _entry(600, "VERIFIED_COMPANY_FAULT", True, APPROVE),
    "POL-30.01": _entry(700, "FINAL_SALE_RESTRICTED", True, REJECT),
    "POL-30.02": _entry(701, "OPENED_ELECTRONICS", True, REJECT),
    "POL-20.06": _entry(720, "RETURN_WINDOW_EXPIRED", True, REJECT),
    "POL-00.08": _entry(800, "REFUND_ELIGIBLE", True, APPROVE),
}


TOP_KEYS = {
    "trusted_context",
    "request",
    "lookup_counts",
    "order",
    "customer_snapshot",
    "product",
    "shipment",
    "refund_history",
}
OBJECT_KEYS = {
    "trusted_context": {"evaluation_date", "timezone"},
    "request": {"refund_request_id", "order_item_id", "requested_amount", "currency"},
    "lookup_counts": {"order_item_order", "customer_snapshot", "product", "shipment"},
    "order": {
        "order_id", "order_item_id", "customer_id", "product_id",
        "order_snapshot_id", "ordered_at", "order_status",
        "paid_item_amount", "currency",
    },
    "customer_snapshot": {
        "customer_id", "order_snapshot_id", "customer_tier_at_order", "snapshotted_at",
    },
    "product": {"product_id", "order_snapshot_id", "category", "final_sale", "snapshotted_at"},
    "shipment": {
        "shipment_id", "order_item_id", "delivered_at", "package_opened",
        "issue_code", "evidence",
    },
    "evidence": {
        "evidence_status", "verified_by", "verified_at",
        "evidence_source", "provenance_attested",
    },
    "refund": {"refund_id", "order_item_id", "status", "amount", "currency"},
}


def _is_int(value: Any) -> bool:
    return type(value) is int


def _is_bool(value: Any) -> bool:
    return type(value) is bool


def _check_exact_object(value: Any, keys: Set[str], path: str, errors: Set[str]) -> bool:
    if not isinstance(value, dict):
        errors.add(path)
        return False
    actual = set(value)
    for key in keys - actual:
        errors.add(f"{path}/{key}")
    for key in actual - keys:
        errors.add(f"{path}/{key}")
    return actual == keys


def _check_string(value: Any, path: str, errors: Set[str], nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str) or not value:
        errors.add(path)


def _check_nullable_string(value: Any, path: str, errors: Set[str]) -> None:
    if value is not None and not isinstance(value, str):
        errors.add(path)


def _check_amount(value: Any, path: str, errors: Set[str], nullable: bool) -> None:
    if value is None and nullable:
        return
    if not _is_int(value) or abs(value) > SAFE_INTEGER:
        errors.add(path)


def _validate_input_contract(facts: Any) -> None:
    errors: Set[str] = set()
    if not _check_exact_object(facts, TOP_KEYS, "", errors):
        raise InputContractError(errors or {""})

    for name in ("trusted_context", "request", "lookup_counts"):
        _check_exact_object(facts[name], OBJECT_KEYS[name], f"/{name}", errors)

    tc = facts["trusted_context"]
    if isinstance(tc, dict):
        _check_string(tc.get("evaluation_date"), "/trusted_context/evaluation_date", errors)
        if tc.get("timezone") != "Asia/Seoul":
            errors.add("/trusted_context/timezone")

    request = facts["request"]
    if isinstance(request, dict):
        _check_string(request.get("refund_request_id"), "/request/refund_request_id", errors)
        _check_string(request.get("order_item_id"), "/request/order_item_id", errors)
        _check_amount(request.get("requested_amount"), "/request/requested_amount", errors, True)
        _check_nullable_string(request.get("currency"), "/request/currency", errors)

    counts = facts["lookup_counts"]
    if isinstance(counts, dict):
        for name in OBJECT_KEYS["lookup_counts"]:
            value = counts.get(name)
            if not _is_int(value) or value < 0 or value > SAFE_INTEGER:
                errors.add(f"/lookup_counts/{name}")

    for name in ("order", "customer_snapshot", "product", "shipment"):
        value = facts[name]
        if value is not None:
            _check_exact_object(value, OBJECT_KEYS[name], f"/{name}", errors)

    order = facts["order"]
    if isinstance(order, dict):
        for field in ("order_id", "order_item_id", "customer_id", "product_id", "order_snapshot_id", "ordered_at"):
            _check_string(order.get(field), f"/order/{field}", errors)
        _check_nullable_string(order.get("order_status"), "/order/order_status", errors)
        _check_amount(order.get("paid_item_amount"), "/order/paid_item_amount", errors, True)
        _check_nullable_string(order.get("currency"), "/order/currency", errors)

    customer = facts["customer_snapshot"]
    if isinstance(customer, dict):
        for field in ("customer_id", "order_snapshot_id", "snapshotted_at"):
            _check_string(customer.get(field), f"/customer_snapshot/{field}", errors)
        _check_nullable_string(customer.get("customer_tier_at_order"), "/customer_snapshot/customer_tier_at_order", errors)

    product = facts["product"]
    if isinstance(product, dict):
        for field in ("product_id", "order_snapshot_id", "snapshotted_at"):
            _check_string(product.get(field), f"/product/{field}", errors)
        _check_nullable_string(product.get("category"), "/product/category", errors)
        if product.get("final_sale") is not None and not _is_bool(product.get("final_sale")):
            errors.add("/product/final_sale")

    shipment = facts["shipment"]
    if isinstance(shipment, dict):
        for field in ("shipment_id", "order_item_id"):
            _check_string(shipment.get(field), f"/shipment/{field}", errors)
        _check_nullable_string(shipment.get("delivered_at"), "/shipment/delivered_at", errors)
        if shipment.get("package_opened") is not None and not _is_bool(shipment.get("package_opened")):
            errors.add("/shipment/package_opened")
        _check_nullable_string(shipment.get("issue_code"), "/shipment/issue_code", errors)
        evidence = shipment.get("evidence")
        if _check_exact_object(evidence, OBJECT_KEYS["evidence"], "/shipment/evidence", errors):
            _check_string(evidence.get("evidence_status"), "/shipment/evidence/evidence_status", errors)
            for field in ("verified_by", "verified_at", "evidence_source"):
                _check_nullable_string(evidence.get(field), f"/shipment/evidence/{field}", errors)
            if not _is_bool(evidence.get("provenance_attested")):
                errors.add("/shipment/evidence/provenance_attested")

    history = facts["refund_history"]
    if not isinstance(history, list):
        errors.add("/refund_history")
    else:
        for index, record in enumerate(history):
            path = f"/refund_history/{index}"
            if not _check_exact_object(record, OBJECT_KEYS["refund"], path, errors):
                continue
            _check_string(record.get("refund_id"), f"{path}/refund_id", errors)
            _check_string(record.get("order_item_id"), f"{path}/order_item_id", errors)
            _check_nullable_string(record.get("status"), f"{path}/status", errors)
            _check_amount(record.get("amount"), f"{path}/amount", errors, True)
            _check_nullable_string(record.get("currency"), f"{path}/currency", errors)

    if errors:
        raise InputContractError(errors)


def _jcs_bytes(value: Any) -> bytes:
    """RFC 8785-compatible serialization for the SCHEMA-10 value domain.

    PolicyFacts contains strings, booleans, nulls and safe integers only.  Its
    keys are ASCII, so Python's sorted compact JSON encoding is JCS-equivalent.
    """

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonical_facts(facts: Mapping[str, Any]) -> Dict[str, Any]:
    canonical = deepcopy(facts)
    canonical["refund_history"] = sorted(
        canonical["refund_history"],
        key=lambda row: (row["refund_id"], _jcs_bytes(row)),
    )
    return canonical


def _parse_date(value: Any) -> Optional[date]:
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not RFC3339_RE.fullmatch(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _match(
    matched: Set[str],
    fields: MutableMapping[str, Set[str]],
    clause: str,
    paths: Iterable[str] = (),
) -> None:
    matched.add(clause)
    fields.setdefault(clause, set()).update(paths)


def _lookup_validation(
    facts: Mapping[str, Any], matched: Set[str], fields: MutableMapping[str, Set[str]]
) -> None:
    mapping = {
        "order_item_order": ("order", "POL-10.01", "POL-10.09"),
        "customer_snapshot": ("customer_snapshot", "POL-10.02", "POL-10.10"),
        "product": ("product", "POL-10.03", "POL-10.11"),
        "shipment": ("shipment", "POL-10.04", "POL-10.12"),
    }
    for count_name, (object_name, missing_clause, duplicate_clause) in mapping.items():
        count = facts["lookup_counts"][count_name]
        obj = facts[object_name]
        count_path = f"/lookup_counts/{count_name}"
        object_path = f"/{object_name}"
        iff_valid = (count == 1 and obj is not None) or (count != 1 and obj is None)
        if not iff_valid:
            _match(matched, fields, "POL-10.14", (count_path, object_path))
        elif count == 0:
            _match(matched, fields, missing_clause, (object_path,))
        elif count >= 2:
            _match(matched, fields, duplicate_clause, (object_path,))


def _reference_validation(
    facts: Mapping[str, Any], matched: Set[str], fields: MutableMapping[str, Set[str]]
) -> None:
    request = facts["request"]
    order = facts["order"]
    customer = facts["customer_snapshot"]
    product = facts["product"]
    shipment = facts["shipment"]

    mismatches: Set[str] = set()
    if order is not None:
        if request["order_item_id"] != order["order_item_id"]:
            mismatches.update(("/request/order_item_id", "/order/order_item_id"))
        if shipment is not None and order["order_item_id"] != shipment["order_item_id"]:
            mismatches.update(("/order/order_item_id", "/shipment/order_item_id"))
        if customer is not None and order["customer_id"] != customer["customer_id"]:
            mismatches.update(("/order/customer_id", "/customer_snapshot/customer_id"))
        if product is not None and order["product_id"] != product["product_id"]:
            mismatches.update(("/order/product_id", "/product/product_id"))
    if mismatches:
        _match(matched, fields, "POL-10.15", mismatches)

    snapshot_mismatches: Set[str] = set()
    if order is not None and customer is not None and product is not None:
        snapshot_ids = {
            order["order_snapshot_id"],
            customer["order_snapshot_id"],
            product["order_snapshot_id"],
        }
        if len(snapshot_ids) != 1:
            snapshot_mismatches.update(
                (
                    "/order/order_snapshot_id",
                    "/customer_snapshot/order_snapshot_id",
                    "/product/order_snapshot_id",
                )
            )
    if snapshot_mismatches:
        _match(matched, fields, "POL-10.16", snapshot_mismatches)


def _order_validation(
    facts: Mapping[str, Any], matched: Set[str], fields: MutableMapping[str, Set[str]]
) -> None:
    order = facts["order"]
    shipment = facts["shipment"]
    if order is None:
        return
    status = order["order_status"]
    if status not in {"PAID", "SHIPPED", "DELIVERED", "CANCELLED"}:
        _match(matched, fields, "POL-10.07", ("/order/order_status",))
        return
    if status in {"PAID", "SHIPPED"}:
        if shipment is not None and shipment["delivered_at"] is not None:
            _match(
                matched,
                fields,
                "POL-10.08",
                ("/order/order_status", "/shipment/delivered_at"),
            )
        _match(matched, fields, "POL-10.05")
    elif status == "CANCELLED":
        _match(matched, fields, "POL-10.06")


def _refund_history_validation(
    facts: Mapping[str, Any], matched: Set[str], fields: MutableMapping[str, Set[str]]
) -> None:
    request = facts["request"]
    order = facts["order"]
    history = facts["refund_history"]
    paid = order["paid_item_amount"] if order is not None else None
    order_currency = order["currency"] if order is not None else None

    invalid_paths: Set[str] = set()
    status_paths: Set[str] = set()
    ids: Dict[str, list[int]] = {}
    active_indices: list[int] = []
    approved_or_completed = False
    requested = False
    reused_rejected = False

    for index, record in enumerate(history):
        base = f"/refund_history/{index}"
        ids.setdefault(record["refund_id"], []).append(index)
        status = record["status"]
        if status not in {"REQUESTED", "APPROVED", "REJECTED", "COMPLETED"}:
            status_paths.add(f"{base}/status")
        else:
            if status in {"REQUESTED", "APPROVED", "COMPLETED"}:
                active_indices.append(index)
            approved_or_completed = approved_or_completed or status in {"APPROVED", "COMPLETED"}
            requested = requested or status == "REQUESTED"
            reused_rejected = reused_rejected or (
                status == "REJECTED" and record["refund_id"] == request["refund_request_id"]
            )

        if record["order_item_id"] != request["order_item_id"]:
            invalid_paths.update((f"{base}/order_item_id", "/request/order_item_id"))
        if order is not None and record["order_item_id"] != order["order_item_id"]:
            invalid_paths.update((f"{base}/order_item_id", "/order/order_item_id"))
        amount = record["amount"]
        if amount is None or amount <= 0 or (paid is not None and paid > 0 and amount > paid):
            invalid_paths.add(f"{base}/amount")
        if record["currency"] is None or record["currency"] != order_currency:
            invalid_paths.add(f"{base}/currency")

    for duplicate_indices in ids.values():
        if len(duplicate_indices) > 1:
            invalid_paths.update(f"/refund_history/{i}/refund_id" for i in duplicate_indices)
    if len(active_indices) > 1:
        invalid_paths.update(f"/refund_history/{i}/status" for i in active_indices)

    if invalid_paths:
        _match(matched, fields, "POL-50.10", invalid_paths)
    if status_paths:
        _match(matched, fields, "POL-50.03", status_paths)
    if approved_or_completed:
        _match(matched, fields, "POL-50.01")
    if requested:
        _match(matched, fields, "POL-50.02")
    if reused_rejected:
        _match(matched, fields, "POL-50.11")


def _money_validation(
    facts: Mapping[str, Any], matched: Set[str], fields: MutableMapping[str, Set[str]]
) -> None:
    request = facts["request"]
    order = facts["order"]
    if order is None:
        return

    request_currency = request["currency"]
    order_currency = order["currency"]
    if request_currency is not None and order_currency is not None and request_currency != order_currency:
        paths: Set[str] = set()
        if request_currency == "KRW" and order_currency != "KRW":
            paths.add("/order/currency")
        elif order_currency == "KRW" and request_currency != "KRW":
            paths.add("/request/currency")
        else:
            paths.update(("/request/currency", "/order/currency"))
        _match(matched, fields, "POL-50.09", paths)

    unsupported: Set[str] = set()
    if request_currency != "KRW":
        unsupported.add("/request/currency")
    if order_currency != "KRW":
        unsupported.add("/order/currency")
    if unsupported:
        _match(matched, fields, "POL-50.08", unsupported)

    paid = order["paid_item_amount"]
    requested = request["requested_amount"]
    invalid_amounts: Set[str] = set()
    if paid is None or paid <= 0:
        invalid_amounts.add("/order/paid_item_amount")
    if requested is not None and requested <= 0:
        invalid_amounts.add("/request/requested_amount")
    if invalid_amounts:
        _match(matched, fields, "POL-50.04", invalid_amounts)
        return
    effective = paid if requested is None else requested
    if effective > paid:
        _match(matched, fields, "POL-50.05")
    elif effective < paid:
        _match(matched, fields, "POL-50.06")
    else:
        _match(matched, fields, "POL-50.07")


def _evidence_prevalidation(
    facts: Mapping[str, Any], matched: Set[str], fields: MutableMapping[str, Set[str]]
) -> Tuple[Optional[str], bool]:
    shipment = facts["shipment"]
    if shipment is None:
        return None, False
    evidence = shipment["evidence"]
    status = evidence["evidence_status"]
    issue = shipment["issue_code"]
    valid_statuses = {"NONE", "PENDING", "VERIFIED", "REJECTED"}
    valid_issues = {"DAMAGED", "WRONG_ITEM", "MISSING_PARTS", "DEFECTIVE"}
    if status not in valid_statuses:
        _match(matched, fields, "POL-40.07", ("/shipment/evidence/evidence_status",))
        return None, False
    if issue is not None and issue not in valid_issues:
        _match(matched, fields, "POL-40.05", ("/shipment/issue_code",))
        return None, False

    provenance_paths = {
        "/shipment/evidence/verified_by",
        "/shipment/evidence/verified_at",
        "/shipment/evidence/evidence_source",
    }
    values = (
        evidence["verified_by"],
        evidence["verified_at"],
        evidence["evidence_source"],
    )

    if status in {"NONE", "PENDING"}:
        expected_issue = issue is None if status == "NONE" else issue in valid_issues
        combo_valid = expected_issue and all(value is None for value in values) and not evidence["provenance_attested"]
        if not combo_valid:
            paths = {"/shipment/issue_code", "/shipment/evidence/provenance_attested"}
            paths.update(provenance_paths)
            _match(matched, fields, "POL-40.04", paths)
            return None, False
        if status == "PENDING":
            _match(
                matched,
                fields,
                "POL-40.02",
                {
                    "/shipment/evidence/evidence_status",
                    "/shipment/evidence/verified_by",
                    "/shipment/evidence/verified_at",
                    "/shipment/evidence/evidence_source",
                    "/shipment/evidence/provenance_attested",
                },
            )
        return status, True

    # VERIFIED and REJECTED require a valid issue and complete provenance.
    if issue not in valid_issues:
        _match(matched, fields, "POL-40.04", ("/shipment/issue_code",))
        return None, False
    provenance = {
        "/shipment/evidence/verified_by": evidence["verified_by"],
        "/shipment/evidence/verified_at": evidence["verified_at"],
        "/shipment/evidence/evidence_source": evidence["evidence_source"],
    }
    missing = {path for path, value in provenance.items() if value is None}
    if missing:
        _match(matched, fields, "POL-40.06", missing)
        return None, False

    # The canonical PolicyFacts contract exposes the signed validator result as
    # provenance_attested; it does not expose signatures or the concrete v2
    # allow-list.  Non-empty provenance plus this trusted attestation is the
    # only deterministic decision available to this pure oracle.
    untrusted: Set[str] = set()
    if not evidence["provenance_attested"]:
        untrusted.add("/shipment/evidence/provenance_attested")
    if not evidence["verified_by"]:
        untrusted.add("/shipment/evidence/verified_by")
    if not evidence["evidence_source"]:
        untrusted.add("/shipment/evidence/evidence_source")
    if untrusted:
        _match(matched, fields, "POL-40.08", untrusted)
        return None, False
    return status, True


def _core_domain_validation(
    facts: Mapping[str, Any],
    evidence_status: Optional[str],
    evidence_state_valid: bool,
    matched: Set[str],
    fields: MutableMapping[str, Set[str]],
) -> Dict[str, Any]:
    order = facts["order"]
    customer = facts["customer_snapshot"]
    product = facts["product"]
    shipment = facts["shipment"]

    tier_valid = False
    category_valid = False
    product_flags_valid = False

    if customer is not None:
        tier = customer["customer_tier_at_order"]
        tier_valid = tier in {"STANDARD", "PREMIUM"}
        if not tier_valid:
            _match(matched, fields, "POL-20.03", ("/customer_snapshot/customer_tier_at_order",))

    if product is not None:
        category = product["category"]
        category_valid = category in {"ELECTRONICS", "FASHION", "HOME", "BEAUTY", "OTHER"}
        if not category_valid:
            _match(matched, fields, "POL-30.03", ("/product/category",))
        final_sale_valid = product["final_sale"] is not None
        if not final_sale_valid:
            _match(matched, fields, "POL-30.05", ("/product/final_sale",))
        package_valid = not (
            category == "ELECTRONICS" and shipment is not None and shipment["package_opened"] is None
        )
        if not package_valid:
            _match(matched, fields, "POL-30.04", ("/shipment/package_opened",))
        product_flags_valid = category_valid and final_sale_valid and package_valid

    eval_date = _parse_date(facts["trusted_context"]["evaluation_date"])
    invalid_date_paths: Set[str] = set()
    parsed: Dict[str, Optional[datetime]] = {}
    date_values: list[Tuple[str, Any]] = []
    if eval_date is None:
        invalid_date_paths.add("/trusted_context/evaluation_date")
    if order is not None:
        date_values.append(("/order/ordered_at", order["ordered_at"]))
    if customer is not None:
        date_values.append(("/customer_snapshot/snapshotted_at", customer["snapshotted_at"]))
    if product is not None:
        date_values.append(("/product/snapshotted_at", product["snapshotted_at"]))
    if shipment is not None and shipment["delivered_at"] is not None:
        date_values.append(("/shipment/delivered_at", shipment["delivered_at"]))
    if (
        shipment is not None
        and evidence_status in {"VERIFIED", "REJECTED"}
        and shipment["evidence"]["verified_at"] is not None
    ):
        date_values.append(("/shipment/evidence/verified_at", shipment["evidence"]["verified_at"]))
    for path, value in date_values:
        parsed[path] = _parse_datetime(value)
        if parsed[path] is None:
            invalid_date_paths.add(path)
    if invalid_date_paths:
        _match(matched, fields, "POL-20.05", invalid_date_paths)

    date_order_paths: Set[str] = set()
    if not invalid_date_paths and eval_date is not None:
        ordered = parsed.get("/order/ordered_at")
        customer_at = parsed.get("/customer_snapshot/snapshotted_at")
        product_at = parsed.get("/product/snapshotted_at")
        delivered = parsed.get("/shipment/delivered_at")
        verified_at = parsed.get("/shipment/evidence/verified_at")
        if ordered and customer_at and product_at and not (ordered == customer_at == product_at):
            date_order_paths.update(
                ("/order/ordered_at", "/customer_snapshot/snapshotted_at", "/product/snapshotted_at")
            )
        if ordered and delivered and delivered < ordered:
            date_order_paths.update(("/order/ordered_at", "/shipment/delivered_at"))
        cutoff = datetime.combine(eval_date + timedelta(days=1), time.min, tzinfo=SEOUL).astimezone(timezone.utc)
        for path, instant in parsed.items():
            if instant is not None and instant >= cutoff:
                date_order_paths.add(path)
        if verified_at is not None:
            lower = delivered if delivered is not None else ordered
            if lower is not None and verified_at < lower:
                date_order_paths.update(("/shipment/evidence/verified_at", "/shipment/delivered_at" if delivered else "/order/ordered_at"))
    if date_order_paths:
        _match(matched, fields, "POL-20.04", date_order_paths)

    verified = evidence_status == "VERIFIED" and evidence_state_valid and not invalid_date_paths and not date_order_paths
    if shipment is not None and shipment["delivered_at"] is None and not verified:
        _match(matched, fields, "POL-10.13", ("/shipment/delivered_at",))

    return {
        "tier_valid": tier_valid,
        "category_valid": category_valid,
        "product_flags_valid": product_flags_valid,
        "eval_date": eval_date,
        "parsed": parsed,
        "date_valid": not invalid_date_paths and not date_order_paths,
        "verified": verified,
    }


def _business_predicates(
    facts: Mapping[str, Any],
    domain: Mapping[str, Any],
    evidence_status: Optional[str],
    evidence_state_valid: bool,
    matched: Set[str],
    fields: MutableMapping[str, Set[str]],
) -> None:
    order = facts["order"]
    customer = facts["customer_snapshot"]
    product = facts["product"]
    shipment = facts["shipment"]

    if evidence_status == "VERIFIED" and domain["verified"]:
        _match(matched, fields, "POL-40.01")
    elif evidence_status == "REJECTED" and evidence_state_valid and domain["date_valid"]:
        _match(matched, fields, "POL-40.03")

    delivered_order = order is not None and order["order_status"] == "DELIVERED"
    if not delivered_order:
        return

    if customer is not None and domain["tier_valid"]:
        tier = customer["customer_tier_at_order"]
        _match(matched, fields, "POL-20.01" if tier == "STANDARD" else "POL-20.02")

    if product is not None and shipment is not None and domain["product_flags_valid"]:
        if product["final_sale"] is True:
            _match(matched, fields, "POL-30.01")
        if product["category"] == "ELECTRONICS" and shipment["package_opened"] is True:
            _match(matched, fields, "POL-30.02")

    if (
        customer is not None
        and shipment is not None
        and shipment["delivered_at"] is not None
        and domain["tier_valid"]
        and domain["date_valid"]
        and domain["eval_date"] is not None
    ):
        delivered = domain["parsed"].get("/shipment/delivered_at")
        if delivered is not None:
            elapsed = (domain["eval_date"] - delivered.astimezone(SEOUL).date()).days
            limit = 14 if customer["customer_tier_at_order"] == "STANDARD" else 30
            if elapsed > limit:
                _match(matched, fields, "POL-20.06")


def decide(policy_facts: dict) -> dict:
    """Return the deterministic SCHEMA-20 DecisionResult for PolicyFacts.

    The function is pure: no clock, locale, random source, network, file, DB,
    environment or Gold answer is read.  Structural contract violations raise
    InputContractError and are never serialized as policy decisions.
    """

    _validate_input_contract(policy_facts)
    facts = _canonical_facts(policy_facts)
    matched: Set[str] = set()
    required_by_clause: Dict[str, Set[str]] = {}

    _lookup_validation(facts, matched, required_by_clause)
    _reference_validation(facts, matched, required_by_clause)
    _order_validation(facts, matched, required_by_clause)
    _refund_history_validation(facts, matched, required_by_clause)
    _money_validation(facts, matched, required_by_clause)
    evidence_status, evidence_state_valid = _evidence_prevalidation(
        facts, matched, required_by_clause
    )
    domain = _core_domain_validation(
        facts,
        evidence_status,
        evidence_state_valid,
        matched,
        required_by_clause,
    )
    _business_predicates(
        facts,
        domain,
        evidence_status,
        evidence_state_valid,
        matched,
        required_by_clause,
    )

    terminals = {clause for clause in matched if REGISTRY[clause]["terminal"]}
    if not terminals:
        matched.add("POL-00.08")
        terminals.add("POL-00.08")
    primary = min(terminals, key=lambda clause: REGISTRY[clause]["priority"])
    rule = REGISTRY[primary]
    eligibility, case_status, next_action = rule["outcome"]

    overridden: Set[str] = set()
    if primary == "POL-40.01":
        overridden = matched.intersection({"POL-30.01", "POL-30.02", "POL-20.06"})

    required: Set[str] = set()
    if next_action == "REQUEST_INFO":
        for clause in terminals:
            if REGISTRY[clause]["outcome"] == INFO:
                required.update(required_by_clause.get(clause, set()))

    facts_hash = hashlib.sha256(_jcs_bytes(facts)).hexdigest()
    result = {
        "eligibility": eligibility,
        "case_status": case_status,
        "next_action": next_action,
        "reason_code": rule["reason_code"],
        "primary_clause": primary,
        "matched_clauses": sorted(matched),
        "overridden_clauses": sorted(overridden),
        "required_fields": sorted(required),
        "facts": facts,
        "facts_hash": facts_hash,
        "versions": dict(VERSION_VECTOR),
    }
    if primary not in matched or not overridden.issubset(matched):
        raise AssertionError("DecisionResult clause invariants violated")
    return result


def decision_bytes(policy_facts: dict) -> bytes:
    """Return the canonical UTF-8 bytes used for deterministic byte comparison."""

    return _jcs_bytes(decide(policy_facts))


__all__ = [
    "InputContractError",
    "REGISTRY",
    "VERSION_VECTOR",
    "decide",
    "decision_bytes",
]
