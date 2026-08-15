"""Order & Refund Testbed v0.5 deterministic policy oracle.

Public API:
    decide(policy_facts: dict) -> dict

The function is deliberately pure: it performs no file/database writes, network
calls, clock reads, random operations, locale-dependent parsing, LLM calls, or
Gold-data reads.  Its only inputs are ``policy_facts`` and the immutable v0.5
registry in this module.

Input-contract violations raise :class:`InputContractError` and never produce a
DecisionResult.  Domain errors in a schema-valid input produce a normal v0.5
DecisionResult according to POL/REG clauses.

The canonical JSON serializer is sufficient for this schema's JSON domain
(objects, arrays, strings, booleans, null, and safe integers).  Floats are not
permitted by the input contract.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
from types import MappingProxyType
from typing import Any, Iterable, Mapping, MutableMapping, Sequence
from zoneinfo import ZoneInfo


SAFE_INTEGER = 9_007_199_254_740_991
SEOUL = ZoneInfo("Asia/Seoul")
UTC = timezone.utc
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class InputContractError(ValueError):
    """Raised when the argument violates SCHEMA-10's structural contract."""

    def __init__(self, errors: Sequence[str]):
        self.errors = tuple(sorted(set(errors)))
        super().__init__("PolicyFacts input contract rejected: " + "; ".join(self.errors))


@dataclass(frozen=True)
class Rule:
    priority: int
    reason_code: str
    terminal: bool
    outcome: tuple[str, str, str] | None = None


INFO = ("UNDETERMINED", "WAITING", "REQUEST_INFO")
CANCEL = ("NOT_APPLICABLE", "OUT_OF_SCOPE", "ROUTE_TO_CANCEL")
NO_ACTION = ("NOT_APPLICABLE", "COMPLETED", "NONE")
ALREADY_DONE = ("INELIGIBLE", "COMPLETED", "NONE")
WAIT = ("NOT_APPLICABLE", "WAITING", "WAIT_EXISTING_REQUEST")
REJECT = ("INELIGIBLE", "READY", "REJECT_REFUND")
MANUAL = ("NOT_APPLICABLE", "OUT_OF_SCOPE", "ROUTE_TO_MANUAL_REVIEW")
APPROVE = ("ELIGIBLE", "READY", "APPROVE_REFUND")


def _r(
    priority: int,
    reason_code: str,
    terminal: bool = True,
    outcome: tuple[str, str, str] | None = INFO,
) -> Rule:
    return Rule(priority, reason_code, terminal, outcome if terminal else None)


# REG-20 v0.5.  MappingProxyType prevents accidental runtime mutation.
REGISTRY: Mapping[str, Rule] = MappingProxyType(
    {
        "POL-10.14": _r(110, "INCONSISTENT_LOOKUP_RESULT"),
        "POL-10.15": _r(111, "ENTITY_REFERENCE_MISMATCH"),
        "POL-10.16": _r(112, "SNAPSHOT_REFERENCE_MISMATCH"),
        "POL-10.01": _r(120, "ORDER_NOT_FOUND"),
        "POL-10.09": _r(121, "NON_UNIQUE_ORDER"),
        "POL-10.02": _r(130, "CUSTOMER_DATA_MISSING"),
        "POL-10.10": _r(131, "NON_UNIQUE_CUSTOMER"),
        "POL-10.03": _r(140, "PRODUCT_DATA_MISSING"),
        "POL-10.11": _r(141, "NON_UNIQUE_PRODUCT"),
        "POL-10.04": _r(150, "SHIPMENT_DATA_MISSING"),
        "POL-10.12": _r(151, "NON_UNIQUE_SHIPMENT"),
        "POL-10.07": _r(160, "INVALID_ORDER_STATUS"),
        "POL-10.08": _r(161, "INCONSISTENT_ORDER_SHIPMENT_STATE"),
        "POL-10.05": _r(170, "CANCEL_FLOW_REQUIRED", outcome=CANCEL),
        "POL-10.06": _r(171, "ORDER_CANCELLED", outcome=NO_ACTION),
        "POL-50.10": _r(200, "INVALID_REFUND_HISTORY_RECORD"),
        "POL-50.03": _r(201, "INVALID_REFUND_STATUS"),
        "POL-50.01": _r(210, "ALREADY_REFUNDED", outcome=ALREADY_DONE),
        "POL-50.02": _r(211, "REFUND_IN_PROGRESS", outcome=WAIT),
        "POL-50.11": _r(212, "REFUND_REQUEST_ID_REUSED", outcome=NO_ACTION),
        "POL-50.09": _r(300, "CURRENCY_MISMATCH"),
        "POL-50.08": _r(301, "UNSUPPORTED_CURRENCY"),
        "POL-50.04": _r(310, "INVALID_REFUND_AMOUNT"),
        "POL-50.05": _r(311, "REFUND_AMOUNT_EXCEEDS_PAID", outcome=REJECT),
        "POL-50.06": _r(312, "PARTIAL_REFUND_OUT_OF_SCOPE", outcome=MANUAL),
        "POL-50.07": _r(320, "FULL_REFUND_AMOUNT_VALID", False),
        "POL-40.07": _r(400, "INVALID_EVIDENCE_STATUS"),
        "POL-40.04": _r(401, "INCONSISTENT_FAULT_EVIDENCE"),
        "POL-40.05": _r(402, "INVALID_ISSUE_CODE"),
        "POL-40.02": _r(403, "FAULT_EVIDENCE_REQUIRED"),
        "POL-40.06": _r(404, "EVIDENCE_PROVENANCE_MISSING"),
        "POL-40.08": _r(405, "UNTRUSTED_EVIDENCE_PROVENANCE"),
        "POL-40.03": _r(410, "EVIDENCE_REJECTED_NO_OVERRIDE", False),
        "POL-20.03": _r(500, "INVALID_CUSTOMER_TIER"),
        "POL-30.03": _r(501, "INVALID_PRODUCT_CATEGORY"),
        "POL-30.05": _r(502, "FINAL_SALE_UNKNOWN"),
        "POL-30.04": _r(503, "PACKAGE_OPENED_UNKNOWN"),
        "POL-20.05": _r(510, "INVALID_DATE_FORMAT"),
        "POL-20.04": _r(511, "INVALID_DATE_ORDER"),
        "POL-10.13": _r(512, "DELIVERED_AT_MISSING"),
        "POL-20.01": _r(520, "STANDARD_TIER_RULE_SELECTED", False),
        "POL-20.02": _r(521, "PREMIUM_TIER_RULE_SELECTED", False),
        "POL-40.01": _r(600, "VERIFIED_COMPANY_FAULT", outcome=APPROVE),
        "POL-30.01": _r(700, "FINAL_SALE_RESTRICTED", outcome=REJECT),
        "POL-30.02": _r(701, "OPENED_ELECTRONICS", outcome=REJECT),
        "POL-20.06": _r(720, "RETURN_WINDOW_EXPIRED", outcome=REJECT),
        "POL-00.08": _r(800, "REFUND_ELIGIBLE", outcome=APPROVE),
    }
)


