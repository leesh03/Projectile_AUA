"""실행 결과 두 벌(V0/V1)을 소현의 AuditBundle 하나로 묶는다.

통합 기획서 §6.6 인수인계: 이준원,유채린 -> 이소현
  전달물   AgentVersion , TraceStep , TrialResult
  수락기준 V0/V1 동일 testcase_id로 매칭 가능

Testbed의 runner는 케이스별 trial_*.json까지만 만들고, Auditor의 loader는
합쳐진 bundle부터 읽는다. 그 사이를 잇는다 — 스키마를 소유한 Auditor 쪽 책임이다.

사용:
  python -m core.ingest.collect \
      --baseline reports/runs/<V0_run> \
      --candidate reports/runs/<V1_run> \
      --out reports/bundles/bundle.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from core.ingest.mapper import to_trace_steps, to_trial_result
from core.schemas.bundle import AuditBundle


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _require_mapping(value: Any, *, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be an object")
    return value


def collect_run(run_dir: Path) -> tuple[list[dict], list[dict], dict]:
    """한 run 폴더에서 에이전트 로그를 모아 Auditor 계약으로 옮긴다.

    구조: <run_dir>/<agent_label>/<testcase_id>/trial_<n>.json

    대상 에이전트는 자기 어휘로 로그를 남길 뿐이다. 그 로그가 TrialResult ·
    TraceStep 계약을 만족하는지 검증하는 것은 여기(Auditor)의 책임이다.
    """
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest.json이 없습니다: {run_dir}")
    manifest = _read_json(manifest_path)

    trials: list[dict] = []
    traces: list[dict] = []
    for trial_file in sorted(run_dir.glob("*/*/trial_*.json")):
        record = _read_json(trial_file)
        trial_result = record["trial_result"]
        provider_calls = record.get("provider_calls") or []
        if not isinstance(provider_calls, list):
            raise TypeError(f"provider_calls must be an array: {trial_file}")
        provider_tokens = 0
        for call in provider_calls:
            usage = call.get("usage") if isinstance(call, dict) else None
            if not isinstance(usage, dict):
                raise TypeError(f"provider call usage must be an object: {trial_file}")
            provider_tokens += int(usage.get("input_tokens") or 0)
            provider_tokens += int(usage.get("output_tokens") or 0)
        if provider_tokens != trial_result.get("total_tokens"):
            raise ValueError(f"provider usage does not match total_tokens: {trial_file}")
        if len(provider_calls) != trial_result.get("llm_call_count"):
            raise ValueError(f"provider call count does not match llm_call_count: {trial_file}")
        trials.append(to_trial_result(trial_result))
        traces.extend(to_trace_steps(record.get("traces") or []))

    if not trials:
        raise ValueError(f"trial 파일을 찾지 못했습니다: {run_dir}")
    return trials, traces, manifest


def relabel(records: list[dict], label: str) -> list[dict]:
    """agent_label을 bundle의 baseline/candidate 라벨로 통일한다.

    같은 라벨이 양쪽에 오면 loader가 ContractViolation을 던진다.
    """
    for record in records:
        record["agent_label"] = label
    return records


def build_agent_version(label: str, manifest: dict, trials: list[dict]) -> dict:
    """manifest와 trial의 scaffold_config에서 AgentVersion을 만든다."""
    meta = manifest.get("run_metadata", {})
    version_meta = meta.get("agent_version", {})
    if not isinstance(version_meta, dict):
        version_meta = {}
    config = trials[0].get("scaffold_config", {})
    return {
        "label": label,
        "agent_id": "order-refund-policy-agent",
        "version": version_meta.get("version") or label,
        "model_id": meta.get("model") or meta.get("provider") or "unknown",
        "prompt_version": version_meta.get("prompt_version") or "unknown",
        "tool_schema_version": version_meta.get("tool_schema_version") or "sqlite-select-v1",
        "workflow_version": version_meta.get("workflow_version") or f"planner={config.get('planner')}",
        # 실험 독립변수. Auditor가 retry/verifier 축소를 판단하는 근거가 된다.
        "retry_policy": (
            f"enabled={bool(config.get('repair_enabled', config.get('repair', 0)))};"
            f"max_retries={config.get('max_retries', config.get('repair', 0))}"
        ),
        "verifier_policy": (
            f"enabled={bool(config.get('verifier_enabled', config.get('verifier', 0)))};"
            f"max_reflections={config.get('max_reflections', config.get('verifier', 0))};"
            f"policy={config.get('reflection_policy', 'legacy')}"
        ),
        "commit": version_meta.get("commit"),
    }


def _experiment(manifest: dict[str, Any], *, side: str) -> dict[str, Any]:
    metadata = _require_mapping(manifest.get("run_metadata"), name=f"{side} run_metadata")
    experiment = _require_mapping(metadata.get("experiment"), name=f"{side} experiment")
    required = {
        "suite_id",
        "dataset_version",
        "dataset_manifest_sha256",
        "agent_cases_sha256",
        "gold_sha256",
        "gold_version",
        "executed_testcase_ids",
        "testcase_ids_sha256",
        "evaluation_context_sha256",
        "evaluation_date",
        "timezone",
        "tool_schema_version",
        "trial_contract_version",
    }
    missing = sorted(key for key in required if experiment.get(key) in (None, ""))
    if missing:
        raise ValueError(f"{side} experiment provenance is incomplete: {missing}")
    testcase_ids = experiment["executed_testcase_ids"]
    if not isinstance(testcase_ids, list) or not testcase_ids:
        raise ValueError(f"{side} executed_testcase_ids must be a non-empty array")
    if experiment["testcase_ids_sha256"] != _sha256_json(testcase_ids):
        raise ValueError(f"{side} testcase_ids_sha256 does not match executed_testcase_ids")
    return experiment


def _artifact_contract(manifest: dict[str, Any], *, side: str) -> dict[str, Any]:
    artifacts = _require_mapping(manifest.get("artifacts"), name=f"{side} artifacts")
    database = _require_mapping(artifacts.get("database"), name=f"{side} database artifact")
    policy = _require_mapping(artifacts.get("policy"), name=f"{side} policy artifact")
    result = {
        "database.sha256": database.get("sha256"),
        "policy.sha256": policy.get("sha256"),
        "policy.version": policy.get("version"),
    }
    missing = sorted(key for key, value in result.items() if value in (None, ""))
    if missing:
        raise ValueError(f"{side} artifact provenance is incomplete: {missing}")
    return result


def _validate_same_provenance(
    base_manifest: dict[str, Any],
    cand_manifest: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    base_artifacts = _artifact_contract(base_manifest, side="V0")
    cand_artifacts = _artifact_contract(cand_manifest, side="V1")
    base_experiment = _experiment(base_manifest, side="V0")
    cand_experiment = _experiment(cand_manifest, side="V1")
    comparisons = {
        **base_artifacts,
        **{
            key: base_experiment[key]
            for key in (
                "suite_id",
                "dataset_version",
                "dataset_manifest_sha256",
                "agent_cases_sha256",
                "gold_sha256",
                "gold_version",
                "executed_testcase_ids",
                "testcase_ids_sha256",
                "evaluation_context_sha256",
                "evaluation_date",
                "timezone",
                "tool_schema_version",
                "trial_contract_version",
            )
        },
    }
    candidate_values = {
        **cand_artifacts,
        **{key: cand_experiment[key] for key in comparisons if key not in cand_artifacts},
    }
    mismatches = [key for key, value in comparisons.items() if candidate_values.get(key) != value]
    if mismatches:
        raise ValueError(f"V0/V1 experiment provenance mismatch: {sorted(mismatches)}")
    return base_experiment, base_artifacts


def _validate_trials(trials: list[dict[str, Any]], *, side: str) -> set[tuple[str, int]]:
    keys: set[tuple[str, int]] = set()
    numbers_by_case: dict[str, set[int]] = defaultdict(set)
    for index, trial in enumerate(trials):
        testcase_id = trial.get("testcase_id")
        trial_number = trial.get("trial")
        if not isinstance(testcase_id, str) or not isinstance(trial_number, int):
            raise TypeError(f"{side} trial {index} has an invalid pairing key")
        key = (testcase_id, trial_number)
        if key in keys:
            raise ValueError(f"{side} has a duplicate trial key: {key}")
        if trial.get("evaluation_basis") != "GOLD" or trial.get("gold_agreement") is None:
            raise ValueError(f"{side} official Bundle requires Gold evaluation: {key}")
        if bool(trial.get("policy_correct")) != bool(trial.get("gold_agreement")):
            raise ValueError(f"{side} policy_correct does not equal Gold agreement: {key}")
        keys.add(key)
        numbers_by_case[testcase_id].add(trial_number)
    for testcase_id, numbers in numbers_by_case.items():
        expected = set(range(1, max(numbers) + 1))
        if numbers != expected:
            raise ValueError(
                f"{side} trial numbers contain a gap for {testcase_id}: {sorted(numbers)}"
            )
    return keys


def _validate_traces(
    traces: list[dict[str, Any]],
    trials: list[dict[str, Any]],
    manifest: dict[str, Any],
    *,
    side: str,
) -> None:
    trial_by_key = {(trial["testcase_id"], trial["trial"]): trial for trial in trials}
    steps: dict[tuple[str, int], list[int]] = defaultdict(list)
    llm_counts: dict[tuple[str, int], int] = defaultdict(int)
    repair_counts: dict[tuple[str, int], int] = defaultdict(int)
    token_counts: dict[tuple[str, int], int] = defaultdict(int)
    run_id = manifest.get("run_id")
    seen_steps: set[tuple[str, int, int]] = set()
    for index, trace in enumerate(traces):
        testcase_id = trace.get("testcase_id")
        trial_number = trace.get("trial")
        step_index = trace.get("step_index")
        key = (testcase_id, trial_number)
        if key not in trial_by_key:
            raise ValueError(f"{side} trace {index} references no TrialResult: {key}")
        if trace.get("run_id") != run_id:
            raise ValueError(f"{side} trace {index} has a different run_id")
        if not isinstance(step_index, int):
            raise TypeError(f"{side} trace {index} has an invalid step_index")
        step_key = (testcase_id, trial_number, step_index)
        if step_key in seen_steps:
            raise ValueError(f"{side} has a duplicate trace step: {step_key}")
        seen_steps.add(step_key)
        steps[key].append(step_index)
        if trace.get("type") == "llm_call":
            llm_counts[key] += 1
        if trace.get("node_role") == "REPAIR_QUERY":
            repair_counts[key] += 1
        token_counts[key] += int(trace.get("input_tokens") or 0)
        token_counts[key] += int(trace.get("output_tokens") or 0)
    for key, trial in trial_by_key.items():
        indexes = steps.get(key, [])
        if indexes != list(range(len(indexes))):
            raise ValueError(f"{side} trace step_index is not contiguous for {key}: {indexes}")
        expected_llm = trial.get("llm_call_count")
        if expected_llm is not None and llm_counts[key] != expected_llm:
            raise ValueError(f"{side} llm_call_count does not match traces for {key}")
        if repair_counts[key] != trial.get("retry_count"):
            raise ValueError(f"{side} retry_count does not match traces for {key}")
        if token_counts[key] != trial.get("total_tokens"):
            raise ValueError(f"{side} total_tokens does not match traces for {key}")


def make_bundle(baseline_dir: Path, candidate_dir: Path, change_note: str | None) -> dict:
    base_trials, base_traces, base_manifest = collect_run(baseline_dir)
    cand_trials, cand_traces, cand_manifest = collect_run(candidate_dir)

    experiment, artifacts = _validate_same_provenance(base_manifest, cand_manifest)
    base_keys = _validate_trials(base_trials, side="V0")
    cand_keys = _validate_trials(cand_trials, side="V1")
    if base_keys != cand_keys:
        missing_v0 = sorted(cand_keys - base_keys)
        missing_v1 = sorted(base_keys - cand_keys)
        raise ValueError(
            "V0/V1 (testcase_id, trial) sets differ: "
            f"missing_in_v0={missing_v0[:5]}, missing_in_v1={missing_v1[:5]}"
        )
    _validate_traces(base_traces, base_trials, base_manifest, side="V0")
    _validate_traces(cand_traces, cand_trials, cand_manifest, side="V1")

    relabel(base_trials, "V0"), relabel(base_traces, "V0")
    relabel(cand_trials, "V1"), relabel(cand_traces, "V1")

    case_ids = sorted({testcase_id for testcase_id, _ in base_keys})
    expected_case_ids = experiment["executed_testcase_ids"]
    if case_ids != sorted(expected_case_ids) or len(case_ids) != len(expected_case_ids):
        raise ValueError("suite executed_testcase_ids does not match actual TrialResults")

    bundle = {
        "bundle_id": f"{base_manifest['run_id']}__{cand_manifest['run_id']}",
        "created_at": datetime.now(UTC).isoformat(),
        "suite": {
            "suite_id": experiment["suite_id"],
            "testcase_ids": case_ids,
            "dataset_version": experiment["dataset_version"],
            "dataset_manifest_sha256": experiment["dataset_manifest_sha256"],
            "agent_cases_sha256": experiment["agent_cases_sha256"],
            "database_sha256": artifacts["database.sha256"],
            "policy_sha256": artifacts["policy.sha256"],
            "policy_version": artifacts["policy.version"],
            "gold_sha256": experiment["gold_sha256"],
            "gold_version": experiment["gold_version"],
            "testcase_ids_sha256": experiment["testcase_ids_sha256"],
            "evaluation_context_sha256": experiment["evaluation_context_sha256"],
            "tool_schema_version": experiment["tool_schema_version"],
            "trial_contract_version": experiment["trial_contract_version"],
        },
        "baseline": build_agent_version("V0", base_manifest, base_trials),
        "candidate": build_agent_version("V1", cand_manifest, cand_trials),
        "change_note": change_note,
        "trials": base_trials + cand_trials,
        "traces": base_traces + cand_traces,
    }

    # 여기서 검증해야 소현 쪽에서 ContractViolation으로 되돌아오지 않는다.
    AuditBundle.model_validate(bundle)
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True, help="V0 run 폴더")
    parser.add_argument("--candidate", type=Path, required=True, help="V1 run 폴더")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--change-note", default=None)
    args = parser.parse_args()

    bundle = make_bundle(args.baseline, args.candidate, args.change_note)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"bundle: {args.out}")
    print(f"  cases  {len(bundle['suite']['testcase_ids'])}")
    print(f"  trials {len(bundle['trials'])}  traces {len(bundle['traces'])}")
    print(f"  V0 {bundle['baseline']['retry_policy']} / {bundle['baseline']['verifier_policy']}")
    print(f"  V1 {bundle['candidate']['retry_policy']} / {bundle['candidate']['verifier_policy']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
