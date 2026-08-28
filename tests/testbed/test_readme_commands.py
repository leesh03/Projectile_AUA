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
    assert "--mode api --provider gemini" in readme
    assert "--mode api --provider groq" in readme


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
    assert summary["provider"] == "deterministic"


def test_api_mode_requires_explicit_provider() -> None:
    completed = _run(
        "-B",
        "run_agent.py",
        "run-one",
        "--case",
        "E-001",
        "--mode",
        "api",
    )
    assert completed.returncode == 2
    assert "requires an explicit --provider" in completed.stderr


def test_ask_runs_in_isolation_without_claiming_gold_accuracy() -> None:
    completed = _run(
        "-B",
        "run_agent.py",
        "ask",
        "--question",
        "이 주문 상품을 환불할 수 있나요?",
        "--order-item-id",
        "OI-E-001",
        "--amount",
        "10000",
        "--evaluation-date",
        "2026-08-15",
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    summary = json.loads(completed.stdout)
    assert summary["task_success"] is True
    assert summary["decision"] == "APPROVE"
    assert summary["response"]
    assert summary["evaluation_basis"] == "ENGINE_ONLY"
    artifact = json.loads(Path(summary["summary"]).read_text(encoding="utf-8"))
    assert artifact["record"]["evaluation_basis"] == "ENGINE_ONLY"
    assert artifact["record"]["gold_agreement"] is None


def test_cli_stdout_is_utf8_without_environment_overrides() -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONUTF8", None)
    environment.pop("PYTHONIOENCODING", None)
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "run_agent.py",
            "run-one",
            "--case",
            "E-001",
            "--mode",
            "deterministic",
        ],
        cwd=ROOT,
        capture_output=True,
        env=environment,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    summary = json.loads(completed.stdout.decode("utf-8"))
    assert "에이전트_활동" in summary["summary"]


def test_comparison_api_mode_requires_provider_per_version() -> None:
    completed = _run(
        "-B",
        "tools/run_comparison.py",
        "--baseline-mode",
        "api",
    )
    assert completed.returncode == 2
    assert "--baseline-mode api requires --baseline-provider" in completed.stderr


def test_other_readme_entrypoints_parse() -> None:
    for command in (
        ("-B", "tools/run_comparison.py", "--help"),
        ("-m", "apps.cli", "--help"),
    ):
        completed = _run(*command)
        assert completed.returncode == 0, completed.stdout + completed.stderr
