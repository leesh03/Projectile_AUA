"""Fail-closed file-access boundary for the Agent subprocess.

The evaluator may read Gold and Oracle artifacts, but the Agent must not.  A
Python audit hook is process-wide and cannot be removed by ordinary Agent code;
the context variable activates it only while the isolated worker builds and
runs the Agent.  The worker also blocks child-process creation so a model/tool
cannot bypass the file guard through an external command.
"""

from __future__ import annotations

import contextvars
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


class AgentAccessViolation(PermissionError):
    """Raised when Agent-side code tries to access evaluator-only assets."""


_BLOCKED_FILENAMES = frozenset(
    {
        "answer_key.db",
        "expected_cases.json",
        "policy_oracle.py",
        "test_cases.json",
    }
)
_BLOCKED_DIRECTORY_NAMES = frozenset({"gpt_정책", "정우혁"})
_PROCESS_EVENTS = frozenset(
    {
        "os.system",
        "os.posix_spawn",
        "os.spawn",
        "subprocess.Popen",
    }
)


@dataclass(frozen=True, slots=True)
class _GuardPolicy:
    project_root: Path

    def check_path(self, raw_path: Any, *, event: str) -> None:
        if isinstance(raw_path, int) or raw_path is None:
            return
        try:
            value = os.fsdecode(raw_path)
        except TypeError:
            return
        if not value:
            return
        path = Path(value)
        try:
            resolved = path.resolve(strict=False)
        except (OSError, RuntimeError):
            resolved = Path(os.path.abspath(value))
        parts = tuple(part.casefold() for part in resolved.parts)
        name = resolved.name.casefold()
        contains_private_evaluation = any(
            parts[index : index + 2] == ("evaluation", "private")
            for index in range(max(0, len(parts) - 1))
        )
        if (
            name in _BLOCKED_FILENAMES
            or contains_private_evaluation
            or any(part in _BLOCKED_DIRECTORY_NAMES for part in parts)
        ):
            raise AgentAccessViolation(
                f"Agent access denied by gold/oracle isolation policy: {event}:{name or '[directory]'}"
            )


_ACTIVE_POLICY: contextvars.ContextVar[_GuardPolicy | None] = contextvars.ContextVar(
    "policy_agent_access_guard", default=None
)
_AUDIT_INSTALLED = False


def _audit_hook(event: str, args: tuple[Any, ...]) -> None:
    policy = _ACTIVE_POLICY.get()
    if policy is None:
        return
    if event in _PROCESS_EVENTS:
        raise AgentAccessViolation(
            f"Agent child-process execution denied by isolation policy: {event}"
        )
    if event in {"open", "os.listdir", "os.scandir", "os.chdir", "sqlite3.connect"}:
        if args:
            policy.check_path(args[0], event=event)


def install_audit_hook() -> None:
    global _AUDIT_INSTALLED
    if _AUDIT_INSTALLED:
        return
    import sys

    sys.addaudithook(_audit_hook)
    _AUDIT_INSTALLED = True


@contextmanager
def agent_execution_guard(project_root: str | Path) -> Iterator[None]:
    """Activate the Agent-only deny policy for the current execution context."""

    install_audit_hook()
    root = Path(project_root).resolve()
    token = _ACTIVE_POLICY.set(_GuardPolicy(root))
    try:
        yield
    finally:
        _ACTIVE_POLICY.reset(token)

