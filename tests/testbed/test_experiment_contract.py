from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from agents.policy_agent.nodes.state import AgentConfig
from core.ingest.collect import make_bundle


def _hash_json(value: Any) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _experiment() -> dict[str, Any]:
    testcase_ids = ["E-001"]
    return {
        "suite_id": "suite-v0.5",
        "dataset_version": "testcase-v0.5:abc123",
        "dataset_manifest_sha256": "a" * 64,
        "agent_cases_sha256": "b" * 64,
        "gold_sha256": "c" * 64,
        "gold_version": "gold-v0.5",
        "executed_testcase_ids": testcase_ids,
        "testcase_ids_sha256": _hash_json(testcase_ids),
        "evaluation_context_sha256": "d" * 64,
        "evaluation_date": "2026-08-15",
        "timezone": "Asia/Seoul",
        "tool_schema_version": "sqlite-select-v1",
        "trial_contract_version": "trial-result-v2",
    }


def _write_run(
    root: Path,
    label: str,
    *,
    trial_numbers: tuple[int, ...] = (1,),
    task_success: bool = True,
    policy_correct: bool = True,
) -> Path:
    run_id = f"run-{label.lower()}"
    manifest = {
        "run_id": run_id,
        "run_metadata": {
            "experiment": _experiment(),
            "mode": "deterministic",
            "provider": "deterministic",
            "model": None,
            "sql_strategy": "canonical",
            "fault_profile": None,
            "agent_version": {
                "version": label.lower(),
                "prompt_version": "p1",
                "tool_schema_version": "sqlite-select-v1",
                "workflow_version": "policy-graph-v1",
            },
        },
        "artifacts": {
            "database": {"filename": "shop.db", "sha256": "e" * 64},
            "policy": {
                "filename": "policy_rules.json",
                "version": "policy-v0.5",
                "sha256": "f" * 64,
            },
        },
        "agents": {},
    }
    root.mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for number in trial_numbers:
        artifact_dir = root / label / "E-001"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        trial = {
            "testcase_id": "E-001",
            "agent_label": label,
            "trial": number,
            "task_success": task_success,
            "policy_correct": policy_correct,
            "evaluation_basis": "GOLD",
            "engine_consistency": task_success,
            "gold_agreement": policy_correct,
            "tool_error_count": 0 if task_success else 1,
            "retry_count": 0,
            "total_tokens": 0,
            "latency_ms": 1,
            "safety_violation": False,
            "stop_reason": "OK" if task_success else "SQL_FAILURE",
            "error_type": None if task_success else "SQLITE_OPERATIONAL_ERROR",
            "tool_schema_valid": True,
            "llm_call_count": 0,
            "scaffold_config": AgentConfig().as_scaffold_config(),
            "difficulty": "EASY",
        }
        trace = {
            "testcase_id": "E-001",
            "agent_label": label,
            "run_id": run_id,
            "trial": number,
            "step_index": 0,
            "node_role": "RETRIEVE_SCHEMA",
            "type": "code",
            "outcome": "ok",
            "tool_name": None,
            "arguments_valid": None,
            "error_type": None,
            "iteration": None,
            "input_tokens": None,
            "output_tokens": None,
            "latency_ms": 0,
        }
        payload = {"trial_result": trial, "traces": [trace]}
        (artifact_dir / f"trial_{number}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
    return root


def _pair(tmp_path: Path) -> tuple[Path, Path]:
    return _write_run(tmp_path / "base", "V0"), _write_run(tmp_path / "candidate", "V1")


def _mutate_manifest(run_dir: Path, mutation: Any) -> None:
    path = run_dir / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    mutation(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")


def test_clean_identical_v0_v1_is_a_valid_experiment(tmp_path: Path) -> None:
    baseline, candidate = _pair(tmp_path)
    bundle = make_bundle(baseline, candidate, "clean")
    assert bundle["suite"]["database_sha256"] == "e" * 64
    assert len(bundle["trials"]) == 2


def test_failed_candidate_is_collectable(tmp_path: Path) -> None:
    baseline = _write_run(tmp_path / "base", "V0")
    candidate = _write_run(
        tmp_path / "candidate",
        "V1",
        task_success=False,
        policy_correct=False,
    )
    bundle = make_bundle(baseline, candidate, "regression")
    failed = next(t for t in bundle["trials"] if t["agent_label"] == "V1")
    assert failed["task_success"] is False
    assert failed["policy_correct"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        lambda m: m["artifacts"]["database"].update(sha256="0" * 64),
        lambda m: m["artifacts"]["policy"].update(sha256="0" * 64),
        lambda m: m["run_metadata"]["experiment"].update(gold_sha256="0" * 64),
        lambda m: m["run_metadata"]["experiment"].update(agent_cases_sha256="0" * 64),
        lambda m: m["run_metadata"]["experiment"].update(
            evaluation_context_sha256="0" * 64
        ),
    ],
)
def test_provenance_mismatch_is_rejected(tmp_path: Path, mutation: Any) -> None:
    baseline, candidate = _pair(tmp_path)
    _mutate_manifest(candidate, mutation)
    with pytest.raises(ValueError, match="provenance mismatch"):
        make_bundle(baseline, candidate, "dirty")


def test_strict_trial_pairing_rejects_unequal_sets(tmp_path: Path) -> None:
    baseline = _write_run(tmp_path / "base", "V0", trial_numbers=(1, 2))
    candidate = _write_run(tmp_path / "candidate", "V1", trial_numbers=(1,))
    with pytest.raises(ValueError, match="sets differ"):
        make_bundle(baseline, candidate, "unpaired")


def test_duplicate_trial_key_is_rejected(tmp_path: Path) -> None:
    baseline, candidate = _pair(tmp_path)
    source = json.loads((candidate / "V1" / "E-001" / "trial_1.json").read_text())
    duplicate = candidate / "duplicate" / "E-001"
    duplicate.mkdir(parents=True)
    (duplicate / "trial_1.json").write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate trial key"):
        make_bundle(baseline, candidate, "duplicate")


def test_orphan_trace_is_rejected(tmp_path: Path) -> None:
    baseline, candidate = _pair(tmp_path)
    path = candidate / "V1" / "E-001" / "trial_1.json"
    payload = json.loads(path.read_text())
    payload["traces"][0]["trial"] = 2
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="references no TrialResult"):
        make_bundle(baseline, candidate, "orphan")


def test_goldless_trial_is_not_an_official_accuracy_input(tmp_path: Path) -> None:
    baseline, candidate = _pair(tmp_path)
    path = candidate / "V1" / "E-001" / "trial_1.json"
    payload = json.loads(path.read_text())
    payload["trial_result"].update(
        evaluation_basis="ENGINE_ONLY",
        gold_agreement=None,
        policy_correct=False,
    )
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="requires Gold evaluation"):
        make_bundle(baseline, candidate, "goldless")


def test_scaffold_enable_flags_are_distinct_from_limits() -> None:
    disabled = AgentConfig(enable_verifier=False, max_reflections=0).as_scaffold_config()
    enabled = AgentConfig(enable_verifier=True, max_reflections=0).as_scaffold_config()
    assert disabled["verifier_enabled"] is False
    assert enabled["verifier_enabled"] is True
    assert disabled["max_reflections"] == enabled["max_reflections"] == 0

