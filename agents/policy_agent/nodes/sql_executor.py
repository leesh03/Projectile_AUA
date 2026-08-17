"""Deterministic SQL guard and read-only SQLite executor."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter_ns
from typing import Any

from agents.policy_agent.nodes.sql_generator import SQLPlan
from agents.policy_agent.nodes.state import PolicyAgentState


class SQLGuardError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.category = "SAFETY_POLICY_VIOLATION"


class SQLExecutionError(RuntimeError):
    """Raised for a database failure after SQL passes the safety guard."""

    def __init__(self, message: str, *, code: str = "DB_RUNTIME_ERROR") -> None:
        super().__init__(message)
        self.code = code
        self.category = "REPAIRABLE_SQL_ERROR"


@dataclass(frozen=True, slots=True)
class QueryResult:
    rows: tuple[dict[str, Any], ...]
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class QueryBatchResult:
    results: dict[str, tuple[dict[str, Any], ...]]
    truncated_queries: tuple[str, ...] = ()


class SQLGuard:
    """Reject unsafe SQL before it reaches SQLite.

    A second defense layer in ``SQLExecutor`` uses SQLite's authorizer to deny
    writes and reads from tables outside the allow-list.
    """

    _COMMENT_PATTERN = re.compile(r"--|/\*|\*/", re.MULTILINE)
    _SELECT_PATTERN = re.compile(r"^\s*SELECT\b", re.IGNORECASE)
    _FORBIDDEN_PATTERN = re.compile(
        r"\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|"
        r"VACUUM|PRAGMA|REINDEX|ANALYZE|TRIGGER|LOAD_EXTENSION)\b",
        re.IGNORECASE,
    )

    def __init__(self, allowed_tables: Iterable[str]) -> None:
        self.allowed_tables = frozenset(table.strip() for table in allowed_tables if table.strip())
        if not self.allowed_tables:
            raise ValueError("allowed_tables must not be empty")

    @staticmethod
    def _mask_string_literals(sql: str) -> str:
        result: list[str] = []
        index = 0
        quote: str | None = None
        while index < len(sql):
            char = sql[index]
            if quote is None and char in {"'", '"'}:
                quote = char
                result.append(" ")
            elif quote is not None:
                result.append(" ")
                if char == quote:
                    if index + 1 < len(sql) and sql[index + 1] == quote:
                        result.append(" ")
                        index += 1
                    else:
                        quote = None
            else:
                result.append(char)
            index += 1
        if quote is not None:
            raise SQLGuardError("UNTERMINATED_STRING", "SQL contains an unterminated string")
        return "".join(result)

    def validate(self, sql: str) -> str:
        if not isinstance(sql, str) or not sql.strip():
            raise SQLGuardError("EMPTY_SQL", "SQL must not be empty")
        normalized = sql.strip()
        if self._COMMENT_PATTERN.search(normalized):
            raise SQLGuardError("COMMENTS_NOT_ALLOWED", "SQL comments are not allowed")

        without_trailing_semicolon = normalized[:-1].rstrip() if normalized.endswith(";") else normalized
        if ";" in without_trailing_semicolon:
            raise SQLGuardError("MULTIPLE_STATEMENTS", "only one SQL statement is allowed")

        masked = self._mask_string_literals(without_trailing_semicolon)
        if not self._SELECT_PATTERN.match(masked):
            raise SQLGuardError("NON_SELECT", "only SELECT statements are allowed")
        forbidden = self._FORBIDDEN_PATTERN.search(masked)
        if forbidden:
            raise SQLGuardError(
                "FORBIDDEN_KEYWORD",
                f"forbidden SQL keyword: {forbidden.group(0).upper()}",
            )
        return without_trailing_semicolon


class SQLExecutor:
    def __init__(
        self,
        db_path: str | Path,
        *,
        allowed_tables: Iterable[str],
        max_rows: int = 200,
        max_query_steps: int = 100_000,
        max_execution_ms: int = 5_000,
    ) -> None:
        self.db_path = Path(db_path).resolve()
        if max_rows <= 0:
            raise ValueError("max_rows must be positive")
        if max_query_steps <= 0:
            raise ValueError("max_query_steps must be positive")
        if max_execution_ms <= 0:
            raise ValueError("max_execution_ms must be positive")
        self.max_rows = max_rows
        self.max_query_steps = max_query_steps
        self.max_execution_ms = max_execution_ms
        self.guard = SQLGuard(allowed_tables)

    def config_dict(self) -> dict[str, int]:
        return {
            "max_rows_per_query": self.max_rows,
            "max_query_steps": self.max_query_steps,
            "max_execution_ms": self.max_execution_ms,
        }

    def _connect_read_only(self) -> sqlite3.Connection:
        if not self.db_path.is_file():
            raise SQLExecutionError(f"database file does not exist: {self.db_path}")
        uri = f"{self.db_path.as_uri()}?mode=ro"
        try:
            connection = sqlite3.connect(uri, uri=True)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            return connection
        except sqlite3.Error as exc:
            raise SQLExecutionError(f"failed to open database: {exc}") from exc

    def execute(self, sql: str, parameters: Sequence[Any] = ()) -> QueryResult:
        safe_sql = self.guard.validate(sql)
        denied_reason: list[str] = []
        resource_limit_reached = False
        progress_interval = min(1_000, self.max_query_steps)
        executed_steps = 0
        deadline_ns = perf_counter_ns() + self.max_execution_ms * 1_000_000

        def check_resource_limit() -> int:
            nonlocal executed_steps, resource_limit_reached
            executed_steps += progress_interval
            if executed_steps >= self.max_query_steps or perf_counter_ns() >= deadline_ns:
                resource_limit_reached = True
                return 1
            return 0

        allowed_action_codes = {
            sqlite3.SQLITE_SELECT,
            sqlite3.SQLITE_READ,
            sqlite3.SQLITE_FUNCTION,
        }
        recursive_code = getattr(sqlite3, "SQLITE_RECURSIVE", None)
        if recursive_code is not None:
            allowed_action_codes.add(recursive_code)

        def authorize(
            action_code: int,
            arg1: str | None,
            arg2: str | None,
            database_name: str | None,
            trigger_name: str | None,
        ) -> int:
            del arg2, database_name, trigger_name
            if action_code == sqlite3.SQLITE_READ:
                if arg1 not in self.guard.allowed_tables:
                    denied_reason.append(f"table is not allowed: {arg1}")
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            if action_code in allowed_action_codes:
                return sqlite3.SQLITE_OK
            denied_reason.append(f"SQLite action is not allowed: {action_code}")
            return sqlite3.SQLITE_DENY

        try:
            with closing(self._connect_read_only()) as connection:
                connection.set_authorizer(authorize)
                connection.set_progress_handler(check_resource_limit, progress_interval)
                cursor = connection.execute(safe_sql, tuple(parameters))
                fetched = cursor.fetchmany(self.max_rows + 1)
        except sqlite3.Error as exc:
            if denied_reason:
                raise SQLGuardError("SQLITE_AUTH_DENIED", denied_reason[0]) from exc
            if resource_limit_reached:
                raise SQLExecutionError(
                    "SQL execution exceeded the configured resource limit",
                    code="QUERY_RESOURCE_LIMIT",
                ) from exc
            raise SQLExecutionError(f"SQL execution failed: {exc}") from exc

        truncated = len(fetched) > self.max_rows
        rows = tuple(dict(row) for row in fetched[: self.max_rows])
        return QueryResult(rows=rows, truncated=truncated)

    def execute_plan(self, plan: SQLPlan) -> QueryBatchResult:
        results: dict[str, tuple[dict[str, Any], ...]] = {}
        truncated: list[str] = []
        for query in plan.queries:
            result = self.execute(query.sql, query.parameters)
            results[query.name] = result.rows
            if result.truncated:
                truncated.append(query.name)
        return QueryBatchResult(results=results, truncated_queries=tuple(truncated))

    def __call__(self, state: PolicyAgentState) -> QueryBatchResult:
        if state.query_plan is None:
            raise SQLExecutionError("query_plan is missing")
        batch = self.execute_plan(state.query_plan)
        state.query_results = {
            name: list(rows) for name, rows in batch.results.items()
        }
        state.rows_truncated = bool(batch.truncated_queries)
        return batch
