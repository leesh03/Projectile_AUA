"""Shared request, state, trace, provider, and artifact adapters.

Public Auditor Pydantic schemas remain owned by ``core.schemas``. This module
only emits dictionaries that match those schemas and keeps Core-local runtime
metadata separate from the official contract.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from time import perf_counter_ns
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

if TYPE_CHECKING:
    from agents.policy_agent.nodes.sql_generator import SQLPlan

StopReason = Literal[
    "OK",
    "SQL_FAILURE",
    "MAX_RETRY",
    "MAX_REFLECTION",
    "INSUFFICIENT_EVIDENCE",
    "TOOL_SCHEMA_ERROR",
    "TIMEOUT",
    "PROVIDER_ERROR",
]

NodeRole = Literal[
    "CLASSIFY",
    "PLAN",
    "RETRIEVE_SCHEMA",
    "GENERATE_QUERY",
    "VALIDATE_QUERY",
    "EXECUTE_TOOL",
    "REPAIR_QUERY",
    "CHECK_EVIDENCE",
    "SELECT_POLICY",
    "DECIDE",
    "VERIFY_REASONING",
    "GENERATE_RESPONSE",
]

StepType = Literal["llm_call", "tool_call", "code"]
StepOutcome = Literal["ok", "fail", "skip"]

# Policy requirements differ by clause. Core performs only structural checks
# by default and accepts explicit JSON-Pointer requirements from Agent-visible
# policy metadata or a caller.
DEFAULT_REQUIRED_EVIDENCE_PATHS: tuple[str, ...] = ()
_SAFE_PATH_COMPONENT = re.compile(r"^[A-Za-z0-9_.-]+$")


def create_run_id() -> str:
    """Return a sortable, filesystem-safe run identifier."""

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}_{uuid4().hex[:8]}"


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    """Trusted usage copied from an API response, never from model text."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int | None = None
    cached_tokens: int | None = None
    reasoning_tokens: int | None = None

    def __post_init__(self) -> None:
        values = {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cached_tokens": self.cached_tokens,
            "reasoning_tokens": self.reasoning_tokens,
        }
        for name, value in values.items():
            if value is not None and (not isinstance(value, int) or value < 0):
                raise ValueError(f"{name} must be a non-negative integer or None")

    @property
    def counted_total(self) -> int:
        if self.total_tokens is not None:
            return self.total_tokens
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, int | None]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cached_tokens": self.cached_tokens,
            "reasoning_tokens": self.reasoning_tokens,
        }


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """Normalized return type implemented by a real model adapter.

    ``output`` contains business JSON only. Usage and provenance are supplied
    by the adapter from API response metadata. Plain mapping/string providers
    remain accepted for simple local tests, but contribute zero tokens.
    """

    output: Mapping[str, Any] | str
    usage: ProviderUsage = field(default_factory=ProviderUsage)
    provider: str | None = None
    model_id: str | None = None
    finish_reason: str | None = None
    latency_ms: int | None = None
    provider_request_id: str | None = None
    raw_output: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.output, (Mapping, str)):
            raise TypeError("ProviderResult.output must be a mapping or JSON string")
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError("latency_ms must be non-negative or None")


