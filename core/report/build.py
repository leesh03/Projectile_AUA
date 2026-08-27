"""UpgradeReport 조립. L1~L4 산출물을 받아 최종 출력 스키마 하나로 묶는다.

여기서부터는 순수 조립·정렬·서식뿐이다. 숫자를 새로 계산하지 않는다 —
전부 L2(Aggregate)·L3(Diff)가 이미 계산한 값을 그대로 옮겨 담는다.
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.detector.verdict import decide_verdict
from core.diff.aggregate import AggregateResult
from core.diff.compare import DiffResult, MetricDelta
from core.schemas.enums import Severity
from core.schemas.finding import Candidate, Finding
from core.schemas.loader import LoadResult
from core.schemas.report import MetricComparison, ReportSummary, RevalidationResult, UpgradeReport

_SEVERITY_ORDER = {Severity.P0: 0, Severity.P1: 1, Severity.P2: 2}


def _to_comparison(md: MetricDelta) -> MetricComparison:
    return MetricComparison(v0=md.v0, v1=md.v1, delta=md.delta, delta_pp=md.delta_pp, delta_pct=md.delta_pct)


def _build_summary(load_result: LoadResult, agg: AggregateResult, diff: DiffResult) -> ReportSummary:
    v0_label, v1_label = agg.labels
    v0m, v1m = agg.overall[v0_label], agg.overall[v1_label]
    testcase_count = load_result.testcase_count

    trials_per_case = 0.0
    if testcase_count:
        trials_per_case = (v0m.trial_count + v1m.trial_count) / (2 * testcase_count)

    return ReportSummary(
        testcase_count=testcase_count,
        trials_per_case=round(trials_per_case, 2),
        success_rate=_to_comparison(diff.overall.metrics["success_rate"]),
        tool_error_rate=_to_comparison(diff.overall.metrics["tool_error_rate"]),
        avg_retry=_to_comparison(diff.overall.metrics["avg_retry"]),
        avg_tokens=_to_comparison(diff.overall.metrics["avg_tokens"]),
        avg_latency_ms=_to_comparison(diff.overall.metrics["avg_latency_ms"]),
        safety_violation=MetricComparison(
            v0=float(v0m.safety_violations),
            v1=float(v1m.safety_violations),
            delta=float(diff.overall.safety_violations.delta or 0),
        ),
    )


def _sort_key(finding: Finding) -> tuple[int, int, str]:
    return (_SEVERITY_ORDER.get(finding.severity, 99), -len(finding.affected_testcases), finding.rule_id)


def _renumber(findings: list[Finding]) -> list[Finding]:
    """정렬 후 F-01, F-02...로 다시 번호를 매긴 새 Finding 목록을 반환한다.

    원본 객체는 건드리지 않는다 — detector 쪽 finding_id(F-{rule_id})는 L4 자체 테스트의
    비교 기준이라 여기서 바꾸면 안 된다.
    """
    ordered = sorted(findings, key=_sort_key)
    return [f.model_copy(update={"finding_id": f"F-{i + 1:02d}"}) for i, f in enumerate(ordered)]


def _build_limitations(load_result: LoadResult) -> list[str]:
    limitations: list[str] = []
    testcase_count = load_result.testcase_count
    trial_counts = {t.trial for t in load_result.trials}
    trials_per_case = max(trial_counts) if trial_counts else 0
    limitations.append(f"TestCase {testcase_count}개 · 반복 {trials_per_case}회 기준이므로 통계적 일반화는 주장하지 않음")

    if not load_result.traces:
        limitations.append("Trace 데이터가 없어 최초 분기 지점(Trace Diff)과 O-01/O-02 규칙을 확인할 수 없음")
    if load_result.low_confidence:
        limitations.append("일부 testcase는 trial 반복이 2회 미만이라 해당 Finding은 낮은 신뢰도(low_confidence)로 표시됨")
    if load_result.unpaired_testcases:
        limitations.append(
            f"{len(load_result.unpaired_testcases)}개 testcase가 baseline/candidate 한쪽에만 있어 비교에서 제외됨: "
            f"{load_result.unpaired_testcases}"
        )
    if load_result.skipped_trials:
        limitations.append(f"trial {len(load_result.skipped_trials)}건이 계약 위반(필수 필드 누락)으로 제외됨")
    return limitations


def build_report(
    *,
    report_id: str,
    load_result: LoadResult,
    agg: AggregateResult,
    diff: DiffResult,
    findings: list[Finding],
    candidates: list[Candidate] | None = None,
    revalidation: list[RevalidationResult] | None = None,
    generated_at: datetime | None = None,
) -> UpgradeReport:
    verdict = decide_verdict(findings)
    return UpgradeReport(
        report_id=report_id,
        bundle_id=load_result.bundle_id,
        verdict=verdict,
        generated_at=generated_at or datetime.now(UTC),
        summary=_build_summary(load_result, agg, diff),
        findings=_renumber(findings),
        candidates=candidates or [],
        revalidation=revalidation or [],
        unpaired_testcases=load_result.unpaired_testcases,
        limitations=_build_limitations(load_result),
    )
