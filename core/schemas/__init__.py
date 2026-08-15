"""공용 계약 — core/schemas/README.md 및 docs/CONTRACT.md 참조.

여기 정의된 모델이 팀 전원이 주고받는 JSON의 유일한 정의다.
"""

from core.schemas.agent_version import AgentVersion
from core.schemas.bundle import AuditBundle, SuiteInfo
from core.schemas.enums import (
    CandidateStatus,
    FindingType,
    NodeRole,
    RevalidationStatus,
    RiskLevel,
    Severity,
    StepOutcome,
    StepType,
    StopReason,
    Verdict,
)
from core.schemas.finding import Candidate, Evidence, Finding, FirstDivergence
from core.schemas.report import (
    EfficiencyCheck,
    MetricComparison,
    QualityCheck,
    ReportSummary,
    RevalidationResult,
    SafetyCheck,
    UpgradeReport,
)
from core.schemas.trace import TraceStep
from core.schemas.trial import TrialResult

__all__ = [
    "AgentVersion",
    "AuditBundle",
    "SuiteInfo",
    "StopReason",
    "NodeRole",
    "StepType",
    "StepOutcome",
    "FindingType",
    "Severity",
    "Verdict",
    "RevalidationStatus",
    "RiskLevel",
    "CandidateStatus",
    "TrialResult",
    "TraceStep",
    "Finding",
    "Candidate",
    "Evidence",
    "FirstDivergence",
    "UpgradeReport",
    "ReportSummary",
    "MetricComparison",
    "QualityCheck",
    "SafetyCheck",
    "EfficiencyCheck",
    "RevalidationResult",
    "export_schemas",
]

# 최상위 입력/출력. 나머지는 이 둘의 부품이므로 JSON Schema export도 이 둘만 하면 충분하다.
_TOP_LEVEL_MODELS = {
    "AuditBundle": AuditBundle,
    "UpgradeReport": UpgradeReport,
}


def export_schemas(output_dir: "str | None" = None) -> dict[str, dict]:
    """AuditBundle·UpgradeReport의 JSON Schema를 만든다.

    P1-1 산출물. `docs/CONTRACT.md`와 팀 배포용 샘플의 근거가 되는 단일 소스.

    Args:
        output_dir: 지정하면 `<output_dir>/<ModelName>.schema.json`으로 각각 저장한다.
                    지정하지 않으면 저장 없이 dict만 반환한다.

    Returns:
        {"AuditBundle": {...}, "UpgradeReport": {...}} 형태의 JSON Schema dict.
    """
    schemas = {name: model.model_json_schema() for name, model in _TOP_LEVEL_MODELS.items()}

    if output_dir is not None:
        import json
        from pathlib import Path

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        for name, schema in schemas.items():
            (out / f"{name}.schema.json").write_text(
                json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    return schemas