VERSIONS: Mapping[str, str] = MappingProxyType(
    {
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
)


VALID_ORDER_STATUSES = frozenset({"PAID", "SHIPPED", "DELIVERED", "CANCELLED"})
VALID_REFUND_STATUSES = frozenset({"REQUESTED", "APPROVED", "REJECTED", "COMPLETED"})
ACTIVE_REFUND_STATUSES = frozenset({"REQUESTED", "APPROVED", "COMPLETED"})
VALID_TIERS = frozenset({"STANDARD", "PREMIUM"})
VALID_CATEGORIES = frozenset({"ELECTRONICS", "FASHION", "HOME", "BEAUTY", "OTHER"})
VALID_EVIDENCE_STATUSES = frozenset({"NONE", "PENDING", "VERIFIED", "REJECTED"})
VALID_ISSUE_CODES = frozenset({"WRONG_ITEM", "DAMAGED", "MISSING_PARTS", "DEFECTIVE"})
OVERRIDABLE = frozenset({"POL-30.01", "POL-30.02", "POL-20.06"})


_POLICY_FACTS_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "trusted_context",
        "request",
        "lookup_counts",
        "order",
        "customer_snapshot",
        "product",
        "shipment",
        "refund_history",
    ],
    "properties": {
        "trusted_context": {
            "type": "object",
            "additionalProperties": False,
            "required": ["evaluation_date", "timezone"],
            "properties": {
                "evaluation_date": {"type": "string"},
                "timezone": {"const": "Asia/Seoul"},
            },
        },
        "request": {
            "type": "object",
            "additionalProperties": False,
            "required": ["refund_request_id", "order_item_id", "requested_amount", "currency"],
            "properties": {
                "refund_request_id": {"type": "string", "minLength": 1},
                "order_item_id": {"type": "string", "minLength": 1},
                "requested_amount": {
                    "type": ["integer", "null"],
                    "minimum": -SAFE_INTEGER,
                    "maximum": SAFE_INTEGER,
                },
                "currency": {"type": ["string", "null"]},
            },
        },
        "lookup_counts": {
            "type": "object",
            "additionalProperties": False,
            "required": ["order_item_order", "customer_snapshot", "product", "shipment"],
            "properties": {
                key: {"type": "integer", "minimum": 0, "maximum": SAFE_INTEGER}
                for key in ("order_item_order", "customer_snapshot", "product", "shipment")
            },
        },
        "order": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": [
                "order_id",
                "order_item_id",
                "customer_id",
                "product_id",
                "order_snapshot_id",
                "ordered_at",
                "order_status",
                "paid_item_amount",
                "currency",
            ],
            "properties": {
                "order_id": {"type": "string", "minLength": 1},
                "order_item_id": {"type": "string", "minLength": 1},
                "customer_id": {"type": "string", "minLength": 1},
                "product_id": {"type": "string", "minLength": 1},
                "order_snapshot_id": {"type": "string", "minLength": 1},
                "ordered_at": {"type": "string"},
                "order_status": {"type": ["string", "null"]},
                "paid_item_amount": {
                    "type": ["integer", "null"],
                    "minimum": -SAFE_INTEGER,
                    "maximum": SAFE_INTEGER,
                },
                "currency": {"type": ["string", "null"]},
            },
        },
        "customer_snapshot": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["customer_id", "order_snapshot_id", "customer_tier_at_order", "snapshotted_at"],
            "properties": {
                "customer_id": {"type": "string", "minLength": 1},
                "order_snapshot_id": {"type": "string", "minLength": 1},
                "customer_tier_at_order": {"type": ["string", "null"]},
                "snapshotted_at": {"type": "string"},
            },
        },
        "product": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["product_id", "order_snapshot_id", "category", "final_sale", "snapshotted_at"],
            "properties": {
                "product_id": {"type": "string", "minLength": 1},
                "order_snapshot_id": {"type": "string", "minLength": 1},
                "category": {"type": ["string", "null"]},
                "final_sale": {"type": ["boolean", "null"]},
                "snapshotted_at": {"type": "string"},
            },
        },
        "shipment": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": [
                "shipment_id",
                "order_item_id",
                "delivered_at",
                "package_opened",
                "issue_code",
                "evidence",
            ],
            "properties": {
                "shipment_id": {"type": "string", "minLength": 1},
                "order_item_id": {"type": "string", "minLength": 1},
                "delivered_at": {"type": ["string", "null"]},
                "package_opened": {"type": ["boolean", "null"]},
                "issue_code": {"type": ["string", "null"]},
                "evidence": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "evidence_status",
                        "verified_by",
                        "verified_at",
                        "evidence_source",
                        "provenance_attested",
                    ],
                    "properties": {
                        "evidence_status": {"type": "string"},
                        "verified_by": {"type": ["string", "null"]},
                        "verified_at": {"type": ["string", "null"]},
                        "evidence_source": {"type": ["string", "null"]},
                        "provenance_attested": {"type": "boolean"},
                    },
                },
            },
        },
        "refund_history": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["refund_id", "order_item_id", "status", "amount", "currency"],
                "properties": {
                    "refund_id": {"type": "string", "minLength": 1},
                    "order_item_id": {"type": "string", "minLength": 1},
                    "status": {"type": ["string", "null"]},
                    "amount": {
                        "type": ["integer", "null"],
                        "minimum": -SAFE_INTEGER,
                        "maximum": SAFE_INTEGER,
                    },
                    "currency": {"type": ["string", "null"]},
                },
            },
        },
    },
}


