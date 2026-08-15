"""AuditBundle — Auditor가 받는 유일한 최상위 입력."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.schemas.agent_version import AgentVersion
from core.schemas.trace import TraceStep
from core.schemas.trial import TrialResult


class SuiteInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite_id: str
    testcase_ids: list[str] = Field(..., min_length=1)
    dataset_version: str


class AuditBundle(BaseModel):
    """파일 하나 또는 JSON 텍스트 하나. loader.py(P2)가 이걸 파싱·페어링한다.

    여기서 하는 검증은 "구조적으로 말이 되는가"까지다.
    (예: trial 한 건도 없다, agent_label이 baseline/candidate 어느 쪽도 아니다)
    필드가 없어서 특정 규칙을 못 돌리는 문제는 loader.py가 규칙별 SKIPPED로 처리한다.
    """

    model_config = ConfigDict(extra="forbid")

    bundle_id: str
    created_at: datetime
    suite: SuiteInfo
    baseline: AgentVersion
    candidate: AgentVersion
    change_note: str | None = None
    trials: list[TrialResult] = Field(..., min_length=1)
    traces: list[TraceStep] | None = None

    @model_validator(mode="after")
    def _check_labels_consistent(self) -> "AuditBundle":
        if self.baseline.label == self.candidate.label:
            raise ValueError(
                f"baseline.label과 candidate.label이 같습니다 ({self.baseline.label!r}). "
                "두 버전을 구분할 수 없습니다."
            )
        allowed = {self.baseline.label, self.candidate.label}

        bad_trial_labels = {t.agent_label for t in self.trials} - allowed
        if bad_trial_labels:
            raise ValueError(
                f"trials에 baseline/candidate에 없는 agent_label이 있습니다: {sorted(bad_trial_labels)} "
                f"(허용값: {sorted(allowed)})"
            )

        if self.traces:
            bad_trace_labels = {t.agent_label for t in self.traces} - allowed
            if bad_trace_labels:
                raise ValueError(
                    f"traces에 baseline/candidate에 없는 agent_label이 있습니다: {sorted(bad_trace_labels)} "
                    f"(허용값: {sorted(allowed)})"
                )
        return self
