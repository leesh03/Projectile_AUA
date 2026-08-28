"""Subprocess entry point that runs Agent trials without evaluator assets."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agents.policy_agent.nodes.state import AgentRequest
from policy_runtime.access_guard import agent_execution_guard
from policy_runtime.factory import build_agent


def _read_request() -> dict[str, Any]:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise ValueError("isolated worker input must be JSON") from exc
    if not isinstance(payload, dict):
        raise TypeError("isolated worker input must be an object")
    return payload


def _require_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"isolated worker field must be a non-empty string: {key}")
    return value


def main() -> int:
    payload = _read_request()
    root = Path(_require_string(payload, "project_root")).resolve()
    blocked_roots_raw = payload.get("blocked_roots", [])
    if not isinstance(blocked_roots_raw, list) or not all(
        isinstance(item, str) and item for item in blocked_roots_raw
    ):
        raise TypeError("isolated worker blocked_roots must be an array of paths")
    blocked_roots = tuple(Path(item).resolve() for item in blocked_roots_raw)
    output_root = Path(_require_string(payload, "output_root")).resolve()
    run_id = _require_string(payload, "run_id")
    mode = _require_string(payload, "mode")
    provider = _require_string(payload, "provider")
    agent_label = _require_string(payload, "agent_label")
    isolation = _require_string(payload, "isolation")
    if isolation not in {"staged-subprocess-audit-v2", "container-hardened-v1"}:
        raise ValueError("isolated worker received an unsupported isolation mode")
    model_raw = payload.get("model")
    model = model_raw if isinstance(model_raw, str) and model_raw else None
    db_path_raw = payload.get("db_path")
    db_path = Path(db_path_raw).resolve() if isinstance(db_path_raw, str) else None
    scaffold_overrides = payload.get("scaffold_overrides")
    if not isinstance(scaffold_overrides, Mapping):
        raise TypeError("isolated worker scaffold_overrides must be an object")
    version_metadata = payload.get("version_metadata")
    if not isinstance(version_metadata, Mapping):
        raise TypeError("isolated worker version_metadata must be an object")
    structured_output_retries = payload.get("structured_output_retries")
    if not isinstance(structured_output_retries, int):
        raise TypeError("isolated worker structured_output_retries must be an integer")
    sql_strategy = _require_string(payload, "sql_strategy")
    fault_profile_raw = payload.get("fault_profile")
    fault_profile = (
        fault_profile_raw
        if isinstance(fault_profile_raw, str) and fault_profile_raw
        else None
    )
    experiment_provenance = payload.get("experiment_provenance")
    if not isinstance(experiment_provenance, Mapping):
        raise TypeError("isolated worker experiment_provenance must be an object")
    jobs = payload.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("isolated worker jobs must be a non-empty array")

    records: list[dict[str, Any]] = []
    with agent_execution_guard(root, blocked_roots=blocked_roots):
        bundle = build_agent(
            root,
            mode=mode,
            provider=provider,
            model=model,
            db_path=db_path,
            agent_label=agent_label,
            scaffold_overrides=scaffold_overrides,
            version_metadata=version_metadata,
            structured_output_retries=structured_output_retries,
            sql_strategy=sql_strategy,
            fault_profile=fault_profile,
        )
        for job in jobs:
            if not isinstance(job, Mapping):
                raise TypeError("isolated worker job must be an object")
            raw_case = job.get("case")
            trial = job.get("trial")
            if not isinstance(raw_case, Mapping) or not isinstance(trial, int):
                raise TypeError("isolated worker job requires case and integer trial")
            request = AgentRequest.from_mapping(raw_case)
            run = bundle.graph.run(
                request,
                agent_label=bundle.agent_label,
                trial=trial,
                run_id=run_id,
                run_metadata={
                    "experiment": dict(experiment_provenance),
                    "mode": mode,
                    "provider": bundle.provider,
                    "model": bundle.model,
                    "planner": False,
                    "isolation": isolation,
                    "agent_version": dict(bundle.version_metadata),
                    "runtime": dict(bundle.runtime_metadata),
                    "sql_strategy": bundle.sql_strategy,
                    "fault_profile": bundle.fault_profile,
                },
            )
            # The worker cannot compute policy_correct because that would cross
            # the evaluator boundary. The parent patches this placeholder after
            # evaluating the returned facts outside the Agent process.
            artifact = run.state.write_trial_artifact(
                output_root,
                policy_correct=False,
            )
            records.append(
                {
                    "testcase_id": request.testcase_id,
                    "trial": trial,
                    "task_success": run.state.task_success,
                    "decision": run.state.decision,
                    "clauses": list(run.state.policy_clauses),
                    "response": run.state.response,
                    "verifier_status": run.state.verifier_status,
                    "stop_reason": run.state.stop_reason,
                    "error_type": run.state.error_type,
                    "error_message": run.state.error_message,
                    "structured_output_retry_count": (
                        run.state.structured_output_retry_count
                    ),
                    "facts": run.state.facts,
                    "artifact": str(artifact.relative_to(output_root / run_id)),
                }
            )

    json.dump(
        {"schema": "isolated-agent-result-v1", "records": records},
        sys.stdout,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
