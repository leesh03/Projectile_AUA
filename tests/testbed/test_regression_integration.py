from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.detector import DetectionContext, run_rules
from core.detector.verdict import decide_verdict
from core.diff.aggregate import aggregate
from core.diff.compare import compare
from core.schemas.enums import Verdict
from core.schemas.loader import load_bundle

ROOT = Path(__file__).resolve().parents[2]


def _comparison(tmp_path: Path, *extra: str) -> dict:
    output = tmp_path / "bundle.json"
    command = [
        sys.executable,
        "-B",
        "tools/run_comparison.py",
        "--limit",
        "1",
        "--trials",
        "1",
        "--no-baseline-verifier",
        "--no-candidate-verifier",
        "--bundle-out",
        str(output),
        *extra,
    ]
    environment = os.environ.copy()
    environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(output.read_text(encoding="utf-8"))


def _findings(bundle: dict) -> list:
    loaded = load_bundle(bundle)
    aggregated = aggregate(loaded)
    findings, _ = run_rules(
        DetectionContext(
            load_result=loaded,
            agg=aggregated,
            diff=compare(aggregated),
        )
    )
    return findings


def test_clean_actual_v0_v1_has_no_false_regression(tmp_path: Path) -> None:
    bundle = _comparison(
        tmp_path,
        "--baseline-max-reflections",
        "0",
        "--candidate-max-reflections",
        "0",
    )
    # One local wall-clock sample can cross E-03's 20% latency threshold due
    # to scheduler noise. That low-confidence efficiency warning belongs to a
    # repeated performance experiment, not this functional regression check.
    functional_findings = [
        finding for finding in _findings(bundle) if finding.rule_id != "E-03"
    ]
    assert functional_findings == []


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        ("sql-typo", {"task_success": False, "policy_correct": False}),
        ("wrong-policy", {"task_success": True, "policy_correct": False}),
        ("unsafe-delete", {"task_success": False, "safety_violation": True}),
    ],
)
def test_failed_candidates_still_create_official_bundles(
    tmp_path: Path,
    profile: str,
    expected: dict[str, bool],
) -> None:
    bundle = _comparison(tmp_path, "--candidate-fault-profile", profile)
    candidate = next(t for t in bundle["trials"] if t["agent_label"] == "V1")
    assert all(candidate[key] is value for key, value in expected.items())
    assert candidate["evaluation_basis"] == "GOLD"

    rule_ids = {finding.rule_id for finding in _findings(bundle)}
    if profile == "sql-typo":
        assert "R-01" in rule_ids
    if profile == "wrong-policy":
        assert "R-03" in rule_ids

    if profile == "unsafe-delete":
        assert decide_verdict(_findings(bundle)) is Verdict.BLOCK


def test_sql_repair_recovery_is_recorded_in_bundle(tmp_path: Path) -> None:
    bundle = _comparison(
        tmp_path,
        "--candidate-fault-profile",
        "sql-typo",
        "--candidate-repair",
        "--candidate-max-retries",
        "1",
    )
    candidate = next(t for t in bundle["trials"] if t["agent_label"] == "V1")
    assert candidate["task_success"] is True
    assert candidate["retry_count"] == 1
    assert any(
        trace["agent_label"] == "V1" and trace["node_role"] == "REPAIR_QUERY"
        for trace in bundle["traces"]
    )


def test_verifier_on_with_zero_reflections_differs_from_off(tmp_path: Path) -> None:
    bundle = _comparison(
        tmp_path,
        "--candidate-verifier",
        "--candidate-max-reflections",
        "0",
    )
    trials = {trial["agent_label"]: trial for trial in bundle["trials"]}
    v0 = trials["V0"]["scaffold_config"]
    v1 = trials["V1"]["scaffold_config"]
    assert v0["verifier_enabled"] is False
    assert v1["verifier_enabled"] is True
    assert v0["max_reflections"] == v1["max_reflections"] == 0
    assert any(
        trace["agent_label"] == "V1" and trace["node_role"] == "VERIFY_REASONING"
        for trace in bundle["traces"]
    )
