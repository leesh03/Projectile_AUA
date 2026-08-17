"""Assemble PolicyFacts and enforce structural/policy evidence contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from agents.policy_agent.nodes.sql_generator import QUERY_REGISTRY
from agents.policy_agent.nodes.state import PolicyAgentState

BOOLEAN_LEAF_NAMES = frozenset(
    {"final_sale", "package_opened", "provenance_attested", "attested"}
)


class EvidenceAssemblyError(RuntimeError):
    """Raised when flat SQL output cannot safely become nested facts."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class EvidenceResult:
    sufficient: bool
    missing_paths: tuple[str, ...] = ()
    ambiguous_sections: tuple[str, ...] = ()
    mismatched_paths: tuple[str, ...] = ()
    reason: str | None = None


class EvidenceChecker:
    """Convert named SQL results into canonical nested PolicyFacts.

    Stage 1 checks structure, cardinality, identifiers, and caller-supplied
    baseline paths. Stage 2 checks paths required by the policy clauses selected
    by the reasoner. Gold ``required_fields`` are never used.
    """

    @staticmethod
    def _coerce_leaf(name: str, value: Any) -> Any:
        if name not in BOOLEAN_LEAF_NAMES or value is None:
            return value
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        raise EvidenceAssemblyError(
            "INVALID_BOOLEAN_VALUE",
            f"boolean result column '{name}' must be 0, 1, true, false, or null",
        )

    @classmethod
    def _unflatten_row(cls, row: Mapping[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for raw_key, raw_value in row.items():
            key = str(raw_key)
            parts = key.split("__")
            if not key or any(not part for part in parts):
                raise EvidenceAssemblyError(
                    "INVALID_NESTED_ALIAS",
                    f"nested result alias contains an empty path segment: {key!r}",
                )
            cursor = result
            for part in parts[:-1]:
                existing = cursor.get(part)
                if existing is None:
                    nested: dict[str, Any] = {}
                    cursor[part] = nested
                    cursor = nested
                elif isinstance(existing, dict):
                    cursor = existing
                else:
                    raise EvidenceAssemblyError(
                        "NESTED_ALIAS_COLLISION",
                        f"scalar/object collision in result alias: {key}",
                    )
            leaf = parts[-1]
            if leaf in cursor:
                raise EvidenceAssemblyError(
                    "NESTED_ALIAS_COLLISION",
                    f"duplicate or scalar/object collision in result alias: {key}",
                )
            cursor[leaf] = cls._coerce_leaf(leaf, raw_value)
        return result

    @staticmethod
    def _expected_identifiers(state: PolicyAgentState) -> dict[str, Any]:
        expected = dict(state.agent_request.target_ids)
        expected["order_item_id"] = state.agent_request.request.get("order_item_id")
        return expected

    def assemble_facts(
        self, state: PolicyAgentState
    ) -> tuple[dict[str, Any], tuple[str, ...], tuple[str, ...]]:
        request = state.agent_request
        facts: dict[str, Any] = {
            "trusted_context": dict(request.trusted_context),
            "request": dict(request.request),
            "target_ids": dict(request.target_ids),
            "lookup_counts": {},
        }
        ambiguous: list[str] = []
        mismatched: list[str] = []
        expected_ids = self._expected_identifiers(state)

        for section, rows in state.query_results.items():
            spec = QUERY_REGISTRY.get(section)
            if spec is None:
                raise EvidenceAssemblyError(
                    "UNKNOWN_QUERY_SECTION", f"query result has unknown section: {section}"
                )
            normalized = [self._unflatten_row(row) for row in rows]
            if spec.count_key is not None:
                facts["lookup_counts"][spec.count_key] = len(normalized)

            for index, row in enumerate(normalized):
                for field_name in spec.identity_fields:
                    prefix = f"/{section}/{index}" if spec.cardinality == "many" else f"/{section}"
                    path = f"{prefix}/{field_name}"
                    if field_name not in row:
                        mismatched.append(path)
                        continue
                    expected = expected_ids.get(field_name)
                    if expected is not None and row[field_name] != expected:
                        mismatched.append(path)

            if spec.cardinality == "one":
                if len(normalized) == 0:
                    facts[section] = None
                elif len(normalized) == 1:
                    facts[section] = normalized[0]
                else:
                    facts[section] = None
                    ambiguous.append(section)
            else:
                facts[section] = normalized

        for section, spec in QUERY_REGISTRY.items():
            facts.setdefault(section, [] if spec.cardinality == "many" else None)
            if spec.count_key is not None:
                facts["lookup_counts"].setdefault(spec.count_key, 0)
        return facts, tuple(sorted(ambiguous)), tuple(sorted(set(mismatched)))

    @staticmethod
    def _decode_pointer_token(token: str) -> str:
        return token.replace("~1", "/").replace("~0", "~")

    @classmethod
    def resolve_pointer(cls, document: Any, pointer: str) -> tuple[bool, Any]:
        if pointer == "":
            return True, document
        if not pointer.startswith("/"):
            raise ValueError(f"invalid JSON Pointer: {pointer}")
        current = document
        for raw_token in pointer[1:].split("/"):
            token = cls._decode_pointer_token(raw_token)
            if isinstance(current, Mapping):
                if token not in current:
                    return False, None
                current = current[token]
            elif isinstance(current, Sequence) and not isinstance(
                current, (str, bytes, bytearray)
            ):
                try:
                    index = int(token)
                except ValueError:
                    return False, None
                if not 0 <= index < len(current):
                    return False, None
                current = current[index]
            else:
                return False, None
        return current is not None and current != "", current

    def evaluate(self, state: PolicyAgentState) -> EvidenceResult:
        """Run the pre-reasoning structural evidence check."""

        facts, ambiguous, mismatched = self.assemble_facts(state)
        state.facts = facts
        missing = tuple(
            path
            for path in state.required_evidence_paths
            if not self.resolve_pointer(facts, path)[0]
        )
        state.missing_evidence = list(missing)
        if ambiguous:
            return EvidenceResult(
                sufficient=False,
                missing_paths=missing,
                ambiguous_sections=ambiguous,
                mismatched_paths=mismatched,
                reason="AMBIGUOUS_RESULT",
            )
        if mismatched:
            state.missing_evidence = list(mismatched)
            return EvidenceResult(
                sufficient=False,
                mismatched_paths=mismatched,
                reason="IDENTITY_MISMATCH",
            )
        if missing:
            return EvidenceResult(
                sufficient=False,
                missing_paths=missing,
                reason="MISSING_REQUIRED_FIELDS",
            )
        return EvidenceResult(sufficient=True)

    def evaluate_policy_requirements(self, state: PolicyAgentState) -> EvidenceResult:
        """Check Agent-visible evidence contracts for selected policy clauses."""

        raw_contracts = state.context.get("policy_evidence_contracts", {})
        if not isinstance(raw_contracts, Mapping):
            raise EvidenceAssemblyError(
                "INVALID_POLICY_EVIDENCE_CONTRACT",
                "policy_evidence_contracts must be an object",
            )
        required: list[str] = []
        for clause in state.policy_clauses:
            raw_paths = raw_contracts.get(clause, [])
            if not isinstance(raw_paths, (list, tuple)):
                raise EvidenceAssemblyError(
                    "INVALID_POLICY_EVIDENCE_CONTRACT",
                    f"required paths for {clause} must be an array",
                )
            for path in raw_paths:
                if not isinstance(path, str) or not path.startswith("/"):
                    raise EvidenceAssemblyError(
                        "INVALID_POLICY_EVIDENCE_CONTRACT",
                        f"required path for {clause} must be a JSON Pointer",
                    )
                if path not in required:
                    required.append(path)

        missing = tuple(path for path in required if not self.resolve_pointer(state.facts, path)[0])
        state.missing_evidence = list(missing)
        if missing:
            return EvidenceResult(
                sufficient=False,
                missing_paths=missing,
                reason="MISSING_POLICY_EVIDENCE",
            )
        return EvidenceResult(sufficient=True)

    def __call__(self, state: PolicyAgentState) -> EvidenceResult:
        return self.evaluate(state)
