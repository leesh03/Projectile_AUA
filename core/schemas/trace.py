"""TraceStep — AuditBundle.traces[]. 선택 필드. 없으면 Trace Diff/O-01/O-02가 NOT_AVAILABLE·SKIPPED로 처리된다."""

from pydantic import BaseModel, ConfigDict, Field

from core.schemas.enums import NodeRole, StepOutcome, StepType


class TraceStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # --- 페어링 키 ---
    testcase_id: str
    agent_label: str = Field(..., description="AuditBundle.baseline/candidate.label과 일치해야 함")
    run_id: str | None = Field(default=None, description="같은 testcase·trial의 실행 1회를 식별")
    trial: int | None = Field(default=None, ge=1, le=3, description="어느 TrialResult에 속하는지")

    # --- 단계 정보 ---
    step_index: int = Field(..., ge=0, description="같은 run 안에서의 순서")
    node_role: NodeRole
    type: StepType
    outcome: StepOutcome

    # --- 선택 ---
    tool_name: str | None = None
    arguments_valid: bool | None = Field(default=None, description="시나리오 A: tool 인자 스키마 유효성")
    error_type: str | None = None
    iteration: int | None = Field(default=None, ge=0, description="retry 회차 (O-02 회복률 계산)")
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
