"""Dependency-free local implementation of the shared TraceStep contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.schemas.enums import NodeRole, StepOutcome, StepType


@dataclass(frozen=True, slots=True)
class TraceStep:
    testcase_id: str
    agent_label: str
    step_index: int
    node_role: NodeRole
    type: StepType
    outcome: StepOutcome
    run_id: str | None = None
    trial: int | None = None
    tool_name: str | None = None
    arguments_valid: bool | None = None
    error_type: str | None = None
    iteration: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None

    def __post_init__(self) -> None:
        if not self.testcase_id or not self.agent_label:
            raise ValueError("testcase_id and agent_label are required")
        if self.step_index < 0:
            raise ValueError("step_index must be non-negative")
        if self.trial is not None and not 1 <= self.trial <= 3:
            raise ValueError("trial must be between 1 and 3")
        for name in ("iteration", "input_tokens", "output_tokens", "latency_ms"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative")

    def model_dump(self, *, mode: str = "python") -> dict[str, Any]:
        if mode not in {"python", "json"}:
            raise ValueError("mode must be python or json")

        def normalize(value: Any) -> Any:
            return value.value if isinstance(value, Enum) else value

        return {
            "testcase_id": self.testcase_id,
            "agent_label": self.agent_label,
            "run_id": self.run_id,
            "trial": self.trial,
            "step_index": self.step_index,
            "node_role": normalize(self.node_role),
            "type": normalize(self.type),
            "outcome": normalize(self.outcome),
            "tool_name": self.tool_name,
            "arguments_valid": self.arguments_valid,
            "error_type": self.error_type,
            "iteration": self.iteration,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
        }
