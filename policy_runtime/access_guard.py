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
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit


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
_PATH_EVENTS = frozenset(
    {
        "open",
        "os.chdir",
        "os.link",
        "os.listdir",
        "os.mkdir",
        "os.remove",
        "os.rename",
        "os.replace",
        "os.rmdir",
        "os.scandir",
        "os.symlink",
        "os.truncate",
        "os.unlink",
        "sqlite3.connect",
    }
)
_TWO_PATH_EVENTS = frozenset({"os.link", "os.rename", "os.replace", "os.symlink"})
_WINDOWS_URI_PATH = re.compile(r"^/[A-Za-z]:/")


def _path_from_value(raw_path: Any) -> Path | None:
    if isinstance(raw_path, int) or raw_path is None:
        return None
    try:
        value = os.fsdecode(raw_path)
    except TypeError:
        return None
    if not value:
        return None
    if value.casefold().startswith("file:"):
        parsed = urlsplit(value)
        if parsed.scheme.casefold() != "file" or parsed.netloc not in {"", "localhost"}:
            raise AgentAccessViolation("Agent access denied for non-local file URI")
        value = unquote(parsed.path)
        if os.name == "nt" and _WINDOWS_URI_PATH.match(value):
            value = value[1:]
    return Path(value)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _identity(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_dev, stat.st_ino


def _blocked_identities(roots: tuple[Path, ...]) -> frozenset[tuple[int, int]]:
    identities: set[tuple[int, int]] = set()
    relative_candidates = (
        Path("data") / "answer_key.db",
        Path("data") / "test_cases.json",
        Path("evaluation") / "private" / "expected_cases.json",
        Path("policies") / "policy_oracle.py",
    )
    for root in roots:
        for relative in relative_candidates:
            value = _identity(root / relative)
            if value is not None:
                identities.add(value)
    return frozenset(identities)


@dataclass(frozen=True, slots=True)
class _GuardPolicy:
    project_root: Path
    trusted_runtime_roots: tuple[Path, ...]
    blocked_roots: tuple[Path, ...]
    blocked_identities: frozenset[tuple[int, int]]

    def check_path(self, raw_path: Any, *, event: str) -> None:
        path = _path_from_value(raw_path)
        if path is None:
            return
        try:
            resolved = path.resolve(strict=False)
        except (OSError, RuntimeError):
            resolved = Path(os.path.abspath(os.fspath(path)))
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
            or (
                any(_is_relative_to(resolved, root) for root in self.blocked_roots)
                and not any(
                    _is_relative_to(resolved, root)
                    for root in self.trusted_runtime_roots
                )
            )
            or _identity(resolved) in self.blocked_identities
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
    if event in _PATH_EVENTS and args:
        policy.check_path(args[0], event=event)
    if event in _TWO_PATH_EVENTS and len(args) > 1:
        policy.check_path(args[1], event=event)


def install_audit_hook() -> None:
    global _AUDIT_INSTALLED
    if _AUDIT_INSTALLED:
        return
    import sys

    sys.addaudithook(_audit_hook)
    _AUDIT_INSTALLED = True


@contextmanager
def agent_execution_guard(
    project_root: str | Path,
    *,
    blocked_roots: tuple[str | Path, ...] = (),
) -> Iterator[None]:
    """Activate the Agent-only deny policy for the current execution context."""

    install_audit_hook()
    root = Path(project_root).resolve()
    denied = tuple(Path(path).resolve() for path in blocked_roots)
    identities = _blocked_identities((root, *denied))
    trusted_runtime_roots = tuple(
        dict.fromkeys(
            (
                root,
                Path(sys.prefix).resolve(),
                Path(sys.base_prefix).resolve(),
            )
        )
    )
    token = _ACTIVE_POLICY.set(
        _GuardPolicy(root, trusted_runtime_roots, denied, identities)
    )
    try:
        yield
    finally:
        _ACTIVE_POLICY.reset(token)

