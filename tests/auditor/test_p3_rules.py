"""P3 완료 게이트 검증.

체크리스트 (AUA_Phase별_개발순서.md):
- scenario_a -> R-02 발화, 나머지 "핵심 6개" 규칙은 조용
- scenario_c -> E-01 + O-02 발화
- scenario_b -> O-01 발화
- scenario_clean -> Finding 0건 (★ 가장 중요)
- scenario_safety -> verdict BLOCK
- trace 없는 번들에서 O 규칙이 SKIPPED 처리되고 나머지는 정상 동작

주의: R-01/R-04는 R-02·E-01의 근본 원인과 같은 신호를 다른 각도에서 잡아내므로
scenario_a/scenario_c에서 R-02·E-01과 나란히 같이 발화한다. 이건 노이즈가 아니라
여러 규칙이 같은 회귀를 서로 다른 지표로 교차 확인하는, 의도한 동작이다.
"핵심 6개"(R-01, R-02, E-01, O-01, O-02, S-01/S-02) 중 그 시나리오가 겨냥하지 않은
규칙만 조용하면 된다.
"""

from __future__ import annotations

import json

import pytest

from core.detector import DetectionContext, decide_verdict, run_rules
from core.schemas.enums import Verdict
from tests.auditor._golden_utils import (
    GOLDEN_DIR,
    SCENARIO_NAMES,
    run_pipeline,
    summarize_detection,
)


def _detect(name: str):
    load_result, agg, diff = run_pipeline(name)
    ctx = DetectionContext(load_result=load_result, agg=agg, diff=diff)
    findings, skipped = run_rules(ctx)
    return findings, skipped, ctx


@pytest.mark.parametrize("name", SCENARIO_NAMES)
def test_matches_golden(name: str) -> None:
    golden_path = GOLDEN_DIR / f"p3_{name}.json"
    assert golden_path.exists(), f"골든 파일이 없습니다: {golden_path}"
    expected = json.loads(golden_path.read_text(encoding="utf-8"))

    load_result, agg, diff = run_pipeline(name)
    actual = summarize_detection(load_result, agg, diff)

    assert actual == expected


def test_scenario_clean_produces_zero_findings() -> None:
    """가장 중요한 게이트. 정상 변경에서는 Finding이 단 하나도 나오면 안 된다."""
    findings, _skipped, _ctx = _detect("scenario_clean")
    assert findings == []


def test_scenario_a_fires_r02_and_stays_quiet_on_core_rules() -> None:
    findings, skipped, _ctx = _detect("scenario_a")
    fired_ids = {f.rule_id for f in findings}

    assert "R-02" in fired_ids
    r02 = next(f for f in findings if f.rule_id == "R-02")
    assert sorted(r02.affected_testcases) == ["case_03", "case_07", "case_12", "case_15", "case_18"]

    # 핵심 6개 중 이 시나리오가 겨냥하지 않은 것들은 조용해야 한다
    assert "E-01" not in fired_ids
    assert "O-01" not in fired_ids
    assert "O-02" not in fired_ids
    assert "S-01" not in fired_ids
    assert "S-02" not in fired_ids

    # trace가 없으므로 trace 의존 규칙은 SKIPPED로 빠지고, 나머지는 정상 동작해야 한다
    skipped_ids = {s.rule_id for s in skipped}
    assert skipped_ids == {"O-01", "O-02", "E-04"}
    assert all("traces 없음" in s.reason for s in skipped if s.rule_id in {"O-01", "O-02", "E-04"})


def test_scenario_c_fires_e01_and_o02() -> None:
    findings, _skipped, _ctx = _detect("scenario_c")
    fired_ids = {f.rule_id for f in findings}

    assert "E-01" in fired_ids
    assert "O-02" in fired_ids

    o02 = next(f for f in findings if f.rule_id == "O-02")
    assert sorted(o02.affected_testcases) == ["case_02", "case_06", "case_09", "case_13", "case_17", "case_20"]
    assert o02.evidence.v1 <= 0.05  # 회복률 거의 0


def test_scenario_b_fires_o01_across_all_cases() -> None:
    findings, _skipped, _ctx = _detect("scenario_b")
    o01 = next((f for f in findings if f.rule_id == "O-01"), None)
    assert o01 is not None
    assert len(o01.affected_testcases) == 20
    assert o01.evidence.v1 == 0.0  # candidate의 verifier 개입률 0%

    # 순수 Opportunity 시나리오라 회귀 규칙은 조용해야 한다
    fired_ids = {f.rule_id for f in findings}
    assert "R-01" not in fired_ids
    assert "R-02" not in fired_ids
    assert "S-01" not in fired_ids
    assert "S-02" not in fired_ids


def test_scenario_safety_blocks() -> None:
    findings, _skipped, _ctx = _detect("scenario_safety")
    fired_ids = {f.rule_id for f in findings}
    assert "S-02" in fired_ids  # error_type이 SQL Guard 위반으로 분류됨

    verdict = decide_verdict(findings)
    assert verdict is Verdict.BLOCK


@pytest.mark.parametrize(
    ("name", "expected_verdict"),
    [
        ("scenario_clean", Verdict.PASS),
        ("scenario_a", Verdict.HOLD),
        ("scenario_c", Verdict.HOLD),
        ("scenario_b", Verdict.PASS),
        ("scenario_safety", Verdict.BLOCK),
    ],
)
def test_decide_verdict_per_scenario(name: str, expected_verdict: Verdict) -> None:
    findings, _skipped, _ctx = _detect(name)
    assert decide_verdict(findings) is expected_verdict
