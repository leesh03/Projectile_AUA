"""Provider-neutral orchestration for the policy-agent Core."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from time import perf_counter_ns
from typing import Any, Protocol

from agents.policy_agent.nodes.context_provider import ContextProvider, ContextProviderError
from agents.policy_agent.nodes.evidence_check import EvidenceAssemblyError, EvidenceChecker
from agents.policy_agent.nodes.policy_reasoner import PolicyReasoner, PolicyReasoningError
from agents.policy_agent.nodes.response_writer import ResponseWriter
from agents.policy_agent.nodes.sql_executor import SQLExecutionError, SQLExecutor, SQLGuardError
from agents.policy_agent.nodes.sql_generator import (
    SQLGenerationError,
    SQLGenerator,
    SQLPlan,
    SQLQuery,
)
from agents.policy_agent.nodes.state import (
    DEFAULT_REQUIRED_EVIDENCE_PATHS,
    AgentConfig,
    AgentRequest,
    NodeRole,
    PolicyAgentState,
    StepType,
)


class SQLRepair(Protocol):
    """Interface the Repair scaffold must implement."""

    def __call__(
        self,
        state: PolicyAgentState,
        query: SQLQuery,
        error: Exception,
    ) -> SQLQuery: ...


class ReasoningVerifier(Protocol):
    """Existing team-facing Verifier interface; changes require agreement."""

    def __call__(self, state: PolicyAgentState) -> bool: ...


@dataclass(frozen=True, slots=True)
class AgentRun:
    state: PolicyAgentState

    @property
    def traces(self) -> list[dict[str, Any]]:
        return self.state.trace_dicts()


class PolicyAgentGraph:
    """Run Core without requiring LangGraph or one specific LLM SDK."""

    def __init__(
        self,
        *,
        context_provider: ContextProvider,
        sql_generator: SQLGenerator,
        sql_executor: SQLExecutor,
        evidence_checker: EvidenceChecker,
        policy_reasoner: PolicyReasoner,
        response_writer: ResponseWriter,
        config: AgentConfig | None = None,
        sql_repair: SQLRepair
        | Callable[[PolicyAgentState, SQLQuery, Exception], SQLQuery]
        | None = None,
        reasoning_verifier: ReasoningVerifier | Callable[[PolicyAgentState], bool] | None = None,
    ) -> None:
        self.context_provider = context_provider
        self.sql_generator = sql_generator
        self.sql_executor = sql_executor
        self.evidence_checker = evidence_checker
        self.policy_reasoner = policy_reasoner
        self.response_writer = response_writer
        self.config = config or AgentConfig()
        self.sql_repair = sql_repair
        self.reasoning_verifier = reasoning_verifier
        if self.config.enable_repair and self.sql_repair is None:
            raise ValueError("enable_repair requires a sql_repair adapter")
        if self.config.enable_verifier and self.reasoning_verifier is None:
            raise ValueError("enable_verifier requires a reasoning_verifier adapter")

    @staticmethod
    def _elapsed_ms(started_ns: int) -> int:
        return max(0, (perf_counter_ns() - started_ns) // 1_000_000)

    @staticmethod
    def _latest_provider_tokens(
        state: PolicyAgentState, before_count: int, node_role: NodeRole
    ) -> tuple[int | None, int | None]:
        if len(state.provider_calls) <= before_count:
            return None, None
        call = state.provider_calls[-1]
        if call.node_role != node_role:
            return None, None
        return call.usage.input_tokens, call.usage.output_tokens

    def _run_step(
        self,
        state: PolicyAgentState,
        *,
        node_role: NodeRole,
        step_type: StepType,
        operation: Callable[[], Any],
        tool_name: str | None = None,
        arguments_valid: bool | None = None,
        iteration: int | None = None,
    ) -> Any:
        started_ns = perf_counter_ns()
        provider_calls_before = len(state.provider_calls)
        try:
            result = operation()
        except Exception as exc:
            failed_arguments_valid = False if node_role == "VALIDATE_QUERY" else arguments_valid
            input_tokens, output_tokens = self._latest_provider_tokens(
                state, provider_calls_before, node_role
            )
            state.add_trace(
                node_role=node_role,
                step_type=step_type,
                outcome="fail",
                latency_ms=self._elapsed_ms(started_ns),
                tool_name=tool_name,
                arguments_valid=failed_arguments_valid,
                error_type=getattr(exc, "code", type(exc).__name__),
                iteration=iteration,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            raise
        input_tokens, output_tokens = self._latest_provider_tokens(
            state, provider_calls_before, node_role
        )
        state.add_trace(
            node_role=node_role,
            step_type=step_type,
            outcome="ok",
            latency_ms=self._elapsed_ms(started_ns),
            tool_name=tool_name,
            arguments_valid=arguments_valid,
            iteration=iteration,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        return result

    def _execute_query_plan(self, state: PolicyAgentState, plan: SQLPlan) -> None:
        completed_queries: list[SQLQuery] = []
        for original_query in plan.queries:
            query = original_query
            attempt = 0
            while True:
                try:
                    self._run_step(
                        state,
                        node_role="VALIDATE_QUERY",
                        step_type="code",
                        operation=lambda q=query: self.sql_executor.guard.validate(q.sql),
                        tool_name=f"sql_guard:{query.name}",
                        arguments_valid=True,
                        iteration=attempt,
                    )
                    result = self._run_step(
                        state,
                        node_role="EXECUTE_TOOL",
                        step_type="tool_call",
                        operation=lambda q=query: self.sql_executor.execute(q.sql, q.parameters),
                        tool_name=f"sqlite_select:{query.name}",
                        arguments_valid=True,
                        iteration=attempt,
                    )
                    state.query_results[query.name] = list(result.rows)
                    state.rows_truncated = state.rows_truncated or result.truncated
                    if state.tool_schema_valid is None:
                        state.tool_schema_valid = True
                    completed_queries.append(query)
                    break
                except (SQLGuardError, SQLExecutionError) as exc:
                    state.tool_error_count += 1
                    is_safety_violation = isinstance(exc, SQLGuardError)
                    if is_safety_violation:
                        state.tool_schema_valid = False
                        state.safety_violation = True
                    safety_repair_allowed = (
                        not is_safety_violation or self.config.repair_safety_violations
                    )
                    can_repair = (
                        safety_repair_allowed
                        and self.config.enable_repair
                        and self.sql_repair is not None
                        and state.retry_count < self.config.max_retries
                    )
                    if not can_repair:
                        raise
                    state.retry_count += 1
                    attempt += 1
                    state.llm_call_count += 1
                    repaired = self._run_step(
                        state,
                        node_role="REPAIR_QUERY",
                        step_type="llm_call",
                        operation=lambda q=query, e=exc: self.sql_repair(state, q, e),
                        tool_name=f"sql_repair:{query.name}",
                        iteration=attempt,
                    )
                    if not isinstance(repaired, SQLQuery):
                        raise SQLGenerationError("repair adapter must return SQLQuery")
                    if repaired.name != query.name:
                        raise SQLGenerationError("repair adapter must preserve the query name")
                    query = repaired

        state.query_plan = SQLPlan(
            queries=tuple(completed_queries),
            input_tokens=plan.input_tokens,
            output_tokens=plan.output_tokens,
        )

    def run(
        self,
        request: AgentRequest,
        *,
        agent_label: str = "V0",
        trial: int = 1,
        run_id: str | None = None,
        required_evidence_paths: tuple[str, ...] = DEFAULT_REQUIRED_EVIDENCE_PATHS,
        run_metadata: Mapping[str, Any] | None = None,
    ) -> AgentRun:
        state = PolicyAgentState(
            agent_request=request,
            agent_label=agent_label,
            trial=trial,
            run_id=run_id,
            required_evidence_paths=required_evidence_paths,
            config=self.config,
            run_metadata=dict(run_metadata or {}),
        )
        state.runtime_config["sql_executor"] = self.sql_executor.config_dict()

        try:
            self._run_step(
                state,
                node_role="RETRIEVE_SCHEMA",
                step_type="code",
                operation=lambda: self.context_provider(state),
            )
            plan = self._run_step(
                state,
                node_role="GENERATE_QUERY",
                step_type="llm_call",
                operation=lambda: self.sql_generator(state),
            )
            self._execute_query_plan(state, plan)

            structural_evidence = self._run_step(
                state,
                node_role="CHECK_EVIDENCE",
                step_type="code",
                operation=lambda: self.evidence_checker(state),
                tool_name="structural_evidence",
            )
            if not structural_evidence.sufficient:
                self._run_step(
                    state,
                    node_role="GENERATE_RESPONSE",
                    step_type="code",
                    operation=lambda: self.response_writer.write_insufficient_evidence(state),
                )
                state.error_type = structural_evidence.reason
                state.finish("INSUFFICIENT_EVIDENCE", success=False)
                return AgentRun(state)

            self._run_step(
                state,
                node_role="DECIDE",
                step_type="llm_call",
                operation=lambda: self.policy_reasoner(state),
            )

            policy_evidence = self._run_step(
                state,
                node_role="CHECK_EVIDENCE",
                step_type="code",
                operation=lambda: self.evidence_checker.evaluate_policy_requirements(state),
                tool_name="policy_clause_evidence",
            )
            if not policy_evidence.sufficient:
                self._run_step(
                    state,
                    node_role="GENERATE_RESPONSE",
                    step_type="code",
                    operation=lambda: self.response_writer.write_policy_evidence_missing(state),
                )
                state.error_type = policy_evidence.reason
                state.finish("INSUFFICIENT_EVIDENCE", success=False)
                return AgentRun(state)

            if self.config.enable_verifier and self.reasoning_verifier is not None:
                state.llm_call_count += 1
                accepted = self._run_step(
                    state,
                    node_role="VERIFY_REASONING",
                    step_type="llm_call",
                    operation=lambda: self.reasoning_verifier(state),
                )
                if accepted is not True:
                    state.fail(
                        "MAX_REFLECTION",
                        error_type="VERIFIER_REJECTED",
                        message="reasoning verifier rejected the decision",
                    )
                    return AgentRun(state)

            self._run_step(
                state,
                node_role="GENERATE_RESPONSE",
                step_type="code",
                operation=lambda: self.response_writer(state),
            )
            # The meaning of task_success for a policy-level NEED_MORE_INFO is a
            # team/Auditor decision. Preserve the existing behavior until agreed.
            if state.decision == "NEED_MORE_INFO":
                state.error_type = "REASONER_NEEDS_MORE_INFO"
                state.finish("INSUFFICIENT_EVIDENCE", success=False)
                return AgentRun(state)
            state.finish("OK", success=True)
            return AgentRun(state)

        except SQLGuardError as exc:
            exhausted = self.config.enable_repair and state.retry_count >= self.config.max_retries
            stop_reason = "MAX_RETRY" if exhausted else "TOOL_SCHEMA_ERROR"
            state.fail(stop_reason, error_type=exc.code, message=str(exc))
        except SQLExecutionError as exc:
            exhausted = self.config.enable_repair and state.retry_count >= self.config.max_retries
            stop_reason = "MAX_RETRY" if exhausted else "SQL_FAILURE"
            state.fail(stop_reason, error_type=exc.code, message=str(exc))
        except EvidenceAssemblyError as exc:
            state.tool_schema_valid = False
            state.tool_error_count += 1
            state.fail("TOOL_SCHEMA_ERROR", error_type=f"EVIDENCE:{exc.code}", message=str(exc))
        except ContextProviderError as exc:
            state.fail(
                "PROVIDER_ERROR",
                error_type=f"CONTEXT:{type(exc).__name__}",
                message=str(exc),
            )
        except (SQLGenerationError, PolicyReasoningError) as exc:
            state.fail(
                "PROVIDER_ERROR",
                error_type=f"PROVIDER:{type(exc).__name__}",
                message=str(exc),
            )
        except Exception as exc:  # noqa: BLE001 - isolate one failed trial
            state.fail(
                "PROVIDER_ERROR",
                error_type=f"CORE:{type(exc).__name__}",
                message=str(exc),
            )
        return AgentRun(state)
