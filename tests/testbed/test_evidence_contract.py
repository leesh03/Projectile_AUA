from __future__ import annotations

import json
from pathlib import Path

from agents.policy_agent.nodes.evidence_check import EvidenceChecker
from agents.policy_agent.nodes.sql_generator import QUERY_REGISTRY
from agents.policy_agent.nodes.state import AgentConfig, AgentRequest, PolicyAgentState

ROOT = Path(__file__).resolve().parents[2]


def _state() -> PolicyAgentState:
    case = json.loads((ROOT / "data" / "agent_cases.json").read_text(encoding="utf-8"))[0]
    return PolicyAgentState(
        AgentRequest.from_mapping(case),
        config=AgentConfig(require_all_query_sections=True),
    )


def test_omitted_query_is_not_confused_with_an_empty_database_result() -> None:
    state = _state()
    for section in QUERY_REGISTRY:
        if section != "shipment":
            state.query_results[section] = []

    result = EvidenceChecker().evaluate(state)

    assert result.sufficient is False
    assert result.reason == "OMITTED_QUERY_SECTIONS"
    assert state.facts["query_status"]["shipment"] == "OMITTED"
    assert state.facts["query_status"]["order"] == "EXECUTED"


def test_executed_query_with_no_row_is_not_marked_omitted() -> None:
    state = _state()
    state.query_results = {section: [] for section in QUERY_REGISTRY}

    result = EvidenceChecker().evaluate(state)

    assert result.sufficient is True
    assert set(state.facts["query_status"].values()) == {"EXECUTED"}


def test_truncated_query_is_incomplete_evidence() -> None:
    state = _state()
    state.query_results = {section: [] for section in QUERY_REGISTRY}
    state.truncated_queries.append("refund_history")
    state.rows_truncated = True

    result = EvidenceChecker().evaluate(state)

    assert result.sufficient is False
    assert result.reason == "RESULT_TRUNCATED"
    assert state.facts["query_status"]["refund_history"] == "TRUNCATED"

