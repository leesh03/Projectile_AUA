"""CLI for one case or the complete local 60-case suite."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from agents.policy_agent.nodes.state import AgentRequest
from policy_runtime.env import load_dotenv
from policy_runtime.factory import build_agent
from policy_runtime.runner import SuiteRunner


def _configure_utf8_stdio() -> None:
    """Keep JSON CLI output interoperable on Windows and redirected streams."""

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


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
    _configure_utf8_stdio()
    root = Path(__file__).resolve().parent
    load_dotenv(root / ".env")
    parser = argparse.ArgumentParser(description="Refund policy Agent local runner")
    parser.add_argument("command", choices=("run-suite", "run-one", "ask"))
    parser.add_argument("--mode", choices=("deterministic", "api"), default="deterministic")
    parser.add_argument(
        "--provider",
        choices=("openai", "gemini", "groq"),
        default=None,
        help="required when --mode api; ignored in deterministic mode",
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
        "--schema-retries",
        type=int,
        choices=(0, 1, 2),
        default=None,
        help="bounded correction retries for malformed structured model output",
    )
    parser.add_argument(
        "--stop-on-repeated-error",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument("--max-total-steps", type=int, default=None)
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--case", dest="testcase_id", default=None)
    parser.add_argument("--question", default=None, help="free-form question for ask")
    parser.add_argument("--order-item-id", default=None, help="trusted order item ID for ask")
    parser.add_argument("--amount", type=int, default=None, help="requested refund amount for ask")
    parser.add_argument("--currency", default="KRW", help="trusted request currency for ask")
    parser.add_argument(
        "--evaluation-date",
        default=None,
        help="trusted YYYY-MM-DD policy evaluation date for ask; defaults to today in Asia/Seoul",
    )
    parser.add_argument(
        "--isolation",
        choices=("staged", "container"),
        default="staged",
        help="container requires Docker and provides an OS-level boundary",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="official or custom shop DB (also configurable with POLICY_AGENT_DB_PATH)",
    )
    args = parser.parse_args()
    if args.command == "run-one" and not args.testcase_id:
        parser.error("run-one requires --case")
    if args.command == "ask" and (not args.question or not args.order_item_id):
        parser.error("ask requires --question and --order-item-id")
    if args.mode == "api" and args.provider is None:
        parser.error("--mode api requires an explicit --provider")

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
        structured_output_retries=args.schema_retries,
        sql_strategy=args.sql_strategy,
        fault_profile=args.fault_profile,
    )
    runner = SuiteRunner(root, bundle, isolation=args.isolation)
    if args.command == "ask":
        request = AgentRequest.interactive(
            args.question,
            order_item_id=args.order_item_id,
            evaluation_date=args.evaluation_date,
            requested_amount=args.amount,
            currency=args.currency,
        )
        interactive = runner.run_interactive(request)
        print(
            json.dumps(
                {
                    "execution_status": "COMPLETED",
                    "run_id": interactive.run_id,
                    "task_success": interactive.task_success,
                    "decision": interactive.decision,
                    "response": interactive.response,
                    "stop_reason": interactive.stop_reason,
                    "error_type": interactive.error_type,
                    "evaluation_basis": "ENGINE_ONLY",
                    "engine_consistency": interactive.engine_consistency,
                    "provider": bundle.provider,
                    "isolation": args.isolation,
                    "summary": str(interactive.output_path),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if interactive.task_success else 1
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
