"""Finding, Candidate — L4(규칙 탐지기)와 L6(수정 후보 생성)의 출력 단위."""

from pydantic import BaseModel, ConfigDict, Field

from core.schemas.enums import CandidateStatus, FindingType, NodeRole, RiskLevel, Severity


class Evidence(BaseModel):
    """Finding 하나를 뒷받침하는 근거 수치. 전부 코드가 계산한다 (LLM 금지)."""

    model_config = ConfigDict(extra="forbid")

    metric: str = Field(..., description='예: "tool_schema_valid_rate"')
    v0: float
    v1: float
    delta: float | None = None
    delta_pp: float | None = None
    delta_pct: float | None = None
    threshold: str | None = Field(default=None, description='임계값 병기. 예: "+21% >= 임계 15%"')


class FirstDivergence(BaseModel):
    """Trace Diff — 두 버전이 최초로 갈라진 지점. trace 없으면 Finding에 아예 안 붙는다."""

    model_config = ConfigDict(extra="forbid")

    node_role: NodeRole
    step_index: int = Field(..., ge=0)
    detail: str


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    type: FindingType
    severity: Severity
    rule_id: str = Field(..., description='예: "R-02"')
    title: str
    affected_testcases: list[str] = Field(default_factory=list)
    evidence: Evidence
    first_divergence: FirstDivergence | None = None
    explanation: str | None = Field(default=None, description="LLM이 채우는 사람 언어 설명. 숫자는 여기 없다.")
    low_confidence: bool = Field(
        default=False, description="영향 케이스 1건뿐이거나 trial<2일 때 True (오탐 방지, P3-3)"
    )
    cluster_id: str | None = Field(
        default=None, description="LLM이 같은 원인으로 묶은 Finding 그룹 ID (P5). --no-llm이면 항상 None."
    )
    cluster_title: str | None = Field(default=None, description="그 그룹의 사람 언어 제목 (P5)")


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    operator: str = Field(..., description="core/candidate/operators.py 허용 목록 중 하나만 유효")
    target: str = Field(..., description='예: "tool_schema:order_lookup"')
    addresses: list[str] = Field(..., min_length=1, description="해결하려는 Finding.finding_id 목록")
    change_spec: str
    expected_effect: str | None = None
    risk: RiskLevel
    status: CandidateStatus = CandidateStatus.PROPOSED