@dataclass(frozen=True, slots=True)
class ProviderCallRecord:
    node_role: NodeRole
    usage: ProviderUsage
    provider: str | None = None
    model_id: str | None = None
    finish_reason: str | None = None
    latency_ms: int | None = None
    provider_request_id: str | None = None

    @classmethod
    def from_result(cls, node_role: NodeRole, result: ProviderResult) -> ProviderCallRecord:
        return cls(
            node_role=node_role,
            usage=result.usage,
            provider=result.provider,
            model_id=result.model_id,
            finish_reason=result.finish_reason,
            latency_ms=result.latency_ms,
            provider_request_id=result.provider_request_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_role": self.node_role,
            "provider": self.provider,
            "model_id": self.model_id,
            "finish_reason": self.finish_reason,
            "latency_ms": self.latency_ms,
            "provider_request_id": self.provider_request_id,
            "usage": self.usage.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class AgentRequest:
    """Agent-visible input matching ``feat/dataset/policies/agent_cases.json``.

    ``question`` is untrusted natural language. ``request``, ``target_ids``, and
    ``trusted_context`` are structured evaluation inputs. Gold fields are
    intentionally absent and rejected by :meth:`from_mapping`.
    """

    testcase_id: str
    difficulty: str
    question: str
    request: dict[str, Any]
    target_ids: dict[str, Any]
    trusted_context: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.testcase_id.strip():
            raise ValueError("testcase_id must not be empty")
        if self.difficulty not in {"EASY", "MEDIUM", "HARD", "INTERACTIVE"}:
            raise ValueError("difficulty must be EASY, MEDIUM, HARD, or INTERACTIVE")
        if not self.question.strip():
            raise ValueError("question must not be empty")
        required_request_keys = {
            "currency",
            "order_item_id",
            "refund_request_id",
            "requested_amount",
        }
        required_target_keys = {
            "customer_id",
            "order_id",
            "order_item_id",
            "product_id",
            "shipment_id",
        }
        required_context_keys = {"evaluation_date", "timezone"}
        missing_request = required_request_keys - self.request.keys()
        missing_targets = required_target_keys - self.target_ids.keys()
        missing_context = required_context_keys - self.trusted_context.keys()
        if missing_request:
            raise ValueError(f"request is missing keys: {sorted(missing_request)}")
        if missing_targets:
            raise ValueError(f"target_ids is missing keys: {sorted(missing_targets)}")
        if missing_context:
            raise ValueError(f"trusted_context is missing keys: {sorted(missing_context)}")
        currency = self.request.get("currency")
        if currency is not None and (not isinstance(currency, str) or not currency.strip()):
            raise ValueError("request.currency must be a non-empty string or None")
        if self.trusted_context.get("timezone") != "Asia/Seoul":
            raise ValueError("trusted_context.timezone must be Asia/Seoul")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> AgentRequest:
        required = {
            "testcase_id",
            "difficulty",
            "question",
            "request",
            "target_ids",
            "trusted_context",
        }
        missing = required - value.keys()
        if missing:
            raise ValueError(f"agent case is missing keys: {sorted(missing)}")
        extra = value.keys() - required
        if extra:
            raise ValueError(f"agent case contains non-agent fields: {sorted(extra)}")
        mappings = ("request", "target_ids", "trusted_context")
        if any(not isinstance(value.get(key), Mapping) for key in mappings):
            raise TypeError("request, target_ids, and trusted_context must be objects")
        return cls(
            testcase_id=str(value["testcase_id"]),
            difficulty=str(value["difficulty"]).upper(),
            question=str(value["question"]),
            request=dict(value["request"]),
            target_ids=dict(value["target_ids"]),
            trusted_context=dict(value["trusted_context"]),
        )

    @classmethod
    def interactive(
        cls,
        question: str,
        *,
        order_item_id: str,
        evaluation_date: str | date | None = None,
        timezone_name: str = "Asia/Seoul",
        requested_amount: int | None = None,
        currency: str = "KRW",
    ) -> AgentRequest:
        if timezone_name != "Asia/Seoul":
            raise ValueError("interactive timezone_name must be Asia/Seoul")
        try:
            timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown interactive timezone: {timezone_name}") from exc
        if evaluation_date is None:
            normalized_date = datetime.now(timezone).date().isoformat()
        elif isinstance(evaluation_date, datetime):
            normalized_date = evaluation_date.date().isoformat()
        elif isinstance(evaluation_date, date):
            normalized_date = evaluation_date.isoformat()
        elif isinstance(evaluation_date, str) and evaluation_date.strip():
            normalized_date = evaluation_date.strip()
        else:
            raise TypeError("evaluation_date must be a non-empty string, date, or None")
        return cls(
            testcase_id="interactive",
            difficulty="INTERACTIVE",
            question=question,
            request={
                "currency": currency,
                "order_item_id": order_item_id,
                "refund_request_id": "interactive",
                "requested_amount": requested_amount,
            },
            target_ids={
                "customer_id": None,
                "order_id": None,
                "order_item_id": order_item_id,
                "product_id": None,
                "shipment_id": None,
            },
            trusted_context={
                "evaluation_date": normalized_date,
                "timezone": timezone_name,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "testcase_id": self.testcase_id,
            "difficulty": self.difficulty,
            "question": self.question,
            "request": dict(self.request),
            "target_ids": dict(self.target_ids),
            "trusted_context": dict(self.trusted_context),
        }


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """Core execution and optional scaffold switches."""

    enable_repair: bool = False
    max_retries: int = 0
    repair_safety_violations: bool = False
    stop_on_repeated_error: bool = True
    max_total_steps: int | None = None
    enable_verifier: bool = False
    max_reflections: int = 0
    max_queries: int = 5
    # The reusable Core may run policy-scoped subsets. The official Testbed
    # composition root enables the five-section contract explicitly.
    require_all_query_sections: bool = False

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.max_reflections < 0:
            raise ValueError("max_reflections must be non-negative")
        if self.max_total_steps is not None and self.max_total_steps <= 0:
            raise ValueError("max_total_steps must be positive or None")
        if not 1 <= self.max_queries <= 10:
            raise ValueError("max_queries must be between 1 and 10")

    def as_scaffold_config(self) -> dict[str, Any]:
        return {
            "planner_enabled": False,
            "repair_enabled": self.enable_repair,
            "max_retries": self.max_retries,
            "verifier_enabled": self.enable_verifier,
            "max_reflections": self.max_reflections,
            "reflection_policy": "initial_check_plus_reflections",
            # Legacy numeric keys remain for tolerant downstream consumers.
            "planner": False,
            "repair": self.max_retries if self.enable_repair else 0,
            "verifier": self.max_reflections if self.enable_verifier else 0,
        }

    def as_core_config(self) -> dict[str, Any]:
        return {
            "max_queries": self.max_queries,
            "repair_safety_violations": self.repair_safety_violations,
            "stop_on_repeated_error": self.stop_on_repeated_error,
            "max_total_steps": self.max_total_steps,
            "require_all_query_sections": self.require_all_query_sections,
        }


@dataclass(slots=True)
class TraceRecord:
    testcase_id: str
    agent_label: str
    trial: int
    step_index: int
    node_role: NodeRole
    type: StepType
    outcome: StepOutcome
    run_id: str | None = None
    tool_name: str | None = None
    arguments_valid: bool | None = None
    error_type: str | None = None
    iteration: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None

    def to_contract_dict(self) -> dict[str, Any]:
        return {
            "testcase_id": self.testcase_id,
            "agent_label": self.agent_label,
            "run_id": self.run_id,
            "trial": self.trial,
            "step_index": self.step_index,
            "node_role": self.node_role,
            "type": self.type,
            "outcome": self.outcome,
            "tool_name": self.tool_name,
            "arguments_valid": self.arguments_valid,
            "error_type": self.error_type,
            "iteration": self.iteration,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
        }


@dataclass(slots=True)
class PolicyAgentState:
    agent_request: AgentRequest
    agent_label: str = "V0"
    trial: int = 1
    run_id: str | None = None
    required_evidence_paths: tuple[str, ...] = DEFAULT_REQUIRED_EVIDENCE_PATHS
    config: AgentConfig = field(default_factory=AgentConfig)
    run_metadata: dict[str, Any] = field(default_factory=dict)

    context: dict[str, Any] = field(default_factory=dict)
    runtime_config: dict[str, Any] = field(default_factory=dict)
    query_plan: SQLPlan | None = None
    sql_history: list[str] = field(default_factory=list)
    query_results: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    facts: dict[str, Any] = field(default_factory=dict)
    rows_truncated: bool = False
    truncated_queries: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)

    decision: str | None = None
    policy_clauses: list[str] = field(default_factory=list)
    rationale: str | None = None
    confidence: float | None = None
    verifier_status: str | None = None
    verifier_issues: list[str] = field(default_factory=list)
    reflection_count: int = 0
    response: str | None = None

    task_success: bool = False
    stop_reason: StopReason | None = None
    error_type: str | None = None
    error_message: str | None = None
    tool_schema_valid: bool | None = None
    tool_error_count: int = 0
    retry_count: int = 0
    structured_output_retry_count: int = 0
    total_tokens: int = 0
    llm_call_count: int = 0
    safety_violation: bool = False
    latency_ms: int = 0

    traces: list[TraceRecord] = field(default_factory=list)
    provider_calls: list[ProviderCallRecord] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        repr=False,
    )
    _started_ns: int = field(default_factory=perf_counter_ns, repr=False)

    def __post_init__(self) -> None:
        if not self.agent_label.strip():
            raise ValueError("agent_label must not be empty")
        if not 1 <= self.trial <= 3:
            raise ValueError("trial must be between 1 and 3")
        if any(not path.startswith("/") for path in self.required_evidence_paths):
            raise ValueError("required evidence paths must use JSON Pointer syntax")
        if self.run_id is None:
            self.run_id = create_run_id()
        if not _SAFE_PATH_COMPONENT.fullmatch(self.run_id):
            raise ValueError("run_id contains unsafe path characters")

    @property
    def question(self) -> str:
        return self.agent_request.question

    @property
    def testcase_id(self) -> str:
        return self.agent_request.testcase_id

    def record_provider_result(self, node_role: NodeRole, result: ProviderResult) -> None:
        self.provider_calls.append(ProviderCallRecord.from_result(node_role, result))
        # Trial/Trace cost uses the portable prompt+completion definition.
        # Provider-specific totals may additionally include cached/reasoning
        # buckets and remain available in provider_calls for detailed audits.
        self.total_tokens += result.usage.input_tokens + result.usage.output_tokens

    def add_trace(
        self,
        *,
        node_role: NodeRole,
        step_type: StepType,
        outcome: StepOutcome,
        latency_ms: int,
        tool_name: str | None = None,
        arguments_valid: bool | None = None,
        error_type: str | None = None,
        iteration: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        self.traces.append(
            TraceRecord(
                testcase_id=self.testcase_id,
                agent_label=self.agent_label,
                run_id=self.run_id,
                trial=self.trial,
                step_index=len(self.traces),
                node_role=node_role,
                type=step_type,
                outcome=outcome,
                tool_name=tool_name,
                arguments_valid=arguments_valid,
                error_type=error_type,
                iteration=iteration,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=max(0, latency_ms),
            )
        )

    def finish(self, stop_reason: StopReason, *, success: bool) -> None:
        self.stop_reason = stop_reason
        self.task_success = success
        self.latency_ms = max(0, (perf_counter_ns() - self._started_ns) // 1_000_000)

    def fail(
        self,
        stop_reason: StopReason,
        *,
        error_type: str,
        message: str,
    ) -> None:
        self.error_type = error_type
        self.error_message = message
        self.finish(stop_reason, success=False)

    def trace_dicts(self) -> list[dict[str, Any]]:
        return [trace.to_contract_dict() for trace in self.traces]

    def trial_result_dict(
        self,
        *,
        policy_correct: bool,
        evaluation_basis: str = "PENDING",
        engine_consistency: bool | None = None,
        gold_agreement: bool | None = None,
    ) -> dict[str, Any]:
        """Return fields matching ``core.schemas.TrialResult`` exactly."""

        if not isinstance(policy_correct, bool):
            raise TypeError("policy_correct must be supplied by an independent evaluator")
        if self.stop_reason is None:
            raise RuntimeError("the run must finish before TrialResult is built")
        result = {
            "testcase_id": self.testcase_id,
            "agent_label": self.agent_label,
            "trial": self.trial,
            "task_success": self.task_success,
            "policy_correct": policy_correct,
            "tool_error_count": self.tool_error_count,
            "retry_count": self.retry_count,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "safety_violation": self.safety_violation,
            "stop_reason": self.stop_reason,
            "error_type": self.error_type,
            "tool_schema_valid": self.tool_schema_valid,
            "llm_call_count": self.llm_call_count,
            "scaffold_config": self.config.as_scaffold_config(),
            "difficulty": self.agent_request.difficulty,
        }
        if evaluation_basis != "PENDING" or engine_consistency is not None or gold_agreement is not None:
            result.update(
                {
                    "evaluation_basis": evaluation_basis,
                    "engine_consistency": engine_consistency,
                    "gold_agreement": gold_agreement,
                }
            )
        return result

    @staticmethod
    def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def _provider_manifest(self) -> list[dict[str, Any]]:
        providers: dict[tuple[str | None, str | None, NodeRole], dict[str, Any]] = {}
        for call in self.provider_calls:
            key = (call.provider, call.model_id, call.node_role)
            providers[key] = {
                "node_role": call.node_role,
                "provider": call.provider,
                "model_id": call.model_id,
            }
        return sorted(
            providers.values(),
            key=lambda item: (
                str(item["node_role"]),
                str(item["provider"]),
                str(item["model_id"]),
            ),
        )

    def _write_or_merge_manifest(self, run_root: Path) -> Path:
        manifest_path = run_root / "manifest.json"
        current_artifacts = {
            "database": {
                "filename": self.context.get("database_filename"),
                "sha256": self.context.get("database_sha256"),
            },
            "policy": {
                "filename": self.context.get("policy_filename"),
                "version": self.context.get("policy_version"),
                "sha256": self.context.get("policy_sha256"),
            },
        }
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"existing run manifest is invalid: {manifest_path}") from exc
            if not isinstance(manifest, dict) or manifest.get("run_id") != self.run_id:
                raise ValueError("existing run manifest has a different run_id")
        else:
            manifest = {
                "run_id": self.run_id,
                "created_at": self.created_at,
                "run_metadata": dict(self.run_metadata),
                "artifacts": current_artifacts,
                "agents": {},
            }

        existing_artifacts = manifest.setdefault("artifacts", {})
        for artifact_name, current_values in current_artifacts.items():
            existing_values = existing_artifacts.setdefault(artifact_name, {})
            for key, value in current_values.items():
                if key in existing_values and existing_values[key] not in (None, value):
                    raise ValueError(
                        f"run manifest has conflicting {artifact_name} {key}"
                    )
                if existing_values.get(key) is None:
                    existing_values[key] = value

        existing_metadata = manifest.setdefault("run_metadata", {})
        for key, value in self.run_metadata.items():
            if key in existing_metadata and existing_metadata[key] != value:
                raise ValueError(f"run metadata conflicts for key: {key}")
            existing_metadata[key] = value

        agents = manifest.setdefault("agents", {})
        new_agent = {
            "scaffold_config": self.config.as_scaffold_config(),
            "core_config": self.config.as_core_config(),
            "runtime_config": dict(self.runtime_config),
            "providers": self._provider_manifest(),
        }
        existing_agent = agents.get(self.agent_label)
        if existing_agent is not None:
            for key in ("scaffold_config", "core_config", "runtime_config"):
                if existing_agent.get(key) != new_agent[key]:
                    raise ValueError(
                        f"run manifest has conflicting {key} for {self.agent_label}"
                    )
            merged_providers = {
                (item.get("node_role"), item.get("provider"), item.get("model_id")): item
                for item in existing_agent.get("providers", [])
            }
            for item in new_agent["providers"]:
                merged_providers[(item["node_role"], item["provider"], item["model_id"])] = item
            new_agent["providers"] = sorted(
                merged_providers.values(),
                key=lambda item: (
                    str(item.get("node_role")),
                    str(item.get("provider")),
                    str(item.get("model_id")),
                ),
            )
        agents[self.agent_label] = new_agent
        self._atomic_write_json(manifest_path, manifest)
        return manifest_path

    def write_trial_artifact(
        self,
        output_root: str | Path,
        *,
        policy_correct: bool,
        evaluation_basis: str = "PENDING",
        engine_consistency: bool | None = None,
        gold_agreement: bool | None = None,
    ) -> Path:
        """Write one trial under a collision-resistant run namespace.

        Layout::

            reports/testbed/runs/<run_id>/manifest.json
            reports/testbed/runs/<run_id>/<agent_label>/<testcase_id>/trial_<n>.json
        """

        if self.run_id is None:  # guarded by __post_init__, keeps typing explicit
            raise RuntimeError("run_id is missing")
        for name, value in {
            "run_id": self.run_id,
            "agent_label": self.agent_label,
            "testcase_id": self.testcase_id,
        }.items():
            if not _SAFE_PATH_COMPONENT.fullmatch(value):
                raise ValueError(f"{name} contains unsafe path characters")

        root = Path(output_root).resolve()
        run_root = root / self.run_id
        target_dir = run_root / self.agent_label / self.testcase_id
        target_dir.mkdir(parents=True, exist_ok=True)
        self._write_or_merge_manifest(run_root)

        target = target_dir / f"trial_{self.trial}.json"
        if target.exists():
            raise FileExistsError(f"trial artifact already exists: {target}")
        payload = {
            "trial_result": self.trial_result_dict(
                policy_correct=policy_correct,
                evaluation_basis=evaluation_basis,
                engine_consistency=engine_consistency,
                gold_agreement=gold_agreement,
            ),
            "agent_output": {
                "decision": self.decision,
                "clauses": list(self.policy_clauses),
                "rationale": self.rationale,
                "response": self.response,
                "verifier_status": self.verifier_status,
                "verifier_issues": list(self.verifier_issues),
            },
            "traces": self.trace_dicts(),
            "provider_calls": [call.to_dict() for call in self.provider_calls],
            "runtime_metrics": {
                "structured_output_retry_count": self.structured_output_retry_count,
            },
        }
        self._atomic_write_json(target, payload)
        return target
