"""대상 에이전트의 실행 로그를 Auditor 계약으로 옮긴다.

이 방향이 중요하다. 에이전트는 자기 로그만 남기고 Auditor를 모른다.
남의 로그를 읽어 자기 형식으로 바꾸는 법을 아는 쪽은 Auditor다.
그래야 Auditor가 특정 에이전트에 묶이지 않는다.

지금은 Policy Agent 로그만 다루지만, 다른 에이전트를 붙일 때는
여기에 매퍼를 하나 더 추가하면 된다. `agents/` 는 건드리지 않는다.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from core.schemas.trace import TraceStep
from core.schemas.trial import TrialResult


class IngestError(ValueError):
    """에이전트 로그가 Auditor 계약을 만족하지 못할 때."""


def to_trial_result(observation: dict[str, Any]) -> dict[str, Any]:
    """실행 1회 관측값 → ``TrialResult``.

    필드명이나 enum 값이 어긋나면 여기서 멈춘다. 이전에는 이 검증을
    에이전트 쪽 ``append_step`` 이 하고 있었다.
    """
    try:
        return TrialResult.model_validate(observation).model_dump(mode="json")
    except ValidationError as exc:
        case = observation.get("testcase_id", "?")
        raise IngestError(f"TrialResult 계약 위반 (testcase_id={case}): {exc}") from exc


def to_trace_steps(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """단계 기록 목록 → ``TraceStep`` 목록."""
    steps: list[dict[str, Any]] = []
    for record in records:
        try:
            steps.append(TraceStep.model_validate(record).model_dump(mode="json"))
        except ValidationError as exc:
            where = f"{record.get('testcase_id', '?')}#{record.get('step_index', '?')}"
            raise IngestError(f"TraceStep 계약 위반 ({where}): {exc}") from exc
    return steps
