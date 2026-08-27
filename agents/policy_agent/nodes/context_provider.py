"""Load read-only database schema and Agent-visible policy context."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.policy_agent.nodes.state import PolicyAgentState


class ContextProviderError(RuntimeError):
    """Raised when required local context cannot be loaded."""


@dataclass(frozen=True, slots=True)
class ContextBundle:
    database_schema: dict[str, tuple[dict[str, Any], ...]]
    policy_text: str
    allowed_tables: tuple[str, ...]
    policy_evidence_contracts: dict[str, tuple[str, ...]]
    database_filename: str
    database_sha256: str
    policy_filename: str
    policy_sha256: str
    policy_version: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "database_schema": self.database_schema,
            "policy_text": self.policy_text,
            "allowed_tables": list(self.allowed_tables),
            "policy_evidence_contracts": {
                key: list(paths) for key, paths in self.policy_evidence_contracts.items()
            },
            "database_filename": self.database_filename,
            "database_sha256": self.database_sha256,
            "policy_filename": self.policy_filename,
            "policy_sha256": self.policy_sha256,
            "policy_version": self.policy_version,
        }


class ContextProvider:
    """Provide system-controlled schema, policy, and artifact provenance."""

    def __init__(
        self,
        db_path: str | Path,
        policy_path: str | Path,
        *,
        allowed_tables: Iterable[str],
    ) -> None:
        self.db_path = Path(db_path).resolve()
        self.policy_path = Path(policy_path).resolve()
        self.allowed_tables = frozenset(table.strip() for table in allowed_tables if table.strip())
        if not self.allowed_tables:
            raise ValueError("allowed_tables must not be empty")

    @staticmethod
    def _quote_identifier(identifier: str) -> str:
        return '"' + identifier.replace('"', '""') + '"'

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise ContextProviderError(f"failed to hash artifact {path.name}: {exc}") from exc
        return digest.hexdigest()

    def _connect_read_only(self) -> sqlite3.Connection:
        if not self.db_path.is_file():
            raise ContextProviderError(f"database file does not exist: {self.db_path}")
        uri = f"{self.db_path.as_uri()}?mode=ro"
        try:
            return sqlite3.connect(uri, uri=True)
        except sqlite3.Error as exc:
            raise ContextProviderError(f"failed to open database: {exc}") from exc

    def _load_schema(self) -> dict[str, tuple[dict[str, Any], ...]]:
        schema: dict[str, tuple[dict[str, Any], ...]] = {}
        with closing(self._connect_read_only()) as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            existing_tables = {str(row[0]) for row in rows}
            missing = sorted(self.allowed_tables - existing_tables)
            if missing:
                raise ContextProviderError(f"allowed tables are missing from database: {missing}")

            for table in sorted(self.allowed_tables):
                pragma = f"PRAGMA table_info({self._quote_identifier(table)})"
                columns = connection.execute(pragma).fetchall()
                schema[table] = tuple(
                    {
                        "name": column[1],
                        "type": column[2],
                        "not_null": bool(column[3]),
                        "default": column[4],
                        "primary_key": bool(column[5]),
                    }
                    for column in columns
                )
        return schema

    @staticmethod
    def _normalize_required_paths(clause_id: str, raw: Any) -> tuple[str, ...]:
        if isinstance(raw, Mapping):
            raw = raw.get("required_paths", [])
        if not isinstance(raw, (list, tuple)):
            raise ContextProviderError(
                f"policy evidence contract for {clause_id} must be an array"
            )
        paths: list[str] = []
        for path in raw:
            if not isinstance(path, str) or not path.startswith("/"):
                raise ContextProviderError(
                    f"policy evidence path for {clause_id} must be a JSON Pointer"
                )
            if path not in paths:
                paths.append(path)
        return tuple(paths)

    @classmethod
    def _parse_policy_metadata(
        cls, policy_text: str
    ) -> tuple[str | None, dict[str, tuple[str, ...]]]:
        try:
            parsed = json.loads(policy_text)
        except json.JSONDecodeError:
            return None, {}
        if not isinstance(parsed, Mapping):
            return None, {}

        raw_version = parsed.get("policy_version", parsed.get("version"))
        policy_version = str(raw_version) if raw_version is not None else None
        contracts: dict[str, tuple[str, ...]] = {}

        raw_contracts = parsed.get("evidence_contracts")
        if raw_contracts is not None:
            if not isinstance(raw_contracts, Mapping):
                raise ContextProviderError("policy evidence_contracts must be an object")
            for clause_id, raw in raw_contracts.items():
                contracts[str(clause_id)] = cls._normalize_required_paths(str(clause_id), raw)

        raw_clauses = parsed.get("clauses")
        if isinstance(raw_clauses, Mapping):
            for clause_id, raw in raw_clauses.items():
                if isinstance(raw, Mapping) and "required_paths" in raw:
                    contracts[str(clause_id)] = cls._normalize_required_paths(str(clause_id), raw)
        elif isinstance(raw_clauses, list):
            for raw in raw_clauses:
                if not isinstance(raw, Mapping) or "required_paths" not in raw:
                    continue
                clause_id = raw.get("clause_id", raw.get("id"))
                if not isinstance(clause_id, str) or not clause_id.strip():
                    raise ContextProviderError("policy clause with required_paths needs clause_id")
                contracts[clause_id] = cls._normalize_required_paths(clause_id, raw)

        # Also accept the compact {"POL-X": {"required_paths": [...]}} shape.
        for clause_id, raw in parsed.items():
            if isinstance(raw, Mapping) and "required_paths" in raw:
                contracts[str(clause_id)] = cls._normalize_required_paths(str(clause_id), raw)

        return policy_version, contracts

    def load(self) -> ContextBundle:
        if not self.policy_path.is_file():
            raise ContextProviderError(f"policy file does not exist: {self.policy_path}")
        try:
            policy_text = self.policy_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ContextProviderError(f"failed to read policy file: {exc}") from exc
        if not policy_text:
            raise ContextProviderError("policy file is empty")

        policy_version, contracts = self._parse_policy_metadata(policy_text)
        try:
            parsed_policy = json.loads(policy_text)
        except json.JSONDecodeError:
            agent_policy_text = policy_text
        else:
            agent_policy_text = json.dumps(
                parsed_policy,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        return ContextBundle(
            database_schema=self._load_schema(),
            policy_text=agent_policy_text,
            allowed_tables=tuple(sorted(self.allowed_tables)),
            policy_evidence_contracts=contracts,
            database_filename=self.db_path.name,
            database_sha256=self._sha256_file(self.db_path),
            policy_filename=self.policy_path.name,
            policy_sha256=self._sha256_file(self.policy_path),
            policy_version=policy_version,
        )

    def __call__(self, state: PolicyAgentState) -> ContextBundle:
        bundle = self.load()
        state.context.update(bundle.as_dict())
        return bundle
