"""P1-1 스키마 기본 동작 확인. 여기서 깨지면 core/schemas/ 전체를 소비하는 팀 전원이 영향받는다."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.schemas import AuditBundle, UpgradeReport, export_schemas


def _sample_bundle_dict() -> dict:
    return {
        "bundle_id": "audit_test_001",
        "created_at": "2026-08-18T10:00:00+09:00",
        "suite": {"suite_id": "s1", "testcase_ids": ["c1", "c2"], "dataset_version": "ds1"},
        "baseline": {
            "label": "V0", "agent_id": "policy_agent", "version": "v0", "model_id": "MODEL_A",
            "prompt_version": "p1", "tool_schema_version": "t1", "workflow_version": "w1",
            "retry_policy": "max_retry=2", "verifier_policy": "reflection=1",
        },
        "candidate": {
            "label": "V1", "agent_id": "policy_agent", "version": "v1", "model_id": "MODEL_B",
            "prompt_version": "p2", "tool_schema_version": "t1", "workflow_version": "w1",
            "retry_policy": "max_retry=5", "verifier_policy": "reflection=1",
        },
        "trials": [
            {
                "testcase_id": "c1", "agent_label": "V0", "trial": 1,
                "task_success": True, "policy_correct": True, "tool_error_count": 0,
                "retry_count": 0, "total_tokens": 100, "latency_ms": 200,
                "safety_violation": False, "stop_reason": "OK",
            },
        ],
    }


def test_audit_bundle_round_trip() -> None:
    bundle = AuditBundle.model_validate(_sample_bundle_dict())
    dumped = bundle.model_dump(mode="json")
    reloaded = AuditBundle.model_validate(dumped)
    assert reloaded == bundle


def test_audit_bundle_rejects_duplicate_labels() -> None:
    data = _sample_bundle_dict()
    data["candidate"]["label"] = "V0"  # baseline과 동일 -> 구분 불가
    with pytest.raises(ValidationError, match="label"):
        AuditBundle.model_validate(data)


def test_audit_bundle_rejects_trial_with_unknown_label() -> None:
    data = _sample_bundle_dict()
    data["trials"][0]["agent_label"] = "V9"
    with pytest.raises(ValidationError, match="V9"):
        AuditBundle.model_validate(data)


def test_export_schemas_returns_both_top_level_models() -> None:
    schemas = export_schemas()
    assert set(schemas.keys()) == {"AuditBundle", "UpgradeReport"}
    assert schemas["AuditBundle"]["title"] == "AuditBundle"
    assert schemas["UpgradeReport"]["title"] == "UpgradeReport"


def test_upgrade_report_minimal() -> None:
    report = UpgradeReport.model_validate(
        {
            "report_id": "rpt_1",
            "bundle_id": "audit_test_001",
            "verdict": "PASS",
            "generated_at": "2026-08-18T10:05:00+09:00",
            "summary": {
                "testcase_count": 1,
                "trials_per_case": 1,
                "success_rate": {"v0": 1.0, "v1": 1.0},
                "tool_error_rate": {"v0": 0.0, "v1": 0.0},
                "avg_retry": {"v0": 0.0, "v1": 0.0},
                "avg_tokens": {"v0": 100.0, "v1": 100.0},
                "avg_latency_ms": {"v0": 200.0, "v1": 200.0},
                "safety_violation": {"v0": 0.0, "v1": 0.0},
            },
        }
    )
    assert report.findings == []
    assert report.candidates == []
