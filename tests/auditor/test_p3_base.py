"""P3-3 오탐 방지 장치 단위 테스트.

6개 시나리오 픽스처는 전부 testcase당 trial 2회로 만들어져 있어서 저신뢰 강등 경로를
자연히 통과하지 않는다. 그래서 이 경로만 별도의 작은 합성 데이터로 직접 검증한다.
"""

from __future__ import annotations

from core.detector.base import DetectionContext, _check_requirement, _demote_if_low_confidence
from core.diff.aggregate import aggregate
from core.diff.compare import compare
from core.schemas.enums import FindingType, Severity
from core.schemas.finding import Evidence, Finding
from core.schemas.loader import load_bundle


def _single_case_low_trial_bundle() -> dict:
    """testcase 1개, V1은 trial 1건뿐 (V0는 2건) -> 이 케이스의 V1 trial_count는 1."""
    return {
        "bundle_id": "audit_test_lowconf",
        "created_at": "2026-08-18T10:00:00+09:00",
        "suite": {"suite_id": "s1", "testcase_ids": ["c1"], "dataset_version": "ds1"},
        "baseline": {
            "label": "V0", "agent_id": "a", "version": "v0", "model_id": "m",
            "prompt_version": "p1", "tool_schema_version": "t1", "workflow_version": "w1",
            "retry_policy": "r", "verifier_policy": "v",
        },
        "candidate": {
            "label": "V1", "agent_id": "a", "version": "v1", "model_id": "m",
            "prompt_version": "p2", "tool_schema_version": "t1", "workflow_version": "w1",
            "retry_policy": "r", "verifier_policy": "v",
        },
        "trials": [
            {
                "testcase_id": "c1", "agent_label": "V0", "trial": 1, "task_success": True,
                "policy_correct": True, "tool_error_count": 0, "retry_count": 0,
                "total_tokens": 100, "latency_ms": 100, "safety_violation": False, "stop_reason": "OK",
            },
            {
                "testcase_id": "c1", "agent_label": "V0", "trial": 2, "task_success": True,
                "policy_correct": True, "tool_error_count": 0, "retry_count": 0,
                "total_tokens": 100, "latency_ms": 100, "safety_violation": False, "stop_reason": "OK",
            },
            {
                "testcase_id": "c1", "agent_label": "V1", "trial": 1, "task_success": False,
                "policy_correct": True, "tool_error_count": 0, "retry_count": 0,
                "total_tokens": 100, "latency_ms": 100, "safety_violation": False, "stop_reason": "OK",
            },
        ],
    }


def _ctx() -> DetectionContext:
    load_result = load_bundle(_single_case_low_trial_bundle())
    agg = aggregate(load_result)
    diff = compare(agg)
    return DetectionContext(load_result=load_result, agg=agg, diff=diff)


def test_low_trial_single_case_finding_gets_demoted_to_inconclusive() -> None:
    ctx = _ctx()
    assert ctx.load_result.low_confidence is True

    finding = Finding(
        finding_id="F-TEST",
        type=FindingType.REGRESSION,
        severity=Severity.P0,
        rule_id="R-01",
        title="test",
        affected_testcases=["c1"],
        evidence=Evidence(metric="success_rate", v0=1.0, v1=0.0, delta_pp=-100.0),
    )

    demoted = _demote_if_low_confidence(ctx, finding)
    assert demoted.type is FindingType.INCONCLUSIVE
    assert demoted.low_confidence is True


def test_all_affected_cases_require_both_sides_to_have_enough_trials() -> None:
    ctx = _ctx()
    finding = Finding(
        finding_id="F-TEST",
        type=FindingType.REGRESSION,
        severity=Severity.P0,
        rule_id="R-01",
        title="test",
        affected_testcases=["c1", "c2"],  # 2건 이상이면 강등 조건에 안 걸림
        evidence=Evidence(metric="success_rate", v0=1.0, v1=0.0, delta_pp=-100.0),
    )
    result = _demote_if_low_confidence(ctx, finding)
    assert result.type is FindingType.INCONCLUSIVE
    assert result.low_confidence is True


def test_check_requirement_trace_missing() -> None:
    ctx = _ctx()
    assert ctx.has_trace is False
    assert _check_requirement(ctx, "trace") == "traces 없음"


def test_check_requirement_unknown_field_passes_through() -> None:
    ctx = _ctx()
    assert _check_requirement(ctx, "task_success") is None
