"""SQL Repair Loop.

실패한 SQL을 오류 메시지와 함께 LLM에 다시 넘겨 수정 SQL을 생성하고 재실행한다.
SQL 문법·스키마·실행 오류만 다루며 정책 판단은 취급하지 않는다(v2 기획서 §25).

repair_once와 repair_loop 두 가지를 제공한다.
graph가 반복을 제어하면 repair_once를, 반복까지 맡기려면 repair_loop를 사용한다.
"""

from typing import Any, NamedTuple, Protocol

from core.schemas.enums import NodeRole, StepOutcome, StepType, StopReason

from .llm import LLMClient
from .trace import append_step, timed


class ExecResult(NamedTuple):
    """SQL 실행 결과. 준원의 executor 반환 형태와 일치해야 한다."""

    success: bool
    rows: list[dict] | None = None
    error_type: str | None = None
    error_message: str | None = None


class SQLExecutor(Protocol):
    def __call__(self, sql: str) -> ExecResult: ...


REPAIR_PROMPT = """\
다음 SQL이 실행에 실패했다. 오류를 보고 수정한 SQL 한 문장만 출력하라.

[스키마]
{schema}

[질문]
{question}

[실패한 SQL]
{sql}

[오류]
{error_type}: {error_message}

[이전 시도]
{history}

수정한 SQL:"""


def build_repair_prompt(state: dict[str, Any]) -> str:
    """수정 요청 프롬프트를 만든다.

    이전 시도를 함께 넣는다. 같은 오류를 반복 생성하는 것을 줄이기 위한 것이며,
    통합 기획서 §6.2의 입력 항목(failed_sql, error_type, error_message,
    schema_context, user_query)을 모두 포함한다.
    """
    history = state.get("sql_history") or []
    return REPAIR_PROMPT.format(
        schema=state.get("schema_context") or "(제공되지 않음)",
        question=state.get("user_query") or "",
        sql=state.get("sql") or "",
        error_type=state.get("sql_error_type") or "UNKNOWN",
        error_message=state.get("sql_error_message") or "(메시지 없음)",
        history="\n".join(f"- {s}" for s in history) if history else "(없음)",
    )


def repair_once(state: dict[str, Any], llm: LLMClient) -> dict[str, Any]:
    """실패한 SQL을 1회 수정한다. 재실행은 하지 않는다.

    호출 전 state에 sql, sql_error_type, sql_error_message가 채워져 있어야 한다.
    """
    prompt = build_repair_prompt(state)

    with timed() as t:
        result = llm(prompt)

    previous_sql = state.get("sql") or ""
    repaired = result.text.strip()

    state.setdefault("sql_history", []).append(previous_sql)
    state["sql"] = repaired
    state["sql_retry_count"] = state.get("sql_retry_count", 0) + 1

    append_step(
        state,
        node_role=NodeRole.REPAIR_QUERY,
        step_type=StepType.LLM_CALL,
        outcome=StepOutcome.OK,
        iteration=state["sql_retry_count"],
        error_type=state.get("sql_error_type"),
        latency_ms=t["ms"],
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )
    return state


def _record_execution(state: dict[str, Any], result: ExecResult, latency_ms: int) -> None:
    """재실행 결과를 state와 trace에 반영한다.

    최초 실행은 Core가 기록하므로 여기서는 루프가 유발한 재실행만 남긴다.
    """
    state["sql_success"] = result.success
    state["sql_result"] = result.rows or []
    state["sql_error_type"] = result.error_type
    state["sql_error_message"] = result.error_message

    append_step(
        state,
        node_role=NodeRole.EXECUTE_TOOL,
        step_type=StepType.TOOL_CALL,
        outcome=StepOutcome.OK if result.success else StepOutcome.FAIL,
        iteration=state.get("sql_retry_count", 0),
        error_type=result.error_type,
        latency_ms=latency_ms,
    )


def repair_loop(
    state: dict[str, Any],
    config: dict[str, Any],
    llm: LLMClient,
    execute: SQLExecutor,
) -> dict[str, Any]:
    """설정 횟수만큼 수정과 재실행을 반복한다.

    종료 조건은 세 가지이며 모두 명시적 stop_reason으로 끝난다.
      - 재실행 성공: stop_reason을 설정하지 않고 반환(후속 노드가 계속 진행)
      - repair 미사용 또는 횟수 소진: SQL_FAILURE / MAX_RETRY
      - 동일 오류 연속 발생: 남은 횟수를 사용하지 않고 MAX_RETRY
    """
    if state.get("sql_success"):
        return state

    # repair가 꺼진 상태의 실패는 MAX_RETRY가 아니라 SQL_FAILURE로 구분한다.
    # 두 값을 나눠야 repair 유무에 따른 효과를 비교할 수 있다.
    if not config.get("use_sql_repair"):
        state["stop_reason"] = StopReason.SQL_FAILURE.value
        return state

    max_retries = config.get("max_sql_retries", 0)
    if max_retries <= 0:
        state["stop_reason"] = StopReason.SQL_FAILURE.value
        return state

    max_total_steps = config.get("max_total_steps")
    stop_on_repeated = config.get("stop_on_repeated_error", True)

    for _ in range(max_retries):
        # 개별 카운터와 별개로 두는 전역 상한. 다른 노드의 단계까지 합산한다.
        if max_total_steps is not None and state.get("total_step_count", 0) >= max_total_steps:
            state["stop_reason"] = StopReason.MAX_RETRY.value
            return state

        previous_error = state.get("sql_error_type")

        repair_once(state, llm)

        with timed() as t:
            result = execute(state["sql"])
        _record_execution(state, result, t["ms"])

        if result.success:
            return state

        # 같은 오류가 다시 나오면 남은 횟수를 써도 결과가 달라지지 않는다고 보고 중단한다.
        if stop_on_repeated and result.error_type is not None and result.error_type == previous_error:
            state["stop_reason"] = StopReason.MAX_RETRY.value
            return state

    state["stop_reason"] = StopReason.MAX_RETRY.value
    return state
