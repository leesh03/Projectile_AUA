"""CLI for one case or the complete local 60-case suite."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from policy_runtime.env import load_dotenv
from policy_runtime.factory import build_agent
from policy_runtime.runner import SuiteRunner


def _git_commit(root: Path) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and value else None


def main() -> int:
    root = Path(__file__).resolve().parent
    load_dotenv(root / ".env")
    parser = argparse.ArgumentParser(description="Refund policy Agent local runner")
    parser.add_argument("command", choices=("run-suite", "run-one"))
    parser.add_argument("--mode", choices=("deterministic", "api"), default="deterministic")
    parser.add_argument(
        "--provider",
        choices=("openai", "gemini", "groq"),
        default="openai",
        help="API provider used when --mode api",
    )
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--sql-strategy",
        choices=("canonical", "model"),
        default="canonical",
        help="canonical is reproducible; model lets the selected API model generate SQL",
    )
    parser.add_argument(
        "--fault-profile",
        choices=("sql-typo", "unsafe-delete", "wrong-policy"),
        default=None,
        help="inject a reproducible SQL failure for Repair ON/OFF tests",
    )
    parser.add_argument("--agent-label", default="V0")
    parser.add_argument("--agent-version", default=None)
    parser.add_argument("--prompt-version", default="p1")
    parser.add_argument("--tool-schema-version", default="sqlite-select-v1")
    parser.add_argument("--workflow-version", default="policy-graph-v1")
    parser.add_argument("--commit", default=None)
    parser.add_argument(
        "--repair",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="enable or disable SQL Repair for this version",
    )
    parser.add_argument("--max-retries", type=int, default=None)
    parser.add_argument(
        "--verifier",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="enable or disable Reasoning Verifier for this version",
    )
    parser.add_argument("--max-reflections", type=int, default=None)
    parser.add_argument(
        "--stop-on-repeated-error",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument("--max-total-steps", type=int, default=None)
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--case", dest="testcase_id", default=None)
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="official or custom shop DB (also configurable with POLICY_AGENT_DB_PATH)",
    )
    args = parser.parse_args()
    if args.command == "run-one" and not args.testcase_id:
        parser.error("run-one requires --case")

    scaffold_overrides = {
        key: value
        for key, value in {
            "use_sql_repair": args.repair,
            "max_sql_retries": args.max_retries,
            "use_reasoning_verifier": args.verifier,
            "max_reflections": args.max_reflections,
            "stop_on_repeated_error": args.stop_on_repeated_error,
            "max_total_steps": args.max_total_steps,
        }.items()
        if value is not None
    }
    version_metadata = {
        "version": args.agent_version or args.agent_label.lower(),
        "prompt_version": args.prompt_version,
        "tool_schema_version": args.tool_schema_version,
        "workflow_version": (
            f"{args.workflow_version};sql={args.sql_strategy};"
            f"fault={args.fault_profile or 'none'}"
        ),
        "commit": args.commit or _git_commit(root),
    }

    bundle = build_agent(
        root,
        mode=args.mode,
        provider=args.provider,
        model=args.model,
        db_path=args.db_path,
        agent_label=args.agent_label,
        scaffold_overrides=scaffold_overrides,
        version_metadata=version_metadata,
        sql_strategy=args.sql_strategy,
        fault_profile=args.fault_profile,
    )
    runner = SuiteRunner(root, bundle)
    summary = runner.run(
        trials=args.trials,
        limit=(1 if args.command == "run-one" else args.limit),
        testcase_id=args.testcase_id if args.command == "run-one" else None,
    )
    print(
        json.dumps(
            {
                "execution_status": "COMPLETED",
                "run_id": summary.run_id,
                "total_trials": summary.total_trials,
                "task_successes": summary.task_successes,
                "policy_correct": summary.policy_correct,
                "engine_consistency": summary.engine_consistency,
                "gold_agreements": summary.gold_agreements,
                "oracle_agreements": summary.oracle_agreements,
                "provider": bundle.provider,
                "agent_label": bundle.agent_label,
                "scaffold_config": bundle.graph.config.as_scaffold_config(),
                "sql_strategy": bundle.sql_strategy,
                "fault_profile": bundle.fault_profile,
                "trial_failures": summary.total_trials - summary.task_successes,
                "summary": str(summary.output_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return (
        0
        if summary.task_successes == summary.total_trials
        and summary.policy_correct == summary.total_trials
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
