from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run(*command: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, *command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        check=False,
    )


def test_readme_uses_real_cli_and_case_id() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "run_agent.py run-case" not in readme
    assert "run_agent.py run-one --case E-001 --mode deterministic" in readme
    assert "run_agent.py run-suite --mode deterministic" in readme


def test_readme_run_one_command_executes() -> None:
    completed = _run(
        "-B",
        "run_agent.py",
        "run-one",
        "--case",
        "E-001",
        "--mode",
        "deterministic",
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    summary = json.loads(completed.stdout)
    assert summary["execution_status"] == "COMPLETED"
    assert summary["total_trials"] == summary["task_successes"] == 1


def test_other_readme_entrypoints_parse() -> None:
    for command in (
        ("-B", "tools/run_comparison.py", "--help"),
        ("-m", "apps.cli", "--help"),
    ):
        completed = _run(*command)
        assert completed.returncode == 0, completed.stdout + completed.stderr

