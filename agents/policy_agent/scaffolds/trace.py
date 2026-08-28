"""실행 단계 기록 헬퍼.

각 파일에서 따로 만들면 형식이 어긋날 수 있으므로 여기를 거쳐서 만든다.
어휘 정의: agents/policy_agent/observability.py

이 모듈은 Auditor를 모른다. 기록을 Auditor 계약으로 옮기고 검증하는 일은
core/ingest/ 가 한다.
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from agents.policy_agent.observability import NodeRole, StepOutcome, StepType


@contextmanager
def timed() -> Iterator[dict[str, int]]:
    """블록 실행 시간을 ms로 잰다. finally로 처리하므로 예외가 나도 측정값이 남는다."""
    box = {"ms": 0}
    started = time.perf_counter()
    try:
        yield box
    finally:
        box["ms"] = int((time.perf_counter() - started) * 1000)


def append_step(
    state: dict[str, Any],
    *,
    node_role: NodeRole,
    step_type: StepType,
    outcome: StepOutcome,
    iteration: int | None = None,
    error_type: str | None = None,
    latency_ms: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    tool_name: str | None = None,
    arguments_valid: bool | None = None,
) -> dict[str, Any]:
    """단계 기록 1건을 만들어 state["trace"]에 붙이고 그 값을 돌려준다.

    step_index는 호출자가 세면 어긋날 수 있어 len(trace)로 매긴다.
    """
    trace: list[dict[str, Any]] = state.setdefault("trace", [])

    record: dict[str, Any] = {
        "testcase_id": state["testcase_id"],
        "agent_label": state["agent_label"],
        "run_id": state.get("run_id"),
        "trial": state.get("trial"),
        "step_index": len(trace),
        "node_role": NodeRole(node_role).value,
        "type": StepType(step_type).value,
        "outcome": StepOutcome(outcome).value,
        "tool_name": tool_name,
        "arguments_valid": arguments_valid,
        "error_type": error_type,
        "iteration": iteration,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": latency_ms,
    }
    trace.append(record)
    state["total_step_count"] = len(trace)
    return record
