from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from agents.policy_agent.nodes.policy_reasoner import PolicyReasoner
from agents.policy_agent.nodes.sql_generator import SQLGenerationError, SQLGenerator
from agents.policy_agent.nodes.state import (
    AgentRequest,
    PolicyAgentState,
    ProviderResult,
    ProviderUsage,
)

ROOT = Path(__file__).resolve().parents[2]


def _state() -> PolicyAgentState:
    cases = json.loads((ROOT / "data" / "agent_cases.json").read_text(encoding="utf-8"))
    request = AgentRequest.from_mapping(cases[0])
    state = PolicyAgentState(request)
    state.context = {
        "database_schema": {"orders": [{"name": "order_id"}]},
        "allowed_tables": ["orders"],
        "policy_text": "POL-TEST",
    }
    state.facts = {"order": {"order_id": "O-1"}}
    return state


class _ScriptedModel:
    def __init__(self, outputs: list[Mapping[str, Any] | str]) -> None:
        self.outputs = outputs
        self.payloads: list[dict[str, Any]] = []

    def _next(self, payload: Mapping[str, Any]) -> ProviderResult:
        self.payloads.append(dict(payload))
        output = self.outputs[min(len(self.payloads) - 1, len(self.outputs) - 1)]
        return ProviderResult(
            output=output,
            usage=ProviderUsage(input_tokens=3, output_tokens=2),
            provider="scripted",
            model_id="contract-test",
            latency_ms=1,
        )

    def generate_sql(self, payload: Mapping[str, Any]) -> ProviderResult:
        return self._next(payload)

    def reason(self, payload: Mapping[str, Any]) -> ProviderResult:
        return self._next(payload)


def test_sql_schema_error_is_corrected_once() -> None:
    model = _ScriptedModel(
        [
            {"parameters": []},
            {
                "queries": [
                    {
                        "name": "order",
                        "sql": "SELECT order_id FROM orders WHERE order_id = ?",
                        "parameters": ["O-1"],
                    }
                ]
            },
        ]
    )
    state = _state()

    plan = SQLGenerator(model, max_schema_retries=1).generate(state)

    assert plan.queries[0].name == "order"
    assert len(model.payloads) == 2
    assert model.payloads[1]["schema_correction"]["attempt"] == 1
    assert state.llm_call_count == 2
    assert state.structured_output_retry_count == 1
    assert len(state.provider_calls) == 2
    assert state.traces[0].error_type == "SCHEMA_RETRY"


def test_policy_schema_error_is_corrected_once() -> None:
    model = _ScriptedModel(
        [
            {"decision": "MAYBE"},
            {
                "decision": "APPROVE",
                "clauses": ["POL-TEST"],
                "rationale": "The trusted facts satisfy the supplied policy.",
                "confidence": 0.8,
            },
        ]
    )
    state = _state()

    decision = PolicyReasoner(model, max_schema_retries=1).evaluate(state)

    assert decision.decision == "APPROVE"
    assert len(model.payloads) == 2
    assert model.payloads[1]["schema_correction"]["attempt"] == 1
    assert state.llm_call_count == 2
    assert state.structured_output_retry_count == 1
    assert len(state.provider_calls) == 2


def test_schema_retry_is_bounded() -> None:
    model = _ScriptedModel([{"parameters": []}])
    state = _state()

    with pytest.raises(SQLGenerationError, match="queries"):
        SQLGenerator(model, max_schema_retries=1).generate(state)

    assert len(model.payloads) == 2
    assert state.structured_output_retry_count == 1
