"""Deterministic policy evaluator rebuilt from refund_policy_spec_v0.5.md.

This module is local runtime code, not the team Gold Oracle.  It never reads
Gold answers and is safe to use as a model-independent integration baseline.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from policy_runtime.loader import Clause, PolicyRuleSet

SAFE_INTEGER = 2**53 - 1
RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


class InputContractError(ValueError):
    """A structural input error; no policy DecisionResult may be created."""

    def __init__(self, paths: set[str] | list[str] | tuple[str, ...]) -> None:
        self.paths = tuple(sorted(set(paths)))
        super().__init__(f"PolicyFacts input contract failed: {', '.join(self.paths)}")


@dataclass(frozen=True, slots=True)
class PolicyDecisionResult:
    value: dict[str, Any]

    @property
    def decision(self) -> str:
        return {
            "ELIGIBLE": "APPROVE",
            "INELIGIBLE": "REJECT",
            "UNDETERMINED": "NEED_MORE_INFO",
            "NOT_APPLICABLE": "NOT_APPLICABLE",
        }[self.value["eligibility"]]


class PolicyEngine:
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

    def __init__(self, rules: PolicyRuleSet) -> None:
        self.rules = rules
        self._matched: set[str] = set()
        self._fields: dict[str, set[str]] = {}

    @classmethod
    def from_path(cls, path: str | Path) -> "PolicyEngine":
        return cls(PolicyRuleSet.load(path))

    @staticmethod
    def _canonical_bytes(value: Any) -> bytes:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")

    @staticmethod
    def _is_amount(value: Any) -> bool:
        return value is None or (
            type(value) is int and -SAFE_INTEGER <= value <= SAFE_INTEGER
        )

    @staticmethod
    def _valid_scalar(value: Any, *, nullable: bool = False) -> bool:
        if value is None:
            return nullable
        return isinstance(value, str) and bool(value.strip())

    def _check_object(
        self, value: Any, keys: set[str], path: str, errors: set[str], *, nullable: bool = False
    ) -> bool:
        if value is None and nullable:
            return False
        if not isinstance(value, dict):
            errors.add(path)
            return False
        for key in keys - value.keys():
            errors.add(f"{path}/{key}")
        for key in value.keys() - keys:
            errors.add(f"{path}/{key}")
        return not bool(keys - value.keys())

    def _normalize_input(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(raw, Mapping):
            raise InputContractError({"/"})
        errors: set[str] = set()
        missing = self.TOP_KEYS - raw.keys()
        for key in missing:
            errors.add(f"/{key}")
        unknown = raw.keys() - self.TOP_KEYS - {"target_ids"}
        for key in unknown:
            errors.add(f"/{key}")
        if errors:
            raise InputContractError(errors)
        facts = copy.deepcopy({key: raw[key] for key in self.TOP_KEYS})

        for name in ("trusted_context", "request", "lookup_counts"):
            self._check_object(facts[name], self.OBJECT_KEYS[name], f"/{name}", errors)
        for name in ("order", "customer_snapshot", "product", "shipment"):
            self._check_object(
                facts[name], self.OBJECT_KEYS[name], f"/{name}", errors, nullable=True
            )
        if isinstance(facts.get("shipment"), dict):
            self._check_object(
                facts["shipment"].get("evidence"),
                self.OBJECT_KEYS["evidence"],
                "/shipment/evidence",
                errors,
            )
        history = facts.get("refund_history")
        if not isinstance(history, list):
            errors.add("/refund_history")
        else:
            for index, record in enumerate(history):
                self._check_object(
                    record, self.OBJECT_KEYS["refund"], f"/refund_history/{index}", errors
                )

        if not errors:
            context = facts["trusted_context"]
            request = facts["request"]
            if not self._valid_scalar(context["evaluation_date"]):
                errors.add("/trusted_context/evaluation_date")
            if not self._valid_scalar(context["timezone"]):
                errors.add("/trusted_context/timezone")
            for key in ("refund_request_id", "order_item_id"):
                if not self._valid_scalar(request[key]):
                    errors.add(f"/request/{key}")
            if not self._valid_scalar(request["currency"], nullable=True):
                errors.add("/request/currency")
            if not self._is_amount(request["requested_amount"]):
                errors.add("/request/requested_amount")
            for key, value in facts["lookup_counts"].items():
                if type(value) is not int or value < 0:
                    errors.add(f"/lookup_counts/{key}")
            for name in ("order", "customer_snapshot", "product", "shipment"):
                obj = facts[name]
                if obj is not None:
                    for key, value in obj.items():
                        if key in {"paid_item_amount"} and not self._is_amount(value):
                            errors.add(f"/{name}/{key}")
                        if key in {"final_sale", "package_opened"} and value is not None and type(value) is not bool:
                            errors.add(f"/{name}/{key}")
            if isinstance(facts.get("shipment"), dict):
                attested = facts["shipment"]["evidence"].get("provenance_attested")
                if type(attested) is not bool:
                    errors.add("/shipment/evidence/provenance_attested")
            if isinstance(history, list):
                for index, record in enumerate(history):
                    if not isinstance(record, dict):
                        continue
                    if not self._is_amount(record.get("amount")):
                        errors.add(f"/refund_history/{index}/amount")
        if errors:
            raise InputContractError(errors)
        return facts

    def _match(self, clause_id: str, paths: set[str] | tuple[str, ...] | list[str] = ()) -> None:
        self.rules.clause(clause_id)
        self._matched.add(clause_id)
        self._fields.setdefault(clause_id, set()).update(paths)

    def _lookup_validation(self, facts: dict[str, Any]) -> None:
        pairs = (
            ("order_item_order", "order", "POL-10.01", "POL-10.09"),
            ("customer_snapshot", "customer_snapshot", "POL-10.02", "POL-10.10"),
            ("product", "product", "POL-10.03", "POL-10.11"),
            ("shipment", "shipment", "POL-10.04", "POL-10.12"),
        )
        for count_key, object_key, missing_clause, duplicate_clause in pairs:
            count = facts["lookup_counts"][count_key]
            obj = facts[object_key]
            paths = {f"/lookup_counts/{count_key}", f"/{object_key}"}
            if (count == 1) != (obj is not None):
                self._match("POL-10.14", paths)
            elif count == 0:
                self._match(missing_clause, {f"/{object_key}"})
            elif count > 1:
                self._match(duplicate_clause, {f"/{object_key}"})

        request = facts["request"]
        order = facts["order"]
        customer = facts["customer_snapshot"]
        product = facts["product"]
        shipment = facts["shipment"]
        mismatches: set[str] = set()
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
            self._match("POL-10.15", mismatches)
        if order is not None and customer is not None and product is not None:
            snapshot_values = {
                order["order_snapshot_id"], customer["order_snapshot_id"], product["order_snapshot_id"]
            }
            if len(snapshot_values) != 1:
                self._match(
                    "POL-10.16",
                    {
                        "/order/order_snapshot_id",
                        "/customer_snapshot/order_snapshot_id",
                        "/product/order_snapshot_id",
                    },
                )

    def _order_validation(self, facts: dict[str, Any]) -> None:
        order = facts["order"]
        shipment = facts["shipment"]
        if order is None:
            return
        status = order["order_status"]
        if status not in self.rules.order_statuses:
            self._match("POL-10.07", {"/order/order_status"})
            return
        if status in {"PAID", "SHIPPED"}:
            if shipment is not None and shipment["delivered_at"] is not None:
                self._match(
                    "POL-10.08", {"/order/order_status", "/shipment/delivered_at"}
                )
            self._match("POL-10.05")
        elif status == "CANCELLED":
            self._match("POL-10.06")

    def _refund_history_validation(self, facts: dict[str, Any]) -> None:
        request = facts["request"]
        order = facts["order"]
        history = facts["refund_history"]
        paid = order["paid_item_amount"] if order is not None else None
        currency = order["currency"] if order is not None else None
        invalid: set[str] = set()
        invalid_status: set[str] = set()
        ids: dict[str, list[int]] = {}
        active: list[int] = []
        approved_or_completed = False
        requested = False
        reused_rejected = False
        for index, record in enumerate(history):
            base = f"/refund_history/{index}"
            refund_id = record["refund_id"]
            ids.setdefault(str(refund_id), []).append(index)
            if not isinstance(refund_id, str) or not refund_id.strip():
                invalid.add(f"{base}/refund_id")
            status = record["status"]
            if status not in self.rules.refund_statuses:
                invalid_status.add(f"{base}/status")
            else:
                if status in {"REQUESTED", "APPROVED", "COMPLETED"}:
                    active.append(index)
                approved_or_completed |= status in {"APPROVED", "COMPLETED"}
                requested |= status == "REQUESTED"
                reused_rejected |= status == "REJECTED" and refund_id == request["refund_request_id"]
            if record["order_item_id"] != request["order_item_id"]:
                invalid.update((f"{base}/order_item_id", "/request/order_item_id"))
            if order is not None and record["order_item_id"] != order["order_item_id"]:
                invalid.update((f"{base}/order_item_id", "/order/order_item_id"))
            amount = record["amount"]
            if amount is None or amount <= 0 or (isinstance(paid, int) and paid > 0 and amount > paid):
                invalid.add(f"{base}/amount")
            if record["currency"] is None or record["currency"] != currency:
                invalid.add(f"{base}/currency")
        for indices in ids.values():
            if len(indices) > 1:
                invalid.update(f"/refund_history/{index}/refund_id" for index in indices)
        if len(active) > 1:
            # The conflict belongs to the ledger as a whole; changing either
            # one status in isolation is not a trustworthy remediation hint.
            invalid.add("/refund_history")
        if invalid:
            self._match("POL-50.10", invalid)
        if invalid_status:
            self._match("POL-50.03", invalid_status)
        if approved_or_completed:
            self._match("POL-50.01")
        if requested:
            self._match("POL-50.02")
        if reused_rejected:
            self._match("POL-50.11", {"/request/refund_request_id"})

    def _money_validation(self, facts: dict[str, Any]) -> None:
        order = facts["order"]
        if order is None:
            return
        request = facts["request"]
        request_currency = request["currency"]
        order_currency = order["currency"]
        currency_mismatch = (
            request_currency is not None
            and order_currency is not None
            and request_currency != order_currency
        )
        if currency_mismatch:
            paths = {"/request/currency", "/order/currency"}
            if request_currency == self.rules.supported_currency:
                paths.discard("/request/currency")
            if order_currency == self.rules.supported_currency:
                paths.discard("/order/currency")
            self._match("POL-50.09", paths)
        # The canonical MD defines an ordered currency state machine:
        # mismatch owns the condition, otherwise unsupported/null applies.
        if not currency_mismatch:
            unsupported: set[str] = set()
            if request_currency != self.rules.supported_currency:
                unsupported.add("/request/currency")
            if order_currency != self.rules.supported_currency:
                unsupported.add("/order/currency")
            if unsupported:
                self._match("POL-50.08", unsupported)
        paid = order["paid_item_amount"]
        requested = request["requested_amount"]
        invalid: set[str] = set()
        if paid is None or paid <= 0:
            invalid.add("/order/paid_item_amount")
        if requested is not None and requested <= 0:
            invalid.add("/request/requested_amount")
        if invalid:
            self._match("POL-50.04", invalid)
            return
        effective = paid if requested is None else requested
        if effective > paid:
            self._match("POL-50.05")
        elif effective < paid:
            self._match("POL-50.06")
        else:
            self._match("POL-50.07")

    def _evidence_validation(self, facts: dict[str, Any]) -> tuple[str | None, bool]:
        shipment = facts["shipment"]
        if shipment is None:
            return None, False
        evidence = shipment["evidence"]
        status = evidence["evidence_status"]
        issue = shipment["issue_code"]
        if status not in self.rules.evidence_statuses:
            self._match("POL-40.07", {"/shipment/evidence/evidence_status"})
            return None, False
        if issue is not None and issue not in self.rules.issue_codes:
            self._match("POL-40.05", {"/shipment/issue_code"})
            return None, False
        provenance = {
            "/shipment/evidence/verified_by": evidence["verified_by"],
            "/shipment/evidence/verified_at": evidence["verified_at"],
            "/shipment/evidence/evidence_source": evidence["evidence_source"],
        }
        provenance_paths = set(provenance)
        values = tuple(provenance.values())
        if status in {"NONE", "PENDING"}:
            issue_ok = issue is None if status == "NONE" else issue in self.rules.issue_codes
            combination_ok = issue_ok and all(value is None for value in values) and not evidence["provenance_attested"]
            if not combination_ok:
                invalid_paths: set[str] = set()
                if not issue_ok:
                    invalid_paths.add("/shipment/issue_code")
                invalid_paths.update(path for path, value in provenance.items() if value is not None)
                if evidence["provenance_attested"]:
                    invalid_paths.add("/shipment/evidence/provenance_attested")
                self._match(
                    "POL-40.04",
                    invalid_paths,
                )
                return None, False
            if status == "PENDING":
                self._match("POL-40.02", {"/shipment/evidence/evidence_status"})
            return status, True
        if issue not in self.rules.issue_codes:
            self._match("POL-40.04", {"/shipment/issue_code"})
            return None, False
        missing = {path for path, value in provenance.items() if value is None}
        if missing:
            self._match("POL-40.06", missing)
            return None, False
        if not evidence["provenance_attested"]:
            self._match("POL-40.08", {"/shipment/evidence/provenance_attested"})
            return None, False
        if status == "REJECTED":
            self._match("POL-40.03")
        return status, True

    @staticmethod
    def _parse_evaluation_date(value: Any) -> date | None:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        if not isinstance(value, str) or not RFC3339.fullmatch(value):
            return None
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _policy_timezone(name: str) -> ZoneInfo | timezone:
        """Load the policy timezone without requiring the optional tzdata wheel.

        Windows Python installations may not ship an IANA timezone database.
        The policy contract fixes the timezone to Asia/Seoul, whose current and
        historical project dates use the constant UTC+09:00 offset.
        """

        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError:
            if name == "Asia/Seoul":
                return timezone(timedelta(hours=9), name)
            raise

    def _domain_and_date_validation(
        self, facts: dict[str, Any], evidence_status: str | None, evidence_valid: bool
    ) -> tuple[bool, bool, bool, int | None]:
        order = facts["order"]
        customer = facts["customer_snapshot"]
        product = facts["product"]
        shipment = facts["shipment"]
        tier_valid = False
        category_valid = False
        product_flags_valid = False
        selected_limit: int | None = None
        if customer is not None:
            tier = customer["customer_tier_at_order"]
            if tier in self.rules.customer_tiers:
                tier_valid = True
                selected_limit = int(self.rules.customer_tiers[tier]["max_elapsed_days"])
                self._match("POL-20.01" if tier == "STANDARD" else "POL-20.02")
            else:
                self._match("POL-20.03", {"/customer_snapshot/customer_tier_at_order"})
        if product is not None:
            category_valid = product["category"] in self.rules.product_categories
            if not category_valid:
                self._match("POL-30.03", {"/product/category"})
            final_sale_valid = product["final_sale"] is not None
            if not final_sale_valid:
                self._match("POL-30.05", {"/product/final_sale"})
            package_valid = True
            if shipment is not None and product["category"] == "ELECTRONICS":
                package_valid = shipment["package_opened"] is not None
                if not package_valid:
                    self._match("POL-30.04", {"/shipment/package_opened"})
            product_flags_valid = category_valid and final_sale_valid and package_valid

        evaluation_date = self._parse_evaluation_date(facts["trusted_context"]["evaluation_date"])
        parsed: dict[str, datetime] = {}
        invalid_date_paths: set[str] = set()
        date_values: list[tuple[str, Any]] = []
        if evaluation_date is None:
            invalid_date_paths.add("/trusted_context/evaluation_date")
        if facts["trusted_context"]["timezone"] != self.rules.timezone:
            invalid_date_paths.add("/trusted_context/timezone")
        if order is not None:
            date_values.append(("/order/ordered_at", order["ordered_at"]))
        if customer is not None:
            date_values.append(("/customer_snapshot/snapshotted_at", customer["snapshotted_at"]))
        if product is not None:
            date_values.append(("/product/snapshotted_at", product["snapshotted_at"]))
        if shipment is not None and shipment["delivered_at"] is not None:
            date_values.append(("/shipment/delivered_at", shipment["delivered_at"]))
        if shipment is not None and evidence_status in {"VERIFIED", "REJECTED"}:
            date_values.append(("/shipment/evidence/verified_at", shipment["evidence"]["verified_at"]))
        for path, value in date_values:
            result = self._parse_timestamp(value)
            if result is None:
                invalid_date_paths.add(path)
            else:
                parsed[path] = result
        if invalid_date_paths:
            self._match("POL-20.05", invalid_date_paths)

        invalid_order_paths: set[str] = set()
        if evaluation_date is not None:
            seoul = self._policy_timezone(self.rules.timezone)
            cutoff = datetime.combine(evaluation_date + timedelta(days=1), time.min, seoul).astimezone(timezone.utc)
            for path, value in parsed.items():
                if value >= cutoff:
                    invalid_order_paths.add(path)
        ordered = parsed.get("/order/ordered_at")
        customer_at = parsed.get("/customer_snapshot/snapshotted_at")
        product_at = parsed.get("/product/snapshotted_at")
        delivered = parsed.get("/shipment/delivered_at")
        verified_at = parsed.get("/shipment/evidence/verified_at")
        if ordered is not None and customer_at is not None and customer_at != ordered:
            invalid_order_paths.update(("/order/ordered_at", "/customer_snapshot/snapshotted_at"))
        if ordered is not None and product_at is not None and product_at != ordered:
            invalid_order_paths.update(("/order/ordered_at", "/product/snapshotted_at"))
        if ordered is not None and delivered is not None and delivered < ordered:
            invalid_order_paths.update(("/order/ordered_at", "/shipment/delivered_at"))
        if verified_at is not None:
            lower_bound = delivered if delivered is not None else ordered
            if lower_bound is not None and verified_at < lower_bound:
                invalid_order_paths.update(("/shipment/evidence/verified_at", "/shipment/delivered_at" if delivered is not None else "/order/ordered_at"))
        if invalid_order_paths:
            self._match("POL-20.04", invalid_order_paths)

        verified_fault = evidence_valid and evidence_status == "VERIFIED"
        if verified_fault:
            self._match("POL-40.01")
        if order is not None and order["order_status"] == "DELIVERED" and shipment is not None and shipment["delivered_at"] is None and not verified_fault:
            self._match("POL-10.13", {"/shipment/delivered_at"})

        dates_valid = not invalid_date_paths and not invalid_order_paths
        elapsed_days: int | None = None
        if dates_valid and evaluation_date is not None and delivered is not None:
            elapsed_days = (
                evaluation_date
                - delivered.astimezone(self._policy_timezone(self.rules.timezone)).date()
            ).days
            if tier_valid and selected_limit is not None and elapsed_days > selected_limit:
                self._match("POL-20.06")
        if product is not None and shipment is not None and product_flags_valid:
            if product["final_sale"] is True:
                self._match("POL-30.01")
            if product["category"] == "ELECTRONICS" and shipment["package_opened"] is True:
                self._match("POL-30.02")
        return verified_fault, tier_valid, product_flags_valid, elapsed_days

    def evaluate(self, raw_facts: Mapping[str, Any]) -> PolicyDecisionResult:
        facts = self._normalize_input(raw_facts)
        self._matched = set()
        self._fields = {}
        self._lookup_validation(facts)
        self._order_validation(facts)
        self._refund_history_validation(facts)
        self._money_validation(facts)
        evidence_status, evidence_valid = self._evidence_validation(facts)
        self._domain_and_date_validation(facts, evidence_status, evidence_valid)

        terminal_matches = {
            clause_id for clause_id in self._matched if self.rules.clause(clause_id).terminal
        }
        if not terminal_matches:
            self._match("POL-00.08")
        primary = self.rules.primary(self._matched)
        if primary.result is None:
            raise RuntimeError("primary clause is missing a result tuple")
        overridden = (
            sorted(self._matched & self.rules.override_targets)
            if primary.id == "POL-40.01"
            else []
        )
        required_fields: list[str] = []
        if primary.result["next_action"] == "REQUEST_INFO":
            fields: set[str] = set()
            for clause_id in self._matched:
                clause = self.rules.clause(clause_id)
                if clause.terminal and clause.result and clause.result["next_action"] == "REQUEST_INFO":
                    fields.update(self._fields.get(clause_id, set()))
            required_fields = sorted(fields)
        value: dict[str, Any] = {
            **dict(primary.result),
            "reason_code": primary.reason_code,
            "primary_clause": primary.id,
            "matched_clauses": sorted(self._matched),
            "overridden_clauses": overridden,
            "required_fields": required_fields,
            "facts": facts,
            "facts_hash": hashlib.sha256(self._canonical_bytes(facts)).hexdigest(),
            "versions": dict(self.rules.versions),
        }
        return PolicyDecisionResult(value)

    def rationale(self, result: PolicyDecisionResult) -> str:
        primary: Clause = self.rules.clause(result.value["primary_clause"])
        if result.value["required_fields"]:
            return f"{primary.summary}. 확인 필요: {', '.join(result.value['required_fields'])}"
        if result.value["overridden_clauses"]:
            return f"{primary.summary}. 해제된 제한: {', '.join(result.value['overridden_clauses'])}"
        return primary.summary

