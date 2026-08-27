"""골든 테스트 공용 유틸. 테스트 코드와 골든 생성 스크립트가 같은 요약 함수를 쓴다.

여기서 나오는 dict가 곧 골든 JSON의 내용이다 — 사람이 읽고 리뷰할 수 있는 형태로 유지한다.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from pathlib import Path

from core.detector import DetectionContext, decide_verdict, run_rules
from core.diff.aggregate import AggregateResult, aggregate
from core.diff.compare import DiffResult, FlipClass, compare
from core.report import build_report, render_markdown
from core.schemas.loader import LoadResult, load_bundle
from core.schemas.report import UpgradeReport

REPO_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_DIR = REPO_ROOT / "fixtures" / "bundles"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

# scenario_broken은 의도적으로 계약을 어긴 스트레스 테스트 픽스처라 별도 케이스로 다룬다 (test_loader.py).
SCENARIO_NAMES = ["scenario_a", "scenario_clean", "scenario_c", "scenario_b", "scenario_safety"]

# 골든 비교용 고정 시각 — 실제 wall-clock을 쓰면 재현성이 깨진다.
FIXED_GENERATED_AT = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)


def run_pipeline(name: str) -> tuple[LoadResult, AggregateResult, DiffResult]:
    load_result = load_bundle(BUNDLE_DIR / f"{name}.json")
    agg = aggregate(load_result)
    diff = compare(agg)
    return load_result, agg, diff


def summarize(load_result: LoadResult, agg: AggregateResult, diff: DiffResult) -> dict:
    """L1~L3 파이프라인 결과를 JSON 직렬화 가능한 dict로 요약한다 (골든 비교 대상)."""
    return {
        "bundle_id": load_result.bundle_id,
        "labels": list(agg.labels),
        "unpaired_testcases": load_result.unpaired_testcases,
        "skipped_trials": len(load_result.skipped_trials),
        "skipped_traces": len(load_result.skipped_traces),
        "low_confidence": load_result.low_confidence,
        "testcase_count": load_result.testcase_count,
        "trial_count": len(load_result.trials),
        "trace_count": len(load_result.traces) if load_result.traces else 0,
        "overall": {label: dataclasses.asdict(vm) for label, vm in sorted(agg.overall.items())},
        "diff_metrics": {name: dataclasses.asdict(md) for name, md in sorted(diff.overall.metrics.items())},
        "safety_violations_delta": dataclasses.asdict(diff.overall.safety_violations),
        "flip_counts": {cls.value: count for cls, count in sorted(diff.flip_counts.items(), key=lambda kv: kv[0].value)},
        "regression_testcases": sorted(diff.testcases_by(FlipClass.REGRESSION)),
    }


def summarize_detection(load_result: LoadResult, agg: AggregateResult, diff: DiffResult) -> dict:
    """L4(규칙 탐지기) 결과를 골든 비교 가능한 dict로 요약한다."""
    ctx = DetectionContext(load_result=load_result, agg=agg, diff=diff)
    findings, skipped = run_rules(ctx)
    findings = sorted(findings, key=lambda f: f.finding_id)

    return {
        "verdict": decide_verdict(findings).value,
        "findings": [
            {
                "finding_id": f.finding_id,
                "type": f.type.value,
                "severity": f.severity.value,
                "rule_id": f.rule_id,
                "affected_testcases": sorted(f.affected_testcases),
                "low_confidence": f.low_confidence,
                "evidence_metric": f.evidence.metric,
            }
            for f in findings
        ],
        "skipped_rules": sorted(
            [{"rule_id": s.rule_id, "reason": s.reason} for s in skipped], key=lambda s: s["rule_id"]
        ),
    }


def build_report_for(name: str) -> tuple[UpgradeReport, LoadResult]:
    load_result, agg, diff = run_pipeline(name)
    ctx = DetectionContext(load_result=load_result, agg=agg, diff=diff)
    findings, _skipped = run_rules(ctx)
    report = build_report(
        report_id=f"rpt_{name}",
        load_result=load_result,
        agg=agg,
        diff=diff,
        findings=findings,
        generated_at=FIXED_GENERATED_AT,
    )
    return report, load_result


def render_markdown_for(name: str) -> tuple[UpgradeReport, str]:
    report, load_result = build_report_for(name)
    return report, render_markdown(report, load_result=load_result)


def summarize_report(report: UpgradeReport) -> dict:
    """L(Report Builder) 결과를 골든 비교 가능한 dict로 요약한다."""
    s = report.summary
    return {
        "report_id": report.report_id,
        "bundle_id": report.bundle_id,
        "verdict": report.verdict.value,
        "summary": {
            "testcase_count": s.testcase_count,
            "trials_per_case": s.trials_per_case,
            "success_rate_v1": s.success_rate.v1,
            "tool_error_rate_v1": s.tool_error_rate.v1,
            "avg_retry_v1": s.avg_retry.v1,
        },
        "finding_ids": [f.finding_id for f in report.findings],
        "finding_rule_ids": [f.rule_id for f in report.findings],
        "unpaired_testcases": report.unpaired_testcases,
        "limitations": report.limitations,
    }
