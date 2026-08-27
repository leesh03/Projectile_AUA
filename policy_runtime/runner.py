"""Execute the versioned suite and persist Core TrialResult artifacts."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

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


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


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
        experiment_provenance: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        jobs = [
            {"case": raw_case, "trial": trial}
            for raw_case in cases
            for trial in range(1, trials + 1)
        ]
        worker_environment = os.environ.copy()
        worker_environment["PYTHONUTF8"] = "1"
        worker_environment["PYTHONIOENCODING"] = "utf-8"
        worker_environment.pop("PYTHONPATH", None)
        worker_environment.pop("POLICY_AGENT_DB_PATH", None)
        key_name = self._provider_key_name(self.bundle.provider)
        if key_name and self.bundle.runtime_api_key:
            worker_environment[key_name] = self.bundle.runtime_api_key
        timeout = int(os.getenv("AGENT_WORKER_TIMEOUT_SECONDS", "7200"))
        if timeout <= 0:
            raise ValueError("AGENT_WORKER_TIMEOUT_SECONDS must be positive")
        with tempfile.TemporaryDirectory(prefix="policy-agent-stage-") as temporary:
            stage_root = Path(temporary) / "project"
            self._stage_agent_root(stage_root)
            staged_output = stage_root / ".agent-output"
            staged_db = stage_root / "data" / "shop.db"
            request_payload = {
                "schema": "isolated-agent-request-v2",
                "project_root": str(stage_root),
                "blocked_roots": [str(self.project_root)],
                "output_root": str(staged_output),
                "run_id": run_id,
                "mode": self.bundle.mode,
                "provider": self.bundle.provider,
                "model": self.bundle.model,
                "db_path": str(staged_db),
                "agent_label": self.bundle.agent_label,
                "scaffold_overrides": dict(self.bundle.scaffold_config),
                "version_metadata": dict(self.bundle.version_metadata),
                "structured_output_retries": self.bundle.structured_output_retries,
                "sql_strategy": self.bundle.sql_strategy,
                "fault_profile": self.bundle.fault_profile,
                "experiment_provenance": dict(experiment_provenance),
                "jobs": jobs,
            }
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
                cwd=stage_root,
                env=worker_environment,
                timeout=timeout,
                check=False,
            )
            if completed.returncode == 0:
                staged_run = staged_output / run_id
                destination = self.output_root / run_id
                if not staged_run.is_dir():
                    raise RuntimeError("isolated Agent worker did not create its run directory")
                if destination.exists():
                    raise FileExistsError(f"run output already exists: {destination}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(staged_run, destination)
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

    def _stage_agent_root(self, stage_root: Path) -> None:
        """Copy only Agent runtime inputs; evaluator Gold never enters the namespace."""

        source_db = (self.bundle.db_path or self.project_root / "data" / "shop.db").resolve()
        gold_db = self.project_root / "data" / "answer_key.db"
        same_as_gold = False
        if source_db.exists() and gold_db.exists():
            try:
                same_as_gold = source_db.samefile(gold_db)
            except OSError:
                same_as_gold = False
        if source_db.name.casefold() == "answer_key.db" or same_as_gold:
            raise ValueError("the Agent runtime database cannot be a Gold database")
        required_files = (
            source_db,
            self.project_root / "policies" / "policy_rules.json",
            self.project_root / "core" / "__init__.py",
        )
        missing = [str(path) for path in required_files if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"Agent staging input is missing: {missing}")

        ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".ruff_cache")
        shutil.copytree(self.project_root / "agents", stage_root / "agents", ignore=ignore)
        shutil.copytree(
            self.project_root / "policy_runtime",
            stage_root / "policy_runtime",
            ignore=ignore,
        )
        shutil.copytree(
            self.project_root / "core" / "schemas",
            stage_root / "core" / "schemas",
            ignore=ignore,
        )
        shutil.copy2(
            self.project_root / "core" / "__init__.py",
            stage_root / "core" / "__init__.py",
        )
        (stage_root / "data").mkdir(parents=True, exist_ok=True)
        (stage_root / "policies").mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_db, stage_root / "data" / "shop.db")
        shutil.copy2(
            self.project_root / "policies" / "policy_rules.json",
            stage_root / "policies" / "policy_rules.json",
        )

    def _patch_evaluation(
        self,
        run_id: str,
        relative_artifact: str,
        policy_correct: bool,
        *,
        evaluation_basis: str,
        engine_consistency: bool,
        gold_agreement: bool | None,
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
            raise TypeError("isolated trial artifact is missing trial_result")
        trial_result["policy_correct"] = policy_correct
        trial_result["evaluation_basis"] = evaluation_basis
        trial_result["engine_consistency"] = engine_consistency
        trial_result["gold_agreement"] = gold_agreement
        temporary = target.with_suffix(target.suffix + ".evaluator.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)

    def _gold_source(self) -> tuple[dict[str, dict[str, Any]], Path | None, str | None]:
        candidates = (
            self.project_root / "evaluation" / "private" / "expected_cases.json",
            self.project_root / "data" / "test_cases.json",
        )
        for path in candidates:
            if path.is_file():
                version = None
                manifest_path = self.project_root / "data" / "version_manifest.json"
                if manifest_path.is_file():
                    raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    version = raw_manifest.get("core_version_vector", {}).get("gold_version")
                return (
                    {item["testcase_id"]: item for item in _read_array(path)},
                    path,
                    version,
                )
        return {}, None, None

    def _experiment_provenance(
        self,
        cases: list[dict[str, Any]],
        *,
        gold_path: Path | None,
        gold_version: str | None,
    ) -> dict[str, Any]:
        manifest_path = self.project_root / "data" / "version_manifest.json"
        version_manifest: dict[str, Any] = {}
        if manifest_path.is_file():
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                version_manifest = loaded
        vector = version_manifest.get("core_version_vector", {})
        if not isinstance(vector, Mapping):
            vector = {}
        agent_cases_path = self.project_root / "data" / "agent_cases.json"
        agent_cases_hash = _sha256_file(agent_cases_path)
        testcase_ids = [str(case["testcase_id"]) for case in cases]
        contexts = [
            {
                "testcase_id": str(case["testcase_id"]),
                "trusted_context": case.get("trusted_context"),
            }
            for case in cases
        ]
        dataset_base = str(
            version_manifest.get("testcase_version")
            or vector.get("suite_version")
            or "dataset-unknown"
        )
        suite_id = str(vector.get("suite_version") or "suite-unknown")
        return {
            "suite_id": suite_id,
            "dataset_version": f"{dataset_base}:{agent_cases_hash[:12]}",
            "dataset_manifest_sha256": (
                _sha256_file(manifest_path) if manifest_path.is_file() else None
            ),
            "agent_cases_sha256": agent_cases_hash,
            "gold_sha256": _sha256_file(gold_path) if gold_path is not None else None,
            "gold_version": gold_version,
            "executed_testcase_ids": testcase_ids,
            "testcase_ids_sha256": _sha256_json(testcase_ids),
            "evaluation_context_sha256": _sha256_json(contexts),
            "evaluation_date": version_manifest.get("evaluation_date"),
            "timezone": version_manifest.get("timezone"),
            "tool_schema_version": self.bundle.version_metadata.get(
                "tool_schema_version", "sqlite-select-v1"
            ),
            "trial_contract_version": "trial-result-v2",
        }

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
        gold, gold_path, gold_version = self._gold_source()
        experiment_provenance = self._experiment_provenance(
            cases,
            gold_path=gold_path,
            gold_version=gold_version,
        )
        records: list[dict[str, Any]] = []
        isolated_records = self._run_isolated(
            cases,
            trials=trials,
            run_id=run_id,
            experiment_provenance=experiment_provenance,
        )
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
            # Gold correctness and engine self-consistency are distinct metrics.
            # A Gold-less run cannot claim policy accuracy and is rejected by
            # the official strict Bundle producer.
            evaluation_basis = "GOLD" if gold_agreement is not None else "ENGINE_ONLY"
            policy_correct = bool(gold_agreement) if gold_agreement is not None else False
            artifact = isolated.get("artifact")
            if not isinstance(artifact, str) or not artifact:
                raise RuntimeError("isolated Agent worker did not return an artifact path")
            self._patch_evaluation(
                run_id,
                artifact,
                policy_correct,
                evaluation_basis=evaluation_basis,
                engine_consistency=engine_consistency,
                gold_agreement=gold_agreement,
            )
            isolated.pop("facts", None)
            isolated["policy_correct"] = policy_correct
            isolated["evaluation_basis"] = evaluation_basis
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
            "scaffold_config": self.bundle.graph.config.as_scaffold_config(),
            "version_metadata": dict(self.bundle.version_metadata),
            "runtime_metadata": dict(self.bundle.runtime_metadata),
            "sql_strategy": self.bundle.sql_strategy,
            "fault_profile": self.bundle.fault_profile,
            "execution_status": "COMPLETED",
            "experiment_provenance": experiment_provenance,
            "planner": False,
            "isolation": "staged-subprocess-audit-v2",
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
                "policy_correct": "Agent decision/clauses equal independent Gold; false and not claimable when Gold is absent",
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
