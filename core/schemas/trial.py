"""TrialResult — AuditBundle.trials[]. Auditor가 소비하는 가장 중요한 단위.

필수 필드가 없으면 해당 필드를 쓰는 규칙만 SKIPPED 처리된다 (loader.py, P2).
필드별 "없으면 못 하는 것"은 docs/CONTRACT.md 표 참조.
"""

from pydantic import BaseModel, ConfigDict, Field

from core.schemas.enums import StopReason


class TrialResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # --- 필수 (CONTRACT.md §1) ---
    testcase_id: str
    agent_label: str = Field(..., description="AuditBundle.baseline/candidate.label과 일치해야 함")
    trial: int = Field(..., ge=1, le=3, description="같은 testcase의 반복 회차 (1~3)")
    task_success: bool
    policy_correct: bool
    tool_error_count: int = Field(..., ge=0)
    retry_count: int = Field(..., ge=0)
    total_tokens: int = Field(..., ge=0)
    latency_ms: int = Field(..., ge=0)
    safety_violation: bool
    stop_reason: StopReason

    # --- 권장 (CONTRACT.md §2, 없어도 SKIPPED로 우아하게 저하) ---
    error_type: str | None = Field(default=None, description="Regression 그룹핑에 사용")
    tool_schema_valid: bool | None = Field(default=None, description="시나리오 A 정밀도(R-02)")
    llm_call_count: int | None = Field(default=None, ge=0, description="시나리오 B 절감 추정(O-01)")
    scaffold_config: dict | None = Field(
        default=None,
        description='예: {"planner": false, "repair": 2, "verifier": 1} — Opportunity 탐지',
    )
    difficulty: str | None = Field(
        default=None,
        description="TestCase 난이도 (Easy/Medium/Hard). 없으면 R-05 SKIPPED. P9에서 팀원 데이터로 채워짐.",
    )
