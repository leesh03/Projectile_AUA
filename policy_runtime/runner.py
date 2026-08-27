"""Execute the versioned suite and persist Core TrialResult artifacts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from agents.policy_agent.nodes.state import create_run_id
from policy_runtime.engine import InputContractError
from policy_runtime.factory import AgentBundle


@dataclass(frozen=True, slots=True)
class SuiteRunSummary:
    run_id: str
    total_trials: int
    task_successes: int
    policy_correct: int
    engine_consistency: int
    gold_agreements: int | None
    oracle_agreements: int | None
    output_path: Path


def _read_array(path: Path) -> list[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load suite file {path}: {exc}") from exc
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"suite file must contain an array of objects: {path}")
    return value


def _same_decision_values(
    decision: Any,
    clauses: Any,
    expected: Mapping[str, Any],
) -> bool:
    return (
        decision == expected.get("decision")
        and isinstance(clauses, list)
        and set(clauses) == set(expected.get("clauses", []))
    )


class SuiteRunner:
    def __init__(
        self,
        project_root: str | Path,
        bundle: AgentBundle,
        *,
        output_root: str | Path | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.bundle = bundle
        self.output_root = Path(output_root or self.project_root / "reports" / "runs").resolve()

    @staticmethod
    def _provider_key_name(provider: str) -> str | None:
        return {
            "openai": "OPENAI_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "groq": "GROQ_API_KEY",
        }.get(provider)

    def _run_isolated(
        self,
        cases: list[dict[str, Any]],
        *,
        trials: int,
        run_id: str,
    ) -> list[dict[str, Any]]:
        jobs = [
            {"case": raw_case, "trial": trial}
            for raw_case in cases
            for trial in range(1, trials + 1)
        ]
        request_payload = {
            "schema": "isolated-agent-request-v1",
            "project_root": str(self.project_root),
            "output_root": str(self.output_root),
            "run_id": run_id,
            "mode": self.bundle.mode,
            "provider": self.bundle.provider,
            "model": self.bundle.model,
            "db_path": str(self.bundle.db_path) if self.bundle.db_path else None,
            "agent_label": self.bundle.agent_label,
            "scaffold_overrides": dict(self.bundle.scaffold_config),
            "version_metadata": dict(self.bundle.version_metadata),
            "sql_strategy": self.bundle.sql_strategy,
            "fault_profile": self.bundle.fault_profile,
            "jobs": jobs,
        }
        worker_environment = os.environ.copy()
        worker_environment["PYTHONUTF8"] = "1"
        worker_environment["PYTHONIOENCODING"] = "utf-8"
        key_name = self._provider_key_name(self.bundle.provider)
        if key_name and self.bundle.runtime_api_key:
            worker_environment[key_name] = self.bundle.runtime_api_key
        timeout = int(os.getenv("AGENT_WORKER_TIMEOUT_SECONDS", "7200"))
        if timeout <= 0:
            raise ValueError("AGENT_WORKER_TIMEOUT_SECONDS must be positive")
        completed = subprocess.run(
            [sys.executable, "-B", "-m", "policy_runtime.isolated_worker"],
            input=json.dumps(
                request_payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            text=True,
            encoding="utf-8",
            capture_output=True,
            cwd=self.project_root,
            env=worker_environment,
            timeout=timeout,
            check=False,
        )
        if completed.returncode != 0:
            detail = " ".join((completed.stderr or "").split())[-500:]
            raise RuntimeError(
                "isolated Agent worker failed"
                + (f": {detail}" if detail else " without an error message")
            )
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("isolated Agent worker returned invalid JSON") from exc
        if not isinstance(result, dict) or result.get("schema") != "isolated-agent-result-v1":
            raise RuntimeError("isolated Agent worker returned an invalid contract")
        records = result.get("records")
        if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
            raise RuntimeError("isolated Agent worker records must be an array")
        if len(records) != len(jobs):
            raise RuntimeError("isolated Agent worker returned an unexpected trial count")
        return records

    def _patch_policy_correct(
        self,
        run_id: str,
        relative_artifact: str,
        policy_correct: bool,
    ) -> None:
        run_root = (self.output_root / run_id).resolve()
        target = (run_root / relative_artifact).resolve()
        if not target.is_relative_to(run_root):
            raise ValueError("isolated worker returned an unsafe artifact path")
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read isolated trial artifact: {target}") from exc
        trial_result = payload.get("trial_result") if isinstance(payload, dict) else None
        if not isinstance(trial_result, dict):
            raise ValueError("isolated trial artifact is missing trial_result")
        trial_result["policy_correct"] = policy_correct
        temporary = target.with_suffix(target.suffix + ".evaluator.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)

    def _gold_index(self) -> dict[str, dict[str, Any]]:
        candidates = (
            self.project_root / "evaluation" / "private" / "expected_cases.json",
            self.project_root / "data" / "test_cases.json",
        )
        for path in candidates:
            if path.is_file():
                return {item["testcase_id"]: item for item in _read_array(path)}
        return {}

    @staticmethod
    def _gold_equal(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> bool:
        keys = (
            "eligibility",
            "case_status",
            "next_action",
            "primary_clause",
            "matched_clauses",
            "overridden_clauses",
            "required_fields",
        )
        return all(actual.get(key) == expected.get(key) for key in keys)

    @staticmethod
    def _gold_agent_answer(expected: Mapping[str, Any]) -> dict[str, Any] | None:
        decision_by_eligibility = {
            "ELIGIBLE": "APPROVE",
            "INELIGIBLE": "REJECT",
            "UNDETERMINED": "NEED_MORE_INFO",
            "NOT_APPLICABLE": "NOT_APPLICABLE",
        }
        decision = decision_by_eligibility.get(expected.get("eligibility"))
        clauses = expected.get("matched_clauses")
        if decision is None or not isinstance(clauses, list):
            return None
        return {"decision": decision, "clauses": clauses}

    def run(
        self,
        *,
        trials: int = 1,
        limit: int | None = None,
        testcase_id: str | None = None,
    ) -> SuiteRunSummary:
        if not 1 <= trials <= 3:
            raise ValueError("trials must be between 1 and 3")
        cases = _read_array(self.project_root / "data" / "agent_cases.json")
        if testcase_id is not None:
            cases = [item for item in cases if item.get("testcase_id") == testcase_id]
            if not cases:
                raise ValueError(f"unknown testcase_id: {testcase_id}")
        if limit is not None:
            if limit <= 0:
                raise ValueError("limit must be positive")
            cases = cases[:limit]

        run_id = create_run_id()
        gold = self._gold_index()
        records: list[dict[str, Any]] = []
        isolated_records = self._run_isolated(cases, trials=trials, run_id=run_id)
        for isolated in isolated_records:
            testcase = isolated.get("testcase_id")
            facts = isolated.get("facts")
            try:
                if not isinstance(facts, Mapping):
                    raise TypeError("isolated facts must be an object")
                expected = self.bundle.policy_engine.evaluate(facts)
                expected_agent = {
                    "decision": expected.decision,
                    "clauses": expected.value["matched_clauses"],
                }
                engine_consistency = _same_decision_values(
                    isolated.get("decision"),
                    isolated.get("clauses"),
                    expected_agent,
                )
            except (InputContractError, KeyError, TypeError, ValueError):
                expected = None
                engine_consistency = False

            expected_gold = (
                gold.get(testcase, {}).get("expected_result")
                if isinstance(testcase, str)
                else None
            )
            expected_gold_answer = (
                self._gold_agent_answer(expected_gold)
                if isinstance(expected_gold, Mapping)
                else None
            )
            gold_agreement = (
                None
                if expected_gold_answer is None
                else _same_decision_values(
                    isolated.get("decision"),
                    isolated.get("clauses"),
                    expected_gold_answer,
                )
            )
            oracle_agreement = (
                None
                if expected is None or not isinstance(expected_gold, Mapping)
                else self._gold_equal(expected_gold, expected.value)
            )
            # TrialResult keeps its stable boolean contract.  When private Gold
            # is available this is a genuinely independent Agent-vs-Gold score;
            # otherwise it falls back to the explicitly named engine check.
            policy_correct = (
                gold_agreement if gold_agreement is not None else engine_consistency
            )
            artifact = isolated.get("artifact")
            if not isinstance(artifact, str) or not artifact:
                raise RuntimeError("isolated Agent worker did not return an artifact path")
            self._patch_policy_correct(run_id, artifact, policy_correct)
            isolated.pop("facts", None)
            isolated["policy_correct"] = policy_correct
            isolated["engine_consistency"] = engine_consistency
            isolated["gold_agreement"] = gold_agreement
            isolated["oracle_agreement"] = oracle_agreement
            records.append(isolated)

        gold_values = [item["gold_agreement"] for item in records if item["gold_agreement"] is not None]
        oracle_values = [
            item["oracle_agreement"]
            for item in records
            if item["oracle_agreement"] is not None
        ]
        payload = {
            "schema": "suite-run-summary-v1",
            "run_id": run_id,
            "mode": self.bundle.mode,
            "provider": self.bundle.provider,
            "agent_label": self.bundle.agent_label,
            "scaffold_config": dict(self.bundle.scaffold_config),
            "version_metadata": dict(self.bundle.version_metadata),
            "sql_strategy": self.bundle.sql_strategy,
            "fault_profile": self.bundle.fault_profile,
            "planner": False,
            "isolation": "subprocess-audit-v1",
            "case_count": len(cases),
            "trial_count": len(records),
            "task_successes": sum(bool(item["task_success"]) for item in records),
            "policy_correct": sum(bool(item["policy_correct"]) for item in records),
            "engine_consistency": sum(bool(item["engine_consistency"]) for item in records),
            "gold_agreements": (
                sum(bool(value) for value in gold_values) if gold_values else None
            ),
            "oracle_agreements": (
                sum(bool(value) for value in oracle_values) if oracle_values else None
            ),
            "metric_definitions": {
                "task_successes": "trials that completed and produced a valid artifact",
                "engine_consistency": "Agent decision/clauses equal the local policy engine",
                "gold_agreements": "Agent decision/clauses equal private Gold",
                "oracle_agreements": "local policy engine detailed result equals private Gold",
                "policy_correct": "Gold agreement when Gold exists; otherwise engine consistency",
            },
            "records": records,
        }
        summary_path = self.output_root / run_id / "suite_summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = summary_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(summary_path)
        return SuiteRunSummary(
            run_id=run_id,
            total_trials=len(records),
            task_successes=payload["task_successes"],
            policy_correct=payload["policy_correct"],
            engine_consistency=payload["engine_consistency"],
            gold_agreements=payload["gold_agreements"],
            oracle_agreements=payload["oracle_agreements"],
            output_path=summary_path,
        )
