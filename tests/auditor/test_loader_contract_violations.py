"""loader.py가 docs/CONTRACT.md §6 "계약 위반 처리" 표대로 동작하는지 검증한다.

fixtures/bundles/scenario_broken.json은 일부러 깨뜨린 픽스처다:
- case_19, case_20은 V1 쪽 trial이 아예 없음 (페어링 실패 -> UNPAIRED)
- case_05 trial 1의 V1 레코드는 stop_reason 필드가 빠져 있음 (필수 필드 누락 -> SKIPPED)

강한 요구사항: 이 파일을 로드해도 예외 없이 LoadResult가 나와야 한다.
"""

from __future__ import annotations

from pathlib import Path

from core.schemas.loader import load_bundle

BROKEN_BUNDLE = Path(__file__).resolve().parents[2] / "fixtures" / "bundles" / "scenario_broken.json"


def test_broken_bundle_loads_without_raising() -> None:
    result = load_bundle(BROKEN_BUNDLE)  # 던지면 이 테스트가 바로 실패한다
    assert result.bundle_id == "audit_mock_scenario_broken"


def test_unpaired_testcases_are_separated_not_dropped_silently() -> None:
    result = load_bundle(BROKEN_BUNDLE)
    assert result.unpaired_testcases == ["case_19", "case_20"]
    # 페어링 안 된 testcase는 trials에서 완전히 빠져야 한다 (비교 대상에서 제외)
    remaining_ids = {t.testcase_id for t in result.trials}
    assert "case_19" not in remaining_ids
    assert "case_20" not in remaining_ids


def test_missing_required_field_skips_only_that_record() -> None:
    result = load_bundle(BROKEN_BUNDLE)

    assert len(result.skipped_trials) == 1
    skipped = result.skipped_trials[0]
    assert skipped.testcase_id == "case_05"
    assert skipped.agent_label == "V1"
    assert "stop_reason" in skipped.reason

    # case_05는 V0 trial 2건 + V1 trial 1건(trial 2)만 남아야 한다 -> trial 수 불균형
    case_05_trials = [t for t in result.trials if t.testcase_id == "case_05"]
    assert len(case_05_trials) == 2
    v1_trials = [t for t in case_05_trials if t.agent_label == "V1"]
    assert len(v1_trials) == 1
    assert v1_trials[0].trial == 2
    assert "case_05:trial-1" in result.unpaired_trials


def test_low_confidence_flagged_when_any_pair_has_under_two_trials() -> None:
    result = load_bundle(BROKEN_BUNDLE)
    assert result.low_confidence is True


def test_paired_testcase_count_excludes_unpaired() -> None:
    result = load_bundle(BROKEN_BUNDLE)
    assert result.testcase_count == 18  # 20 - 2(unpaired)
