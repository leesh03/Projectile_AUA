"""Deterministic quality, safety, and efficiency gates for a candidate run."""

from __future__ import annotations

from core.diff.aggregate import aggregate
from core.schemas.enums import CandidateStatus, RevalidationStatus
from core.schemas.finding import Candidate
from core.schemas.loader import LoadResult
from core.schemas.report import (
    EfficiencyCheck,
    QualityCheck,
    RevalidationResult,
    SafetyCheck,
)


def validate_candidate(
    candidate: Candidate,
    load_result: LoadResult,
    *,
    quality_margin: float = 0.0,
    allowed_safety_violations: int = 0,
) -> RevalidationResult:
    if quality_margin < 0:
        raise ValueError("quality_margin must be non-negative")
    if allowed_safety_violations < 0:
        raise ValueError("allowed_safety_violations must be non-negative")

    agg = aggregate(load_result)
    baseline_label, candidate_label = agg.labels
    baseline = agg.overall[baseline_label]
    applied = agg.overall[candidate_label]

    success_floor = baseline.success_rate - quality_margin
    policy_floor = baseline.policy_accuracy - quality_margin
    quality_ok = (
        applied.success_rate >= success_floor
        and applied.policy_accuracy >= policy_floor
    )
    quality = QualityCheck(
        success_rate=applied.success_rate,
        constraint=(
            f"success_rate >= {success_floor:.4f}; "
            f"policy_accuracy >= {policy_floor:.4f} "
            f"(actual={applied.policy_accuracy:.4f})"
        ),
        ok=quality_ok,
    )

    safety_ok = (
        applied.safety_violations <= allowed_safety_violations
        and applied.safety_violations <= baseline.safety_violations
    )
    safety = SafetyCheck(
        violations=applied.safety_violations,
        constraint=(
            f"violations <= {allowed_safety_violations} and "
            f"violations <= baseline({baseline.safety_violations})"
        ),
        ok=safety_ok,
    )

    token_delta = _pct_delta(baseline.avg_tokens, applied.avg_tokens)
    latency_delta = _pct_delta(baseline.avg_latency_ms, applied.avg_latency_ms)
    retry_delta = applied.avg_retry - baseline.avg_retry
    llm_call_delta = _absolute_delta(
        baseline.avg_llm_call_count,
        applied.avg_llm_call_count,
    )
    improved = any(
        value is not None and value < 0
        for value in (token_delta, latency_delta, retry_delta, llm_call_delta)
    )
    efficiency = EfficiencyCheck(
        avg_tokens_delta_pct=token_delta,
        avg_latency_delta_pct=latency_delta,
        avg_retry_delta=retry_delta,
        avg_llm_call_delta=llm_call_delta,
        improved=improved,
    )

    if not safety_ok:
        status = RevalidationStatus.BLOCK
        explanation = "안전 Gate를 통과하지 못해 후보를 차단했다."
    elif load_result.low_confidence:
        status = RevalidationStatus.INCONCLUSIVE
        explanation = "반복 실행이 2회 미만이어서 재검증 결론을 보류했다."
    elif not quality_ok:
        status = RevalidationStatus.HOLD
        explanation = "품질 비열등성 Gate를 통과하지 못해 후보 적용을 보류했다."
    elif improved or candidate.operator == "KEEP":
        status = RevalidationStatus.PASS
        explanation = "품질·안전 Gate를 통과했고 목표 효율 또는 보존 조건을 만족했다."
    else:
        status = RevalidationStatus.HOLD
        explanation = "품질·안전은 유지됐지만 측정 가능한 효율 개선이 없어 보류했다."

    return RevalidationResult(
        candidate_id=candidate.candidate_id,
        status=status,
        quality=quality,
        safety=safety,
        efficiency=efficiency,
        explanation=explanation,
    )


def candidate_with_result(candidate: Candidate, result: RevalidationResult) -> Candidate:
    status = {
        RevalidationStatus.PASS: CandidateStatus.APPLIED,
        RevalidationStatus.BLOCK: CandidateStatus.REJECTED,
    }.get(result.status, CandidateStatus.PROPOSED)
    return candidate.model_copy(update={"status": status})


def _pct_delta(baseline: float, candidate: float) -> float | None:
    if baseline == 0:
        return None
    return (candidate - baseline) / baseline * 100


def _absolute_delta(baseline: float | None, candidate: float | None) -> float | None:
    if baseline is None or candidate is None:
        return None
    return candidate - baseline
