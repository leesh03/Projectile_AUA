"""Adapters between the Core dataclass state and scaffold dict functions.

Chae-rin's scaffolds intentionally expose small ``repair_once`` and
``verify_once`` functions over a dict state. The Core keeps orchestration,
retry/reflection limits, and contract traces in :mod:`nodes.graph`; these
adapters only translate one call at a time.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from agents.policy_agent.nodes.sql_generator import SQLQuery
from agents.policy_agent.nodes.state import (
    AgentConfig,
    NodeRole,
    PolicyAgentState,
    ProviderResult,
    ProviderUsage,
)

DictScaffoldCall = Callable[[dict[str, Any], Any], Mapping[str, Any]]


def agent_config_from_scaffold(
    scaffold_config: Mapping[str, Any],
    *,
    max_queries: int = 5,
    repair_safety_violations: bool = False,
) -> AgentConfig:
    """Translate Chae-rin's config keys without silently dropping loop controls."""

    unsupported_budgets = {
        key: scaffold_config.get(key)
        for key in ("max_total_tokens", "max_total_latency_ms")
        if scaffold_config.get(key) is not None
    }
    if unsupported_budgets:
        raise ValueError(
            "Core has no enforcement boundary for these scaffold budgets yet: "
            f"{sorted(unsupported_budgets)}"
        )

    max_total_steps = scaffold_config.get("max_total_steps")
    return AgentConfig(
        enable_repair=bool(scaffold_config.get("use_sql_repair", False)),
        max_retries=int(scaffold_config.get("max_sql_retries", 0)),
        repair_safety_violations=repair_safety_violations,
        stop_on_repeated_error=bool(
            scaffold_config.get("stop_on_repeated_error", True)
        ),
        max_total_steps=(
            None if max_total_steps is None else int(max_total_steps)
        ),
        enable_verifier=bool(
            scaffold_config.get("use_reasoning_verifier", False)
        ),
        max_reflections=int(scaffold_config.get("max_reflections", 0)),
        max_queries=max_queries,
    )


def _schema_context(state: PolicyAgentState) -> str:
    schema = state.context.get("database_schema", {})
    if isinstance(schema, str):
        return schema
    return json.dumps(schema, ensure_ascii=False, sort_keys=True, default=str)


def _record_scaffold_usage(
    state: PolicyAgentState,
    *,
    node_role: NodeRole,
    scaffold_state: Mapping[str, Any],
    output: Mapping[str, Any] | str,
    llm: Any,
) -> None:
    """Copy trusted token metadata emitted by one injected scaffold call."""

    trace = scaffold_state.get("trace")
    if not isinstance(trace, list) or not trace or not isinstance(trace[-1], Mapping):
        return
    last_step = trace[-1]
    raw_input = last_step.get("input_tokens", 0)
    raw_output = last_step.get("output_tokens", 0)
    input_tokens = raw_input if isinstance(raw_input, int) and raw_input >= 0 else 0
    output_tokens = raw_output if isinstance(raw_output, int) and raw_output >= 0 else 0
    last_result = getattr(llm, "last_result", None)
    finish_reason = getattr(last_result, "finish_reason", None)
    if finish_reason is None:
        finish_reason = getattr(last_result, "status", None)
    state.record_provider_result(
        node_role,
        ProviderResult(
            output=output,
            usage=ProviderUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
            provider=getattr(llm, "provider", None),
            model_id=getattr(llm, "model_id", None),
            finish_reason=finish_reason,
            latency_ms=getattr(last_result, "latency_ms", None),
            provider_request_id=getattr(last_result, "response_id", None),
        ),
    )


class SQLRepairAdapter:
    """Adapt ``repair_once(dict_state, llm)`` to the Core SQLRepair protocol."""

    def __init__(self, repair_once: DictScaffoldCall, llm: Any) -> None:
        self.repair_once = repair_once
        self.llm = llm

    def __call__(
        self,
        state: PolicyAgentState,
        query: SQLQuery,
        error: Exception,
    ) -> SQLQuery:
        scaffold_state: dict[str, Any] = {
            "testcase_id": state.testcase_id,
            "agent_label": state.agent_label,
            "run_id": state.run_id,
            "trial": state.trial,
            "request_id": state.testcase_id,
            "user_query": state.question,
            "schema_context": _schema_context(state),
            "policy_context": state.context.get("policy_text", ""),
            "sql": query.sql,
            "sql_history": list(state.sql_history),
            "sql_result": state.query_results.get(query.name, []),
            "sql_success": False,
            "sql_error_type": getattr(error, "code", type(error).__name__),
            "sql_error_message": str(error),
            "sql_retry_count": max(0, state.retry_count - 1),
            "stop_reason": None,
            "total_step_count": 0,
            "trace": [],
        }
        result = self.repair_once(scaffold_state, self.llm)
        if not isinstance(result, Mapping):
            raise TypeError("repair_once must return the scaffold state mapping")
        repaired_sql = result.get("sql")
        if not isinstance(repaired_sql, str) or not repaired_sql.strip():
            raise ValueError("repair_once returned an empty SQL statement")
        raw_history = result.get("sql_history", [])
        if isinstance(raw_history, list) and all(
            isinstance(item, str) for item in raw_history
        ):
            state.sql_history[:] = raw_history
        _record_scaffold_usage(
            state,
            node_role="REPAIR_QUERY",
            scaffold_state=result,
            output=repaired_sql,
            llm=self.llm,
        )
        return SQLQuery(
            name=query.name,
            sql=repaired_sql.strip(),
            parameters=query.parameters,
        )


class ReasoningVerifierAdapter:
    """Adapt ``verify_once(dict_state, llm)`` to one Core verifier call."""

    def __init__(self, verify_once: DictScaffoldCall, llm: Any) -> None:
        self.verify_once = verify_once
        self.llm = llm

    def __call__(self, state: PolicyAgentState) -> Mapping[str, Any]:
        scaffold_state: dict[str, Any] = {
            "testcase_id": state.testcase_id,
            "agent_label": state.agent_label,
            "run_id": state.run_id,
            "trial": state.trial,
            "request_id": state.testcase_id,
            "user_query": state.question,
            "schema_context": _schema_context(state),
            "policy_context": state.context.get("policy_text", ""),
            "policy_decision": state.decision or "",
            "applied_policy_clauses": list(state.policy_clauses),
            "policy_reason": state.rationale or "",
            "policy_facts": state.facts,
            "verifier_status": state.verifier_status or "",
            "verifier_issues": list(state.verifier_issues),
            "reflection_count": state.reflection_count,
            "stop_reason": None,
            "total_step_count": 0,
            "trace": [],
        }
        result = self.verify_once(scaffold_state, self.llm)
        if not isinstance(result, Mapping):
            raise TypeError("verify_once must return the scaffold state mapping")
        _record_scaffold_usage(
            state,
            node_role="VERIFY_REASONING",
            scaffold_state=result,
            output=result,
            llm=self.llm,
        )
        return result
