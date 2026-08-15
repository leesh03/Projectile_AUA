"""골든 테스트 공용 유틸. 테스트 코드와 골든 생성 스크립트가 같은 요약 함수를 쓴다.

여기서 나오는 dict가 곧 골든 JSON의 내용이다 — 사람이 읽고 리뷰할 수 있는 형태로 유지한다.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from core.diff.aggregate import AggregateResult, aggregate
from core.diff.compare import DiffResult, FlipClass, compare
from core.schemas.loader import LoadResult, load_bundle

REPO_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_DIR = REPO_ROOT / "fixtures" / "bundles"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

# scenario_broken은 의도적으로 계약을 어긴 스트레스 테스트 픽스처라 별도 케이스로 다룬다 (test_loader.py).
SCENARIO_NAMES = ["scenario_a", "scenario_clean", "scenario_c", "scenario_b", "scenario_safety"]


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