def _pointer(path: str, token: Any) -> str:
    escaped = str(token).replace("~", "~0").replace("/", "~1")
    return f"{path}/{escaped}" if path else f"/{escaped}"


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _validate_schema(value: Any, schema: Mapping[str, Any], path: str, errors: list[str]) -> None:
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path or '/'}: expected constant {schema['const']!r}")
        return

    allowed = schema.get("type")
    if isinstance(allowed, str):
        allowed_types = (allowed,)
    else:
        allowed_types = tuple(allowed or ())
    actual = _json_type(value)
    if allowed_types and actual not in allowed_types:
        errors.append(f"{path or '/'}: expected {'|'.join(allowed_types)}, got {actual}")
        return

    if actual == "object":
        if not all(isinstance(key, str) for key in value):
            errors.append(f"{path or '/'}: object keys must be strings")
            return
        properties = schema.get("properties", {})
        required = schema.get("required", ())
        for key in required:
            if key not in value:
                errors.append(f"{_pointer(path, key)}: required property missing")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{_pointer(path, key)}: additional property is forbidden")
        for key, child_schema in properties.items():
            if key in value:
                _validate_schema(value[key], child_schema, _pointer(path, key), errors)
    elif actual == "array":
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                _validate_schema(item, item_schema, _pointer(path, index), errors)
    elif actual == "string":
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path or '/'}: string is shorter than minLength")
    elif actual == "integer":
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path or '/'}: integer is below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path or '/'}: integer is above maximum")


def _validate_input(policy_facts: Any) -> None:
    errors: list[str] = []
    _validate_schema(policy_facts, _POLICY_FACTS_SCHEMA, "", errors)
    if errors:
        raise InputContractError(errors)


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_DATETIME_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})"
    r"(?:\.(\d+))?([Zz]|[+-]\d{2}:\d{2})$"
)


@dataclass(frozen=True)
class _Instant:
    value: Fraction
    utc_second: datetime
    fraction_digits: str

    def canonical(self) -> str:
        fraction = self.fraction_digits.rstrip("0")
        suffix = f".{fraction}" if fraction else ""
        return self.utc_second.strftime("%Y-%m-%dT%H:%M:%S") + suffix + "Z"

    def seoul_date(self) -> date:
        return self.utc_second.astimezone(SEOUL).date()


