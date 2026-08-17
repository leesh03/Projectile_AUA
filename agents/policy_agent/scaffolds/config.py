"""Scaffold 설정 — 기획서 §23.

반복 횟수는 실험 조건이므로 호출부에 상수를 두지 않고 이 파일에서 관리한다.
"""

from typing import Any

AGENT_CONFIG: dict[str, Any] = {
    "use_planner": True,
    "use_sql_repair": True,
    "max_sql_retries": 2,
    "use_reasoning_verifier": True,
    "max_reflections": 2,
    # 개별 루프 카운터와 별개로 거는 전역 상한
    "max_total_steps": 20,
    "max_total_tokens": None,
    "max_total_latency_ms": None,
}


def with_overrides(**overrides: Any) -> dict[str, Any]:
    """기본 설정을 복사해 일부만 바꾼 새 설정을 만든다.

    AGENT_CONFIG를 직접 수정하면 이전 실험 조건이 남으므로 항상 복사한다.
    """
    # dict는 존재하지 않는 키도 그대로 추가되어 오타가 검출되지 않으므로 사전에 차단한다
    unknown = set(overrides) - set(AGENT_CONFIG)
    if unknown:
        raise KeyError(f"AGENT_CONFIG에 없는 키: {sorted(unknown)}")

    config = dict(AGENT_CONFIG)
    config.update(overrides)
    return config
