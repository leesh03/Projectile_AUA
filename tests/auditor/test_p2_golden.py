"""P2-4 골든 테스트. 같은 입력(fixtures/bundles)에서 항상 같은 집계값이 나오는지 검증한다.

이후 모든 Phase(P3~)의 회귀 방지선. 집계 로직을 고의로 바꿨다면
tests/auditor/golden/generate_golden.py를 다시 돌려 골든을 갱신한다.
"""

from __future__ import annotations

import json

import pytest

from tests.auditor._golden_utils import GOLDEN_DIR, SCENARIO_NAMES, run_pipeline, summarize


@pytest.mark.parametrize("name", SCENARIO_NAMES)
def test_matches_golden(name: str) -> None:
    golden_path = GOLDEN_DIR / f"{name}.json"
    assert golden_path.exists(), f"골든 파일이 없습니다: {golden_path}. generate_golden.py를 먼저 실행하세요."
    expected = json.loads(golden_path.read_text(encoding="utf-8"))

    load_result, agg, diff = run_pipeline(name)
    actual = summarize(load_result, agg, diff)

    assert actual == expected


def test_scenario_clean_has_no_regression() -> None:
    """P3 완료 게이트의 전제 조건 — clean 시나리오는 애초에 flip이 하나도 없어야 한다."""
    load_result, _agg, diff = run_pipeline("scenario_clean")

    regression = [f for f in diff.flips if f.classification.value == "regression"]
    assert regression == []
    assert diff.overall.metrics["success_rate"].delta_pp == 0.0
    assert diff.overall.safety_violations.delta == 0
    assert load_result.unpaired_testcases == []
    assert load_result.skipped_trials == []


def test_scenario_a_isolates_tool_schema_regression() -> None:
    """R-02가 나중에 구현될 때 근거가 될 수치 — 5개 케이스만 영향받고 나머지는 조용해야 한다."""
    _, _, diff = run_pipeline("scenario_a")

    regression_ids = sorted(f.testcase_id for f in diff.flips if f.classification.value == "regression")
    assert regression_ids == ["case_03", "case_07", "case_12", "case_15", "case_18"]
    assert diff.overall.metrics["tool_schema_valid_rate"].delta_pp == -25.0


def test_scenario_c_retry_increase_crosses_e01_threshold() -> None:
    """E-01 임계값(평균 retry 증가 >= 0.5)을 실제로 넘는지 확인 — 안 넘으면 픽스처가 잘못된 것."""
    _, _, diff = run_pipeline("scenario_c")

    avg_retry_delta = diff.overall.metrics["avg_retry"].delta
    assert avg_retry_delta is not None
    assert avg_retry_delta >= 0.5


def test_scenario_safety_flags_violation() -> None:
    _, _, diff = run_pipeline("scenario_safety")

    assert diff.overall.safety_violations.v1 == 1
    assert diff.overall.safety_violations.delta == 1
