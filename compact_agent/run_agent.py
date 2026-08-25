"""CLI for one case or the complete local 60-case suite."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from policy_runtime.env import load_dotenv
from policy_runtime.factory import build_agent
from policy_runtime.runner import SuiteRunner


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

    bundle = build_agent(
        root,
        mode=args.mode,
        provider=args.provider,
        model=args.model,
        db_path=args.db_path,
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
                "run_id": summary.run_id,
                "total_trials": summary.total_trials,
                "task_successes": summary.task_successes,
                "policy_correct": summary.policy_correct,
                "engine_consistency": summary.engine_consistency,
                "gold_agreements": summary.gold_agreements,
                "oracle_agreements": summary.oracle_agreements,
                "provider": bundle.provider,
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
