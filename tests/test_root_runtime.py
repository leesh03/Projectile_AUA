from __future__ import annotations

import json
from pathlib import Path

from agents.policy_agent.nodes.state import AgentRequest
from policy_runtime.factory import build_agent

ROOT = Path(__file__).resolve().parents[1]


def test_legacy_compact_directory_is_absent() -> None:
    assert not (ROOT / ("compact" + "_agent")).exists()


def _case(testcase_id: str = "E-001") -> dict:
    cases = json.loads((ROOT / "data" / "agent_cases.json").read_text(encoding="utf-8"))
    return next(item for item in cases if item["testcase_id"] == testcase_id)


def test_runtime_modules_and_agent_are_root_owned() -> None:
    from policy_runtime import factory, runner

    for module in (factory, runner):
        path = Path(module.__file__).resolve()
        assert path.is_relative_to(ROOT)
        assert ("compact" + "_agent") not in path.parts

    bundle = build_agent(ROOT, mode="deterministic", agent_label="V0")
    result = bundle.graph.run(AgentRequest.from_mapping(_case()))
    assert result.state.task_success
    assert result.state.stop_reason == "OK"
    assert result.state.decision == "APPROVE"


def test_scaffold_overrides_are_recorded_and_verifier_can_be_disabled() -> None:
    bundle = build_agent(
        ROOT,
        mode="deterministic",
        agent_label="V1",
        scaffold_overrides={
            "use_reasoning_verifier": False,
            "max_reflections": 0,
        },
    )
    result = bundle.graph.run(AgentRequest.from_mapping(_case()), agent_label="V1")
    assert result.state.task_success
    assert result.state.config.as_scaffold_config()["verifier"] == 0
    assert "VERIFY_REASONING" not in [step.node_role for step in result.state.traces]


def test_fault_profile_proves_sql_repair_utility() -> None:
    request = AgentRequest.from_mapping(_case())
    without_repair = build_agent(
        ROOT,
        mode="deterministic",
        scaffold_overrides={"use_sql_repair": False, "max_sql_retries": 0},
        fault_profile="sql-typo",
    ).graph.run(request)
    with_repair = build_agent(
        ROOT,
        mode="deterministic",
        scaffold_overrides={"use_sql_repair": True, "max_sql_retries": 1},
        fault_profile="sql-typo",
    ).graph.run(request)

    assert not without_repair.state.task_success
    assert without_repair.state.stop_reason == "SQL_FAILURE"
    assert with_repair.state.task_success
    assert with_repair.state.retry_count == 1
    assert any(step.node_role == "REPAIR_QUERY" for step in with_repair.state.traces)
