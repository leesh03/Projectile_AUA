"""TraceStep 생성 헬퍼.

각 파일에서 따로 만들면 형식이 어긋날 수 있으므로 여기를 거쳐서 만든다.
필드 정의: docs/CONTRACT.md §2 · core/schemas/trace.py
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from core.schemas.enums import NodeRole, StepOutcome, StepType
from core.schemas.trace import TraceStep


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
    """TraceStep 1건을 만들어 state["trace"]에 붙이고 그 값을 돌려준다.

    step_index는 호출자가 세면 어긋날 수 있어 len(trace)로 매긴다.
    TraceStep으로 검증하므로 필드명이나 enum 값이 틀리면 이 지점에서 멈춘다.
    """
    trace: list[dict[str, Any]] = state.setdefault("trace", [])

    step = TraceStep(
        testcase_id=state["testcase_id"],
        agent_label=state["agent_label"],
        run_id=state.get("run_id"),
        trial=state.get("trial"),
        step_index=len(trace),
        node_role=node_role,
        type=step_type,
        outcome=outcome,
        iteration=iteration,
        error_type=error_type,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tool_name=tool_name,
        arguments_valid=arguments_valid,
    )

    record = step.model_dump(mode="json")
    trace.append(record)
    state["total_step_count"] = len(trace)
    return record
