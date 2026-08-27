from __future__ import annotations

from datetime import UTC, datetime

from core.candidate import ALLOWED_OPERATORS, generate_candidates
from core.detector import DetectionContext, run_rules
from core.diff.aggregate import aggregate
from core.diff.compare import compare
from core.report import build_report
from core.schemas.enums import CandidateStatus, RevalidationStatus, RiskLevel
from core.schemas.finding import Candidate
from core.schemas.loader import load_bundle
from core.validation import candidate_with_result, validate_candidate
from fixtures.generator import build_scenario_b


def _validation_bundle(*, trials: int = 2, safety: bool = False, quality: bool = True) -> dict:
    records = []
    for label in ("V0", "V1"):
        for trial in range(1, trials + 1):
            records.append(
                {
                    "testcase_id": "case_01",
                    "agent_label": label,
                    "trial": trial,
                    "task_success": quality if label == "V1" else True,
                    "policy_correct": quality if label == "V1" else True,
                    "tool_error_count": 0,
                    "retry_count": 0,
                    "total_tokens": 80 if label == "V1" else 100,
                    "latency_ms": 80 if label == "V1" else 100,
                    "safety_violation": safety if label == "V1" else False,
                    "stop_reason": "OK" if quality else "PROVIDER_ERROR",
                }
            )
    version = {
        "agent_id": "policy-agent",
        "version": "v",
        "model_id": "m",
        "prompt_version": "p",
        "tool_schema_version": "t",
        "workflow_version": "w",
        "retry_policy": "r",
        "verifier_policy": "v",
    }
    return {
        "bundle_id": "revalidation",
        "created_at": datetime.now(UTC).isoformat(),
        "suite": {"suite_id": "s", "testcase_ids": ["case_01"], "dataset_version": "d"},
        "baseline": {**version, "label": "V0"},
        "candidate": {**version, "label": "V1"},
        "trials": records,
        "traces": None,
    }


def test_rule_guided_candidates_use_only_allowed_operators() -> None:
    loaded = load_bundle(build_scenario_b().model_dump(mode="json"))
    agg = aggregate(loaded)
    diff = compare(agg)
    findings, _ = run_rules(DetectionContext(load_result=loaded, agg=agg, diff=diff))
    report = build_report(
        report_id="rpt_candidates",
        load_result=loaded,
        agg=agg,
        diff=diff,
        findings=findings,
    )
    candidates = generate_candidates(report.findings)

    assert candidates
    assert all(candidate.operator in ALLOWED_OPERATORS for candidate in candidates)
    assert any(
        candidate.operator == "REMOVE" and candidate.target == "reasoning_verifier"
        for candidate in candidates
    )


def test_revalidation_passes_quality_safety_and_efficiency_gates() -> None:
    candidate = Candidate(
        candidate_id="C-01",
        operator="REMOVE",
        target="reasoning_verifier",
        addresses=["F-01"],
        change_spec="disable verifier",
        risk=RiskLevel.MEDIUM,
    )
    result = validate_candidate(candidate, load_bundle(_validation_bundle()))
    applied = candidate_with_result(candidate, result)

    assert result.status is RevalidationStatus.PASS
    assert result.quality and result.quality.ok
    assert result.safety and result.safety.ok
    assert result.efficiency and result.efficiency.improved
    assert applied.status is CandidateStatus.APPLIED


def test_revalidation_blocks_new_safety_violation() -> None:
    candidate = Candidate(
        candidate_id="C-01",
        operator="REMOVE",
        target="reasoning_verifier",
        addresses=["F-01"],
        change_spec="disable verifier",
        risk=RiskLevel.HIGH,
    )
    result = validate_candidate(candidate, load_bundle(_validation_bundle(safety=True)))

    assert result.status is RevalidationStatus.BLOCK
    assert candidate_with_result(candidate, result).status is CandidateStatus.REJECTED


def test_revalidation_accepts_deterministic_llm_call_reduction() -> None:
    bundle = _validation_bundle()
    for record in bundle["trials"]:
        record["total_tokens"] = 100
        record["latency_ms"] = 110 if record["agent_label"] == "V1" else 100
        record["llm_call_count"] = 2 if record["agent_label"] == "V1" else 3
    candidate = Candidate(
        candidate_id="C-01",
        operator="REMOVE",
        target="reasoning_verifier",
        addresses=["F-01"],
        change_spec="disable verifier",
        risk=RiskLevel.MEDIUM,
    )

    result = validate_candidate(candidate, load_bundle(bundle))

    assert result.status is RevalidationStatus.PASS
    assert result.efficiency and result.efficiency.avg_llm_call_delta == -1
    assert result.efficiency.improved


def test_revalidation_is_inconclusive_with_one_trial() -> None:
    candidate = Candidate(
        candidate_id="C-01",
        operator="REDUCE",
        target="sql_repair.max_retries",
        addresses=["F-01"],
        change_spec="reduce retry",
        risk=RiskLevel.MEDIUM,
    )
    result = validate_candidate(candidate, load_bundle(_validation_bundle(trials=1)))
    assert result.status is RevalidationStatus.INCONCLUSIVE
