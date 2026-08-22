"""Trusted fact overlays for cases the compact shop database cannot encode."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from agents.policy_agent.nodes.state import PolicyAgentState


class FixtureFactsError(ValueError):
    pass


class FixtureFactsAdapter:
    """Return a sanitized PolicyFacts fixture by testcase ID.

    The fixture file contains facts only.  Expected decisions, Gold clauses,
    and evaluator fields are deliberately rejected at this boundary.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FixtureFactsError(f"cannot load facts fixtures: {exc}") from exc
        if not isinstance(raw, dict) or raw.get("schema") != "policy-facts-fixtures-v1":
            raise FixtureFactsError("fixture schema must be policy-facts-fixtures-v1")
        cases = raw.get("cases")
        if not isinstance(cases, dict):
            raise FixtureFactsError("fixture cases must be an object")
        forbidden = {"expected_result", "gold_decision", "gold_clauses", "required_fields"}
        for testcase_id, facts in cases.items():
            if not isinstance(testcase_id, str) or not isinstance(facts, dict):
                raise FixtureFactsError("each fixture must map an ID to PolicyFacts")
            if forbidden & facts.keys():
                raise FixtureFactsError(f"Gold field leaked into fixture {testcase_id}")
        self._cases: dict[str, dict[str, Any]] = cases

    def __call__(self, state: PolicyAgentState) -> dict[str, Any] | None:
        facts = self._cases.get(state.testcase_id)
        return None if facts is None else copy.deepcopy(facts)

    @property
    def testcase_ids(self) -> frozenset[str]:
        return frozenset(self._cases)
