"""Run two independent Testbed versions and build one validated AuditBundle.

The default experiment isolates one axis:

    V0: deterministic model + Reasoning Verifier OFF
    V1: deterministic model + Reasoning Verifier ON

Use explicit per-version flags to compare models or Repair/Reflection limits.
The two suites always run independently; labels are never applied to the same
artifact set.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.make_audit_bundle import make_bundle


def _json_from_output(output: str) -> dict[str, Any]:
    start = output.find("{")
    end = output.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError(f"Testbed output did not contain JSON: {output[-500:]}")
    value = json.loads(output[start : end + 1])
    if not isinstance(value, dict):
        raise TypeError("Testbed summary must be a JSON object")
    return value


def _run_version(
    *,
    label: str,
    mode: str,
    provider: str,
    model: str | None,
    sql_strategy: str,
    fault_profile: str | None,
    repair: bool,
    max_retries: int,
    verifier: bool,
    max_reflections: int,
    trials: int,
    limit: int | None,
) -> dict[str, Any]:
    command = [
        sys.executable,
        "-B",
        "run_agent.py",
        "run-suite",
        "--mode",
        mode,
        "--provider",
        provider,
        "--agent-label",
        label,
        "--agent-version",
        label.lower(),
        "--sql-strategy",
        sql_strategy,
        "--trials",
        str(trials),
        "--max-retries",
        str(max_retries),
        "--max-reflections",
        str(max_reflections),
        "--repair" if repair else "--no-repair",
        "--verifier" if verifier else "--no-verifier",
    ]
    if model:
        command.extend(("--model", model))
    if fault_profile:
        command.extend(("--fault-profile", fault_profile))
    if limit is not None:
        command.extend(("--limit", str(limit)))
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    timeout = int(os.getenv("COMPARISON_RUN_TIMEOUT_SECONDS", "7500"))
    if timeout <= 0:
        raise ValueError("COMPARISON_RUN_TIMEOUT_SECONDS must be positive")
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{label} runner timed out after {timeout} seconds") from exc
    try:
        summary = _json_from_output(completed.stdout)
    except (json.JSONDecodeError, RuntimeError) as exc:
        detail = (completed.stderr or completed.stdout)[-1000:]
        raise RuntimeError(
            f"{label} runner failed without a valid summary "
            f"(exit {completed.returncode}): {detail}"
        ) from exc
    if completed.returncode not in (0, 1):
        raise RuntimeError(
            f"{label} runner infrastructure failed (exit {completed.returncode}): "
            f"{completed.stderr[-1000:]}"
        )
    if summary.get("execution_status") != "COMPLETED":
        raise RuntimeError(f"{label} runner did not report COMPLETED execution")
    summary_path = Path(str(summary.get("summary", "")))
    if not summary_path.is_file():
        raise RuntimeError(f"{label} runner summary artifact is missing: {summary_path}")
    persisted = json.loads(summary_path.read_text(encoding="utf-8"))
    if (
        not isinstance(persisted, dict)
        or persisted.get("schema") != "suite-run-summary-v1"
        or persisted.get("execution_status") != "COMPLETED"
        or persisted.get("run_id") != summary.get("run_id")
    ):
        raise RuntimeError(f"{label} runner summary artifact violates its contract")
    return summary


def _add_version_arguments(parser: argparse.ArgumentParser, prefix: str, *, verifier: bool) -> None:
    parser.add_argument(f"--{prefix}-mode", choices=("deterministic", "api"), default="deterministic")
    parser.add_argument(f"--{prefix}-provider", choices=("openai", "gemini", "groq"), default="openai")
    parser.add_argument(f"--{prefix}-model", default=None)
    parser.add_argument(
        f"--{prefix}-sql-strategy",
        choices=("canonical", "model"),
        default="canonical",
    )
    parser.add_argument(
        f"--{prefix}-fault-profile",
        choices=("sql-typo", "unsafe-delete", "wrong-policy"),
        default=None,
    )
    parser.add_argument(
        f"--{prefix}-repair",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument(f"--{prefix}-max-retries", type=int, default=0)
    parser.add_argument(
        f"--{prefix}-verifier",
        action=argparse.BooleanOptionalAction,
        default=verifier,
    )
    parser.add_argument(f"--{prefix}-max-reflections", type=int, default=2 if verifier else 0)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Run a paired V0/V1 Testbed experiment")
    parser.add_argument("--trials", type=int, default=2)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--change-note", default="Reasoning Verifier utility comparison")
    parser.add_argument("--bundle-out", type=Path, default=None)
    _add_version_arguments(parser, "baseline", verifier=False)
    _add_version_arguments(parser, "candidate", verifier=True)
    args = parser.parse_args()

    baseline = _run_version(
        label="V0",
        mode=args.baseline_mode,
        provider=args.baseline_provider,
        model=args.baseline_model,
        sql_strategy=args.baseline_sql_strategy,
        fault_profile=args.baseline_fault_profile,
        repair=args.baseline_repair,
        max_retries=args.baseline_max_retries,
        verifier=args.baseline_verifier,
        max_reflections=args.baseline_max_reflections,
        trials=args.trials,
        limit=args.limit,
    )
    candidate = _run_version(
        label="V1",
        mode=args.candidate_mode,
        provider=args.candidate_provider,
        model=args.candidate_model,
        sql_strategy=args.candidate_sql_strategy,
        fault_profile=args.candidate_fault_profile,
        repair=args.candidate_repair,
        max_retries=args.candidate_max_retries,
        verifier=args.candidate_verifier,
        max_reflections=args.candidate_max_reflections,
        trials=args.trials,
        limit=args.limit,
    )

    baseline_dir = Path(str(baseline["summary"])).resolve().parent
    candidate_dir = Path(str(candidate["summary"])).resolve().parent
    bundle = make_bundle(baseline_dir, candidate_dir, args.change_note)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = (args.bundle_out or REPO_ROOT / "reports" / "bundles" / f"comparison_{stamp}.json").resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "bundle": str(output),
                "baseline_run": str(baseline_dir),
                "candidate_run": str(candidate_dir),
                "testcase_count": len(bundle["suite"]["testcase_ids"]),
                "trial_count": len(bundle["trials"]),
                "baseline_config": baseline["scaffold_config"],
                "candidate_config": candidate["scaffold_config"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
