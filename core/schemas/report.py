"""UpgradeReport — Auditor의 최종 출력. JSON을 먼저 만들고 Markdown은 이 JSON을 렌더링한 것.

같은 UpgradeReport JSON에서는 항상 같은 Markdown이 나와야 한다 (재현성 = 대회 fallback의 근거).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from core.schemas.enums import RevalidationStatus, Verdict
from core.schemas.finding import Candidate, Finding


class MetricComparison(BaseModel):
    """summary의 지표 1개. v0/v1 원본값을 항상 병기한다 (숫자 옆에 근거)."""

    model_config = ConfigDict(extra="forbid")

    v0: float
    v1: float
    delta: float | None = None
    delta_pp: float | None = None
    delta_pct: float | None = None


class ReportSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    testcase_count: int = Field(..., ge=0)
    trials_per_case: float = Field(..., ge=0)
    success_rate: MetricComparison
    tool_error_rate: MetricComparison
    avg_retry: MetricComparison
    avg_tokens: MetricComparison
    avg_latency_ms: MetricComparison
    safety_violation: MetricComparison


class QualityCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success_rate: float
    constraint: str
    ok: bool


class SafetyCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    violations: int = Field(..., ge=0)
    constraint: str
    ok: bool


class EfficiencyCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    avg_tokens_delta_pct: float | None = None
    avg_latency_delta_pct: float | None = None
    avg_retry_delta: float | None = None
    improved: bool


class RevalidationResult(BaseModel):
    """P7 재검증 게이트 출력. candidate 1건당 1개. 판정은 코드만 내리고 LLM은 설명만 붙인다."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    status: RevalidationStatus
    quality: QualityCheck | None = None
    safety: SafetyCheck | None = None
    efficiency: EfficiencyCheck | None = None
    explanation: str | None = None


class UpgradeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str
    bundle_id: str
    verdict: Verdict
    generated_at: datetime
    summary: ReportSummary
    findings: list[Finding] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)
    revalidation: list[RevalidationResult] = Field(default_factory=list)
    unpaired_testcases: list[str] = Field(
        default_factory=list, description="V0/V1 한쪽에만 있어 비교에서 제외된 testcase_id"
    )
    limitations: list[str] = Field(default_factory=list, description="표본 수·trial 수·trace 유무 등 자동 생성")
