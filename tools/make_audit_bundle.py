"""실행 결과 두 벌(V0/V1)을 소현의 AuditBundle 하나로 묶는다.

통합 기획서 §6.6 인수인계: 이준원,유채린 -> 이소현
  전달물   AgentVersion , TraceStep , TrialResult
  수락기준 V0/V1 동일 testcase_id로 매칭 가능

준원의 runner는 케이스별 trial_*.json까지만 만들고, 소현의 loader는 합쳐진
bundle부터 읽는다. 그 사이를 잇는다.

사용:
  python tools/make_audit_bundle.py \
      --baseline reports/runs/<V0_run> \
      --candidate reports/runs/<V1_run> \
      --out reports/bundles/bundle.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from core.schemas.bundle import AuditBundle  # noqa: E402


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def collect_run(run_dir: Path) -> tuple[list[dict], list[dict], dict]:
    """한 run 폴더에서 trial과 trace를 모은다.

    구조: <run_dir>/<agent_label>/<testcase_id>/trial_<n>.json
    """
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest.json이 없습니다: {run_dir}")
    manifest = _read_json(manifest_path)

    trials: list[dict] = []
    traces: list[dict] = []
    for trial_file in sorted(run_dir.glob("*/*/trial_*.json")):
        record = _read_json(trial_file)
        trials.append(record["trial_result"])
        traces.extend(record.get("traces") or [])

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
        "retry_policy": f"max_retries={config.get('repair')}",
        "verifier_policy": f"max_reflections={config.get('verifier')}",
        "commit": version_meta.get("commit"),
    }


def make_bundle(baseline_dir: Path, candidate_dir: Path, change_note: str | None) -> dict:
    base_trials, base_traces, base_manifest = collect_run(baseline_dir)
    cand_trials, cand_traces, cand_manifest = collect_run(candidate_dir)

    base_config = base_trials[0].get("scaffold_config")
    cand_config = cand_trials[0].get("scaffold_config")
    base_meta = base_manifest.get("run_metadata", {})
    cand_meta = cand_manifest.get("run_metadata", {})
    if (
        base_config == cand_config
        and base_meta.get("mode") == cand_meta.get("mode")
        and base_meta.get("provider") == cand_meta.get("provider")
        and base_meta.get("model") == cand_meta.get("model")
        and base_meta.get("sql_strategy") == cand_meta.get("sql_strategy")
        and base_meta.get("fault_profile") == cand_meta.get("fault_profile")
    ):
        raise ValueError(
            "V0/V1 실행 조건이 같습니다. 모델 또는 Scaffold 설정을 하나 이상 변경하세요."
        )

    relabel(base_trials, "V0"), relabel(base_traces, "V0")
    relabel(cand_trials, "V1"), relabel(cand_traces, "V1")

    case_ids = sorted({t["testcase_id"] for t in base_trials})
    # 페어링되지 않은 케이스가 있으면 loader가 그 케이스를 통째로 버린다.
    cand_ids = {t["testcase_id"] for t in cand_trials}
    unpaired = sorted(set(case_ids) ^ cand_ids)
    if unpaired:
        print(f"경고: V0/V1 한쪽에만 있는 케이스 {len(unpaired)}건 - {unpaired[:5]}", file=sys.stderr)

    bundle = {
        "bundle_id": f"{base_manifest['run_id']}__{cand_manifest['run_id']}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "suite": {
            "suite_id": base_manifest.get("run_metadata", {}).get("suite", "unknown"),
            "testcase_ids": case_ids,
            "dataset_version": base_manifest.get("run_metadata", {}).get("suite", "unknown"),
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
