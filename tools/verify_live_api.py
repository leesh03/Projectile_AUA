"""Opt-in real-provider smoke test for the isolated Testbed Agent."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

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
    root = REPO_ROOT
    load_dotenv(root / ".env")
    parser = argparse.ArgumentParser(
        description="Run one Gold-scored smoke case against a real API provider"
    )
    parser.add_argument("--provider", choices=("gemini", "groq"), required=True)
    parser.add_argument("--model", default=None)
    parser.add_argument("--case", default="E-001")
    parser.add_argument(
        "--isolation",
        choices=("staged", "container"),
        default="container",
    )
    args = parser.parse_args()

    bundle = build_agent(
        root,
        mode="api",
        provider=args.provider,
        model=args.model,
        scaffold_overrides={
            "use_sql_repair": False,
            "max_sql_retries": 0,
            "use_reasoning_verifier": False,
            "max_reflections": 0,
        },
        version_metadata={
            "version": "live-api-smoke",
            "prompt_version": "p1",
            "tool_schema_version": "sqlite-select-v1",
            "workflow_version": "policy-graph-v1;live-api-smoke",
            "commit": _git_commit(root),
        },
        structured_output_retries=1,
        sql_strategy="canonical",
    )
    summary = SuiteRunner(root, bundle, isolation=args.isolation).run(
        trials=1,
        testcase_id=args.case,
    )
    passed = (
        summary.total_trials == 1
        and summary.task_successes == 1
        and summary.policy_correct == 1
        and summary.gold_agreements == 1
    )
    print(
        json.dumps(
            {
                "schema": "live-api-smoke-v1",
                "passed": passed,
                "provider": bundle.provider,
                "model": bundle.model,
                "testcase_id": args.case,
                "isolation": args.isolation,
                "task_successes": summary.task_successes,
                "gold_agreements": summary.gold_agreements,
                "summary": str(summary.output_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