def _parse_date(value: str) -> date:
    match = _DATE_RE.fullmatch(value)
    if not match:
        raise ValueError("not an RFC 3339 full-date")
    return date(*(int(part) for part in match.groups()))


def _parse_datetime(value: str) -> _Instant:
    match = _DATETIME_RE.fullmatch(value)
    if not match:
        raise ValueError("not an RFC 3339 date-time")
    year, month, day, hour, minute, second = (int(part) for part in match.groups()[:6])
    fraction_digits = match.group(7) or ""
    offset_text = match.group(8)
    if hour > 23 or minute > 59 or second > 59:
        raise ValueError("invalid clock time")
    if offset_text in {"Z", "z"}:
        offset = UTC
    else:
        sign = 1 if offset_text[0] == "+" else -1
        offset_hour = int(offset_text[1:3])
        offset_minute = int(offset_text[4:6])
        if offset_hour > 23 or offset_minute > 59:
            raise ValueError("invalid UTC offset")
        offset = timezone(sign * timedelta(hours=offset_hour, minutes=offset_minute))
    local = datetime(year, month, day, hour, minute, second, tzinfo=offset)
    utc_second = local.astimezone(UTC)
    delta = utc_second - _EPOCH
    whole_seconds = delta.days * 86_400 + delta.seconds
    fractional = Fraction(int(fraction_digits), 10 ** len(fraction_digits)) if fraction_digits else Fraction(0)
    return _Instant(Fraction(whole_seconds) + fractional, utc_second, fraction_digits)


def _midnight_after(evaluation_date: date) -> _Instant:
    local = datetime.combine(evaluation_date + timedelta(days=1), datetime.min.time(), SEOUL)
    utc_second = local.astimezone(UTC)
    delta = utc_second - _EPOCH
    return _Instant(Fraction(delta.days * 86_400 + delta.seconds), utc_second, "")


