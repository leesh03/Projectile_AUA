"""Validated loader for the policy rule set generated from the canonical MD."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


class PolicyRuleError(ValueError):
    """Raised when machine-readable policy metadata is incomplete or ambiguous."""


@dataclass(frozen=True, slots=True)
class Clause:
    id: str
    priority: int
    reason_code: str
    terminal: bool
    result: Mapping[str, str] | None
    required_paths: tuple[str, ...]
    summary: str


@dataclass(frozen=True, slots=True)
class PolicyRuleSet:
    policy_version: str
    timezone: str
    supported_currency: str
    customer_tiers: Mapping[str, Mapping[str, int]]
    product_categories: frozenset[str]
    issue_codes: tuple[str, ...]
    evidence_statuses: frozenset[str]
    order_statuses: frozenset[str]
    refund_statuses: frozenset[str]
    override_targets: frozenset[str]
    versions: Mapping[str, str]
    clauses: Mapping[str, Clause]
    source_md: str

    @classmethod
    def load(cls, path: str | Path) -> "PolicyRuleSet":
        policy_path = Path(path)
        try:
            raw = json.loads(policy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PolicyRuleError(f"cannot load policy rule set: {exc}") from exc
        if not isinstance(raw, dict) or raw.get("schema") != "policy-rule-set-v1":
            raise PolicyRuleError("policy schema must be policy-rule-set-v1")

        raw_clauses = raw.get("clauses")
        if not isinstance(raw_clauses, list):
            raise PolicyRuleError("clauses must be an array")
        clauses: dict[str, Clause] = {}
        priorities: set[int] = set()
        for item in raw_clauses:
            if not isinstance(item, dict):
                raise PolicyRuleError("every clause must be an object")
            clause_id = item.get("id")
            priority = item.get("priority")
            reason_code = item.get("reason_code")
            terminal = item.get("terminal")
            result = item.get("result")
            required_paths = item.get("required_paths", [])
            summary = item.get("summary")
            if not isinstance(clause_id, str) or not clause_id.startswith("POL-"):
                raise PolicyRuleError("clause id is invalid")
            if clause_id in clauses:
                raise PolicyRuleError(f"duplicate clause: {clause_id}")
            if not isinstance(priority, int) or priority <= 0 or priority in priorities:
                raise PolicyRuleError(f"invalid or duplicate priority for {clause_id}")
            if not isinstance(reason_code, str) or not reason_code:
                raise PolicyRuleError(f"reason_code is required for {clause_id}")
            if not isinstance(terminal, bool):
                raise PolicyRuleError(f"terminal must be boolean for {clause_id}")
            if terminal:
                if not isinstance(result, dict) or set(result) != {
                    "eligibility", "case_status", "next_action"
                }:
                    raise PolicyRuleError(f"terminal clause needs an exact result tuple: {clause_id}")
                normalized_result: Mapping[str, str] | None = MappingProxyType(
                    {key: str(value) for key, value in result.items()}
                )
            elif result is not None:
                raise PolicyRuleError(f"nonterminal clause cannot have a result: {clause_id}")
            else:
                normalized_result = None
            if not isinstance(required_paths, list) or not all(
                isinstance(value, str) and value.startswith("/") for value in required_paths
            ):
                raise PolicyRuleError(f"required_paths must be JSON Pointers: {clause_id}")
            if not isinstance(summary, str) or not summary.strip():
                raise PolicyRuleError(f"summary is required for {clause_id}")
            clauses[clause_id] = Clause(
                id=clause_id,
                priority=priority,
                reason_code=reason_code,
                terminal=terminal,
                result=normalized_result,
                required_paths=tuple(dict.fromkeys(required_paths)),
                summary=summary.strip(),
            )
            priorities.add(priority)

        if len(clauses) != 47:
            raise PolicyRuleError(f"policy-v0.5 requires 47 clauses, found {len(clauses)}")
        overrides = frozenset(str(value) for value in raw.get("override_targets", []))
        if not overrides <= clauses.keys():
            raise PolicyRuleError("override_targets contains an unknown clause")
        tiers = raw.get("customer_tiers")
        versions = raw.get("versions")
        if not isinstance(tiers, dict) or set(tiers) != {"STANDARD", "PREMIUM"}:
            raise PolicyRuleError("customer_tiers must define STANDARD and PREMIUM")
        if not isinstance(versions, dict) or not versions:
            raise PolicyRuleError("versions must be a non-empty object")
        return cls(
            policy_version=str(raw.get("policy_version")),
            timezone=str(raw.get("timezone")),
            supported_currency=str(raw.get("supported_currency")),
            customer_tiers=MappingProxyType(tiers),
            product_categories=frozenset(str(value) for value in raw.get("product_categories", [])),
            issue_codes=tuple(str(value) for value in raw.get("issue_codes", [])),
            evidence_statuses=frozenset(str(value) for value in raw.get("evidence_statuses", [])),
            order_statuses=frozenset(str(value) for value in raw.get("order_statuses", [])),
            refund_statuses=frozenset(str(value) for value in raw.get("refund_statuses", [])),
            override_targets=overrides,
            versions=MappingProxyType({str(k): str(v) for k, v in versions.items()}),
            clauses=MappingProxyType(clauses),
            source_md=str(raw.get("source_md", "")),
        )

    def primary(self, matched: set[str]) -> Clause:
        terminals = [self.clauses[value] for value in matched if self.clauses[value].terminal]
        if not terminals:
            raise PolicyRuleError("no terminal clause matched")
        return min(terminals, key=lambda clause: clause.priority)

    def clause(self, clause_id: str) -> Clause:
        try:
            return self.clauses[clause_id]
        except KeyError as exc:
            raise PolicyRuleError(f"unknown clause: {clause_id}") from exc