def canonical_json_bytes(value: Any) -> bytes:
    """Return deterministic UTF-8 JSON bytes for the v0.5 schema domain."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _add(
    matched: set[str],
    paths_by_clause: MutableMapping[str, set[str]],
    clause: str,
    paths: Iterable[str] = (),
) -> None:
    if clause not in REGISTRY:
        raise RuntimeError(f"unregistered clause: {clause}")
    matched.add(clause)
    paths_by_clause.setdefault(clause, set()).update(paths)


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and len(value) > 0


def decide(policy_facts: dict) -> dict:
    """Return a deterministic SCHEMA-20 DecisionResult for PolicyFacts v0.5.

    ``InputContractError`` is raised for S0 structural/type/safe-integer errors.
    The input object is never mutated.
    """

    _validate_input(policy_facts)
    facts = copy.deepcopy(policy_facts)
    facts["refund_history"].sort(key=lambda item: item["refund_id"])

    matched: set[str] = set()
    paths_by_clause: dict[str, set[str]] = {}

    request = facts["request"]
    counts = facts["lookup_counts"]
    entity_specs = (
        ("order_item_order", "order", "POL-10.01", "POL-10.09"),
        ("customer_snapshot", "customer_snapshot", "POL-10.02", "POL-10.10"),
        ("product", "product", "POL-10.03", "POL-10.11"),
        ("shipment", "shipment", "POL-10.04", "POL-10.12"),
    )
    entity_ok: dict[str, bool] = {}
    for count_key, object_key, missing_clause, duplicate_clause in entity_specs:
        count = counts[count_key]
        obj = facts[object_key]
        iff_ok = (count == 1) == (obj is not None)
        if not iff_ok:
            _add(
                matched,
                paths_by_clause,
                "POL-10.14",
                (f"/lookup_counts/{count_key}", f"/{object_key}"),
            )
            entity_ok[object_key] = False
        elif count == 0:
            _add(matched, paths_by_clause, missing_clause, (f"/{object_key}",))
            entity_ok[object_key] = False
        elif count >= 2:
            _add(matched, paths_by_clause, duplicate_clause, (f"/{object_key}",))
            entity_ok[object_key] = False
        else:
            entity_ok[object_key] = True

    order = facts["order"]
    customer = facts["customer_snapshot"]
    product = facts["product"]
    shipment = facts["shipment"]

    reference_paths: set[str] = set()
    if entity_ok["order"]:
        assert order is not None
        if request["order_item_id"] != order["order_item_id"]:
            reference_paths.update(("/request/order_item_id", "/order/order_item_id"))
    if entity_ok["shipment"]:
        assert shipment is not None
        if request["order_item_id"] != shipment["order_item_id"]:
            reference_paths.update(("/request/order_item_id", "/shipment/order_item_id"))
    if entity_ok["order"] and entity_ok["shipment"]:
        assert order is not None and shipment is not None
        if order["order_item_id"] != shipment["order_item_id"]:
            reference_paths.update(("/order/order_item_id", "/shipment/order_item_id"))
    if entity_ok["order"] and entity_ok["customer_snapshot"]:
        assert order is not None and customer is not None
        if order["customer_id"] != customer["customer_id"]:
            reference_paths.update(("/order/customer_id", "/customer_snapshot/customer_id"))
    if entity_ok["order"] and entity_ok["product"]:
        assert order is not None and product is not None
        if order["product_id"] != product["product_id"]:
            reference_paths.update(("/order/product_id", "/product/product_id"))
    if reference_paths:
        _add(matched, paths_by_clause, "POL-10.15", reference_paths)

    snapshot_paths: set[str] = set()
    if entity_ok["order"] and entity_ok["customer_snapshot"]:
        assert order is not None and customer is not None
        if order["order_snapshot_id"] != customer["order_snapshot_id"]:
            snapshot_paths.update(("/order/order_snapshot_id", "/customer_snapshot/order_snapshot_id"))
    if entity_ok["order"] and entity_ok["product"]:
        assert order is not None and product is not None
        if order["order_snapshot_id"] != product["order_snapshot_id"]:
            snapshot_paths.update(("/order/order_snapshot_id", "/product/order_snapshot_id"))
    if snapshot_paths:
        _add(matched, paths_by_clause, "POL-10.16", snapshot_paths)

    order_context_ok = bool(
        entity_ok["order"]
        and order is not None
        and request["order_item_id"] == order["order_item_id"]
    )
    shipment_context_ok = bool(
        entity_ok["shipment"]
        and shipment is not None
        and request["order_item_id"] == shipment["order_item_id"]
        and (not order_context_ok or order["order_item_id"] == shipment["order_item_id"])
    )
    customer_context_ok = bool(
        order_context_ok
        and entity_ok["customer_snapshot"]
        and customer is not None
        and order["customer_id"] == customer["customer_id"]
        and order["order_snapshot_id"] == customer["order_snapshot_id"]
    )
    product_context_ok = bool(
        order_context_ok
        and entity_ok["product"]
        and product is not None
        and order["product_id"] == product["product_id"]
        and order["order_snapshot_id"] == product["order_snapshot_id"]
    )

    # POL-10 order status.
    if order_context_ok:
        assert order is not None
        order_status = order["order_status"]
        if order_status not in VALID_ORDER_STATUSES:
            _add(matched, paths_by_clause, "POL-10.07", ("/order/order_status",))
        elif order_status in {"PAID", "SHIPPED"}:
            _add(matched, paths_by_clause, "POL-10.05")
        elif order_status == "CANCELLED":
            _add(matched, paths_by_clause, "POL-10.06")
        if (
            order_status in {"PAID", "SHIPPED"}
            and shipment_context_ok
            and shipment is not None
            and shipment["delivered_at"] is not None
        ):
            _add(
                matched,
                paths_by_clause,
                "POL-10.08",
                ("/order/order_status", "/shipment/delivered_at"),
            )

    # POL-50 refund-history integrity and state.
    history = facts["refund_history"]
    history_integrity_paths: set[str] = set()
    history_status_paths: set[str] = set()
    id_to_indexes: dict[str, list[int]] = {}
    active_indexes: list[int] = []
    paid_for_history = order["paid_item_amount"] if order_context_ok and order is not None else None
    order_currency_for_history = order["currency"] if order_context_ok and order is not None else None
    for index, record in enumerate(history):
        prefix = f"/refund_history/{index}"
        id_to_indexes.setdefault(record["refund_id"], []).append(index)
        if record["order_item_id"] != request["order_item_id"]:
            history_integrity_paths.add(f"{prefix}/order_item_id")
            history_integrity_paths.add("/request/order_item_id")
        if order_context_ok and order is not None and record["order_item_id"] != order["order_item_id"]:
            history_integrity_paths.add(f"{prefix}/order_item_id")
            history_integrity_paths.add("/order/order_item_id")
        amount = record["amount"]
        if amount is None or amount <= 0:
            history_integrity_paths.add(f"{prefix}/amount")
        elif isinstance(paid_for_history, int) and paid_for_history > 0 and amount > paid_for_history:
            history_integrity_paths.update((f"{prefix}/amount", "/order/paid_item_amount"))
        currency = record["currency"]
        if currency is None:
            history_integrity_paths.add(f"{prefix}/currency")
        elif order_currency_for_history is not None and currency != order_currency_for_history:
            history_integrity_paths.update((f"{prefix}/currency", "/order/currency"))
        status = record["status"]
        if status not in VALID_REFUND_STATUSES:
            history_status_paths.add(f"{prefix}/status")
        elif status in ACTIVE_REFUND_STATUSES:
            active_indexes.append(index)

    for indexes in id_to_indexes.values():
        if len(indexes) > 1:
            history_integrity_paths.update(f"/refund_history/{index}/refund_id" for index in indexes)
    if len(active_indexes) > 1:
        history_integrity_paths.update(f"/refund_history/{index}/status" for index in active_indexes)
    if history_integrity_paths:
        _add(matched, paths_by_clause, "POL-50.10", history_integrity_paths)
    if history_status_paths:
        _add(matched, paths_by_clause, "POL-50.03", history_status_paths)

    history_valid = not history_integrity_paths and not history_status_paths
    if history_valid:
        statuses = [record["status"] for record in history]
        if any(status in {"APPROVED", "COMPLETED"} for status in statuses):
            _add(matched, paths_by_clause, "POL-50.01")
        if "REQUESTED" in statuses:
            _add(matched, paths_by_clause, "POL-50.02")
        if any(
            record["status"] == "REJECTED"
            and record["refund_id"] == request["refund_request_id"]
            for record in history
        ):
            _add(matched, paths_by_clause, "POL-50.11")

    # POL-50 request/order currency and amount.
    if order_context_ok:
        assert order is not None
        request_currency = request["currency"]
        order_currency = order["currency"]
        if request_currency is not None and order_currency is not None and request_currency != order_currency:
            currency_paths: set[str] = set()
            if request_currency != "KRW":
                currency_paths.add("/request/currency")
            if order_currency != "KRW":
                currency_paths.add("/order/currency")
            if not currency_paths:
                currency_paths.update(("/request/currency", "/order/currency"))
            _add(matched, paths_by_clause, "POL-50.09", currency_paths)
            currency_valid = False
        elif request_currency != "KRW" or order_currency != "KRW":
            currency_paths = set()
            if request_currency != "KRW":
                currency_paths.add("/request/currency")
            if order_currency != "KRW":
                currency_paths.add("/order/currency")
            _add(matched, paths_by_clause, "POL-50.08", currency_paths)
            currency_valid = False
        else:
            currency_valid = True

        amount_paths: set[str] = set()
        paid_amount = order["paid_item_amount"]
        requested_amount = request["requested_amount"]
        if paid_amount is None or paid_amount <= 0:
            amount_paths.add("/order/paid_item_amount")
        if requested_amount is not None and requested_amount <= 0:
            amount_paths.add("/request/requested_amount")
        if amount_paths:
            _add(matched, paths_by_clause, "POL-50.04", amount_paths)
        elif currency_valid:
            assert isinstance(paid_amount, int)
            effective_requested_amount = paid_amount if requested_amount is None else requested_amount
            if effective_requested_amount > paid_amount:
                _add(matched, paths_by_clause, "POL-50.05")
            elif effective_requested_amount < paid_amount:
                _add(matched, paths_by_clause, "POL-50.06")
            else:
                _add(matched, paths_by_clause, "POL-50.07")

    # POL-40 evidence state machine.  provenance_attested is the immutable
    # evidence-validator-v2 result; this oracle does not invent an allowlist.
    evidence_candidate: str | None = None
    evidence = shipment["evidence"] if shipment_context_ok and shipment is not None else None
    if evidence is not None:
        evidence_prefix = "/shipment/evidence"
        evidence_status = evidence["evidence_status"]
        issue_code = shipment["issue_code"]
        if evidence_status not in VALID_EVIDENCE_STATUSES:
            _add(
                matched,
                paths_by_clause,
                "POL-40.07",
                (f"{evidence_prefix}/evidence_status",),
            )
        elif issue_code is not None and issue_code not in VALID_ISSUE_CODES:
            _add(matched, paths_by_clause, "POL-40.05", ("/shipment/issue_code",))
        else:
            provenance_keys = ("verified_by", "verified_at", "evidence_source")
            nonempty_provenance = {key: _nonempty(evidence[key]) for key in provenance_keys}
            combination_paths: set[str] = set()
            if evidence_status == "NONE":
                if issue_code is not None:
                    combination_paths.add("/shipment/issue_code")
                for key in provenance_keys:
                    if evidence[key] is not None:
                        combination_paths.add(f"{evidence_prefix}/{key}")
                if evidence["provenance_attested"]:
                    combination_paths.add(f"{evidence_prefix}/provenance_attested")
                if combination_paths:
                    _add(matched, paths_by_clause, "POL-40.04", combination_paths)
            elif evidence_status == "PENDING":
                if issue_code is None:
                    combination_paths.add("/shipment/issue_code")
                for key in provenance_keys:
                    if evidence[key] is not None:
                        combination_paths.add(f"{evidence_prefix}/{key}")
                if evidence["provenance_attested"]:
                    combination_paths.add(f"{evidence_prefix}/provenance_attested")
                if combination_paths:
                    _add(matched, paths_by_clause, "POL-40.04", combination_paths)
                else:
                    _add(
                        matched,
                        paths_by_clause,
                        "POL-40.02",
                        (
                            f"{evidence_prefix}/evidence_status",
                            f"{evidence_prefix}/verified_by",
                            f"{evidence_prefix}/verified_at",
                            f"{evidence_prefix}/evidence_source",
                            f"{evidence_prefix}/provenance_attested",
                        ),
                    )
            else:  # VERIFIED or REJECTED
                if issue_code is None:
                    _add(matched, paths_by_clause, "POL-40.04", ("/shipment/issue_code",))
                else:
                    missing_paths = {
                        f"{evidence_prefix}/{key}"
                        for key in provenance_keys
                        if not nonempty_provenance[key]
                    }
                    if missing_paths:
                        _add(matched, paths_by_clause, "POL-40.06", missing_paths)
                    elif not evidence["provenance_attested"]:
                        _add(
                            matched,
                            paths_by_clause,
                            "POL-40.08",
                            (f"{evidence_prefix}/provenance_attested",),
                        )
                    else:
                        evidence_candidate = evidence_status

    # POL-20/POL-30 domain values.
    tier: str | None = None
    if customer_context_ok:
        assert customer is not None
        candidate_tier = customer["customer_tier_at_order"]
        if candidate_tier not in VALID_TIERS:
            _add(
                matched,
                paths_by_clause,
                "POL-20.03",
                ("/customer_snapshot/customer_tier_at_order",),
            )
        else:
            tier = candidate_tier
            _add(
                matched,
                paths_by_clause,
                "POL-20.01" if tier == "STANDARD" else "POL-20.02",
            )

    category: str | None = None
    if product_context_ok:
        assert product is not None
        candidate_category = product["category"]
        if candidate_category not in VALID_CATEGORIES:
            _add(matched, paths_by_clause, "POL-30.03", ("/product/category",))
        else:
            category = candidate_category
        if product["final_sale"] is None:
            _add(matched, paths_by_clause, "POL-30.05", ("/product/final_sale",))
        elif product["final_sale"]:
            _add(matched, paths_by_clause, "POL-30.01")
        if category == "ELECTRONICS":
            assert shipment is None or isinstance(shipment, dict)
            if shipment_context_ok and shipment is not None:
                if shipment["package_opened"] is None:
                    _add(
                        matched,
                        paths_by_clause,
                        "POL-30.04",
                        ("/shipment/package_opened",),
                    )
                elif shipment["package_opened"]:
                    _add(matched, paths_by_clause, "POL-30.02")

    # POL-20 strict date parsing and canonical UTC-Z normalization.
    evaluation_date: date | None
    try:
        evaluation_date = _parse_date(facts["trusted_context"]["evaluation_date"])
        facts["trusted_context"]["evaluation_date"] = evaluation_date.isoformat()
    except (TypeError, ValueError):
        evaluation_date = None
        _add(
            matched,
            paths_by_clause,
            "POL-20.05",
            ("/trusted_context/evaluation_date",),
        )

    instants: dict[str, _Instant] = {}
    date_sources: list[tuple[str, str | None]] = []
    if order_context_ok and order is not None:
        date_sources.append(("/order/ordered_at", order["ordered_at"]))
    if customer_context_ok and customer is not None:
        date_sources.append(("/customer_snapshot/snapshotted_at", customer["snapshotted_at"]))
    if product_context_ok and product is not None:
        date_sources.append(("/product/snapshotted_at", product["snapshotted_at"]))
    if shipment_context_ok and shipment is not None and shipment["delivered_at"] is not None:
        date_sources.append(("/shipment/delivered_at", shipment["delivered_at"]))
    if evidence_candidate is not None and evidence is not None:
        date_sources.append(("/shipment/evidence/verified_at", evidence["verified_at"]))

    invalid_date_paths: set[str] = set()
    for path, raw_value in date_sources:
        assert isinstance(raw_value, str)
        try:
            parsed = _parse_datetime(raw_value)
            instants[path] = parsed
            if path == "/order/ordered_at":
                facts["order"]["ordered_at"] = parsed.canonical()
            elif path == "/customer_snapshot/snapshotted_at":
                facts["customer_snapshot"]["snapshotted_at"] = parsed.canonical()
            elif path == "/product/snapshotted_at":
                facts["product"]["snapshotted_at"] = parsed.canonical()
            elif path == "/shipment/delivered_at":
                facts["shipment"]["delivered_at"] = parsed.canonical()
            elif path == "/shipment/evidence/verified_at":
                facts["shipment"]["evidence"]["verified_at"] = parsed.canonical()
        except (TypeError, ValueError, OverflowError):
            invalid_date_paths.add(path)
    if invalid_date_paths:
        _add(matched, paths_by_clause, "POL-20.05", invalid_date_paths)

    date_order_paths: set[str] = set()
    ordered_path = "/order/ordered_at"
    customer_time_path = "/customer_snapshot/snapshotted_at"
    product_time_path = "/product/snapshotted_at"
    delivered_path = "/shipment/delivered_at"
    verified_path = "/shipment/evidence/verified_at"
    if ordered_path in instants and customer_time_path in instants:
        if instants[ordered_path].value != instants[customer_time_path].value:
            date_order_paths.update((ordered_path, customer_time_path))
    if ordered_path in instants and product_time_path in instants:
        if instants[ordered_path].value != instants[product_time_path].value:
            date_order_paths.update((ordered_path, product_time_path))
    if ordered_path in instants and delivered_path in instants:
        if instants[delivered_path].value < instants[ordered_path].value:
            date_order_paths.update((ordered_path, delivered_path))
    if evaluation_date is not None:
        cutoff = _midnight_after(evaluation_date)
        for path, instant in instants.items():
            if instant.value >= cutoff.value:
                date_order_paths.add(path)
    if verified_path in instants:
        if delivered_path in instants:
            if instants[verified_path].value < instants[delivered_path].value:
                date_order_paths.update((verified_path, delivered_path))
        elif shipment_context_ok and shipment is not None and shipment["delivered_at"] is None:
            if ordered_path in instants and instants[verified_path].value < instants[ordered_path].value:
                date_order_paths.update((verified_path, ordered_path))
    if date_order_paths:
        _add(matched, paths_by_clause, "POL-20.04", date_order_paths)

    # A VERIFIED/REJECTED evidence state becomes valid only after its timestamp
    # passes POL-20 parsing and temporal-order checks.
    evidence_time_valid = False
    if evidence_candidate is not None and verified_path in instants and evaluation_date is not None:
        evidence_related_order_error = verified_path in date_order_paths
        if delivered_path in invalid_date_paths:
            evidence_related_order_error = True
        if shipment is not None and shipment["delivered_at"] is None and ordered_path not in instants:
            evidence_related_order_error = True
        evidence_time_valid = not evidence_related_order_error
    verified_company_fault = evidence_candidate == "VERIFIED" and evidence_time_valid
    if verified_company_fault:
        _add(matched, paths_by_clause, "POL-40.01")
    elif evidence_candidate == "REJECTED" and evidence_time_valid:
        _add(matched, paths_by_clause, "POL-40.03")

    # delivered_at=null is permitted only by a fully valid VERIFIED company fault.
    if shipment_context_ok and shipment is not None and shipment["delivered_at"] is None:
        if not verified_company_fault:
            _add(matched, paths_by_clause, "POL-10.13", ("/shipment/delivered_at",))

    # REFUND-01/03 elapsed-day rules.  Do not evaluate a period on invalid dates.
    if (
        tier is not None
        and evaluation_date is not None
        and delivered_path in instants
        and delivered_path not in date_order_paths
    ):
        elapsed_days = (evaluation_date - instants[delivered_path].seoul_date()).days
        limit = 14 if tier == "STANDARD" else 30
        if elapsed_days > limit:
            _add(matched, paths_by_clause, "POL-20.06")

    terminal_matches = [clause for clause in matched if REGISTRY[clause].terminal]
    if not terminal_matches:
        _add(matched, paths_by_clause, "POL-00.08")
        terminal_matches = ["POL-00.08"]
    primary_clause = min(terminal_matches, key=lambda clause: REGISTRY[clause].priority)
    primary_rule = REGISTRY[primary_clause]
    if primary_rule.outcome is None:
        raise RuntimeError(f"terminal clause has no outcome: {primary_clause}")

    overridden_clauses: list[str] = []
    if primary_clause == "POL-40.01":
        overridden_clauses = sorted(matched.intersection(OVERRIDABLE))

    eligibility, case_status, next_action = primary_rule.outcome
    required_fields: list[str] = []
    if next_action == "REQUEST_INFO":
        required: set[str] = set()
        for clause in matched:
            rule = REGISTRY[clause]
            if rule.terminal and rule.outcome == INFO:
                required.update(paths_by_clause.get(clause, ()))
        required_fields = sorted(required)

    sorted_matched = sorted(matched)
    facts_hash = hashlib.sha256(canonical_json_bytes(facts)).hexdigest()
    result = {
        "eligibility": eligibility,
        "case_status": case_status,
        "next_action": next_action,
        "reason_code": primary_rule.reason_code,
        "primary_clause": primary_clause,
        "matched_clauses": sorted_matched,
        "overridden_clauses": overridden_clauses,
        "required_fields": required_fields,
        "facts": facts,
        "facts_hash": facts_hash,
        "versions": dict(VERSIONS),
    }

    # Runtime invariants from SCHEMA-20/VAL-10.
    if primary_clause not in matched:
        raise RuntimeError("primary_clause must be in matched_clauses")
    if not set(overridden_clauses).issubset(matched):
        raise RuntimeError("overridden_clauses must be a subset of matched_clauses")
    if sorted_matched != sorted(set(sorted_matched)):
        raise RuntimeError("matched_clauses must be unique and sorted")
    if overridden_clauses != sorted(set(overridden_clauses)):
        raise RuntimeError("overridden_clauses must be unique and sorted")
    if required_fields != sorted(set(required_fields)):
        raise RuntimeError("required_fields must be unique and sorted")
    return result


__all__ = [
    "InputContractError",
    "REGISTRY",
    "VERSIONS",
    "canonical_json_bytes",
    "decide",
]
