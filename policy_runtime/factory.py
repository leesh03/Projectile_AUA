"""Composition root for deterministic and real-API Agent modes."""

from __future__ import annotations

import os
import platform
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents.policy_agent.nodes.context_provider import ContextProvider
from agents.policy_agent.nodes.evidence_check import EvidenceChecker
from agents.policy_agent.nodes.graph import PolicyAgentGraph
from agents.policy_agent.nodes.policy_reasoner import PolicyReasoner
from agents.policy_agent.nodes.response_writer import ResponseWriter
from agents.policy_agent.nodes.scaffold_adapters import (
    ReasoningVerifierAdapter,
    SQLRepairAdapter,
    agent_config_from_scaffold,
)
from agents.policy_agent.nodes.sql_executor import SQLExecutor
from agents.policy_agent.nodes.sql_generator import SQLGenerator
from agents.policy_agent.scaffolds.config import AGENT_CONFIG, with_overrides
from agents.policy_agent.scaffolds.reasoning_verifier import verify_once
from agents.policy_agent.scaffolds.sql_repair import repair_once
from policy_runtime.deterministic import (
    DeterministicPolicyModel,
    DeterministicSQLModel,
    DeterministicSQLRepairLLM,
    FaultInjectingPolicyModel,
    FaultInjectingSQLModel,
    PolicyAwareVerifierLLM,
)
from policy_runtime.engine import PolicyEngine
from policy_runtime.multi_provider import (
    GeminiClient,
    GroqClient,
    MultiProviderCoreModel,
    MultiProviderScaffoldLLM,
)
from policy_runtime.openai_provider import (
    OpenAICoreModel,
    OpenAIResponsesClient,
    OpenAIScaffoldLLM,
)
from policy_runtime.prompt_contract import prompt_contract_sha256

ALLOWED_TABLES = ("customers", "orders", "products", "refunds", "shipments")


@dataclass(frozen=True, slots=True)
class AgentBundle:
    graph: PolicyAgentGraph
    policy_engine: PolicyEngine
    mode: str
    provider: str
    model: str | None = None
    db_path: Path | None = None
    agent_label: str = "V0"
    scaffold_config: dict[str, Any] = field(default_factory=dict)
    version_metadata: dict[str, Any] = field(default_factory=dict)
    runtime_metadata: dict[str, Any] = field(default_factory=dict)
    structured_output_retries: int = 1
    sql_strategy: str = "canonical"
    fault_profile: str | None = None
    runtime_api_key: str | None = field(default=None, repr=False, compare=False)


def build_agent(
    root: str | Path,
    *,
    mode: str = "deterministic",
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    db_path: str | Path | None = None,
    agent_label: str = "V0",
    scaffold_overrides: Mapping[str, Any] | None = None,
    version_metadata: Mapping[str, Any] | None = None,
    structured_output_retries: int | None = None,
    sql_strategy: str = "canonical",
    fault_profile: str | None = None,
) -> AgentBundle:
    if not agent_label.strip():
        raise ValueError("agent_label must not be empty")
    if sql_strategy not in {"canonical", "model"}:
        raise ValueError("sql_strategy must be 'canonical' or 'model'")
    if mode == "deterministic" and sql_strategy != "canonical":
        raise ValueError("deterministic mode supports only canonical SQL")
    schema_retries = (
        int(os.getenv("AGENT_SCHEMA_MAX_RETRIES", "1"))
        if structured_output_retries is None
        else structured_output_retries
    )
    if not 0 <= schema_retries <= 2:
        raise ValueError("structured_output_retries must be between 0 and 2")
    project_root = Path(root).resolve()
    configured_db = db_path or os.getenv("POLICY_AGENT_DB_PATH")
    runtime_db_path = (
        Path(configured_db).expanduser().resolve()
        if configured_db
        else project_root / "data" / "shop.db"
    )
    policy_path = project_root / "policies" / "policy_rules.json"
    engine = PolicyEngine.from_path(policy_path)
    context_provider = ContextProvider(
        runtime_db_path,
        policy_path,
        allowed_tables=ALLOWED_TABLES,
    )
    executor = SQLExecutor(runtime_db_path, allowed_tables=ALLOWED_TABLES)
    canonical_sql_model: Any = DeterministicSQLModel()
    if fault_profile in {"sql-typo", "unsafe-delete"}:
        canonical_sql_model = FaultInjectingSQLModel(canonical_sql_model, fault_profile)
    elif fault_profile not in {None, "wrong-policy"}:
        raise ValueError("unsupported fault_profile")

    if mode == "deterministic":
        # SQL repair is intentionally dormant in the deterministic baseline:
        # the fixed plan is already valid.  The real repair scaffold is still
        # integrated and unit-tested, and becomes active in API mode.
        scaffold_config = with_overrides(use_sql_repair=False)
        core_model = None
        sql_model = canonical_sql_model
        policy_model = DeterministicPolicyModel(engine)
        verifier_llm = PolicyAwareVerifierLLM(engine)
        repair_llm = DeterministicSQLRepairLLM()
        sql_repair = None
        selected_provider = "deterministic"
        selected_model = None
        runtime_api_key = None
        provider_runtime: dict[str, Any] = {
            "temperature": None,
            "timeout_seconds": None,
            "transport_max_retries": 0,
            "base_url": None,
        }
    elif mode == "api":
        scaffold_config = dict(AGENT_CONFIG)
        if provider is None or not provider.strip():
            raise ValueError("api mode requires an explicit provider")
        selected_provider = provider.lower().strip()
        if selected_provider == "openai":
            client = OpenAIResponsesClient(api_key=api_key, model=model)
            core_model = OpenAICoreModel(client)
            scaffold_llm = OpenAIScaffoldLLM(client)
        elif selected_provider == "gemini":
            client = GeminiClient(api_key=api_key, model=model)
            core_model = MultiProviderCoreModel(client, provider="gemini")
            scaffold_llm = MultiProviderScaffoldLLM(client, provider="gemini")
        elif selected_provider == "groq":
            client = GroqClient(api_key=api_key, model=model)
            core_model = MultiProviderCoreModel(client, provider="groq")
            scaffold_llm = MultiProviderScaffoldLLM(client, provider="groq")
        else:
            raise ValueError("provider must be 'openai', 'gemini', or 'groq'")
        selected_model = client.model
        runtime_api_key = client.api_key
        provider_runtime = {
            "temperature": 0,
            "timeout_seconds": client.timeout_seconds,
            "transport_max_retries": client.max_retries,
            "base_url": client.base_url,
        }
        # Canonical SQL remains the reproducible default; ``model`` enables a
        # real SQL-generation/Repair experiment with the selected provider.
        policy_model = core_model
        verifier_llm = scaffold_llm
        repair_llm = scaffold_llm
        sql_model = core_model if sql_strategy == "model" else canonical_sql_model
        sql_repair = SQLRepairAdapter(repair_once, repair_llm)
    else:
        raise ValueError("mode must be 'deterministic' or 'api'")

    if fault_profile == "wrong-policy":
        policy_model = FaultInjectingPolicyModel(policy_model)

    if scaffold_overrides:
        scaffold_config = with_overrides(
            **{**scaffold_config, **dict(scaffold_overrides)}
        )

    config = agent_config_from_scaffold(scaffold_config, max_queries=5)
    verifier = (
        ReasoningVerifierAdapter(verify_once, verifier_llm)
        if config.enable_verifier
        else None
    )
    if config.enable_repair and sql_repair is None:
        # The deterministic SQL plan is valid by construction, so this path is
        # normally dormant. Keeping the adapter available lets a deterministic
        # V0/V1 experiment vary the repair limit without changing composition.
        sql_repair = SQLRepairAdapter(repair_once, repair_llm)
    graph = PolicyAgentGraph(
        context_provider=context_provider,
        sql_generator=SQLGenerator(sql_model, max_schema_retries=schema_retries),
        sql_executor=executor,
        evidence_checker=EvidenceChecker(),
        policy_reasoner=PolicyReasoner(
            policy_model,
            max_schema_retries=schema_retries,
        ),
        response_writer=ResponseWriter(),
        config=config,
        sql_repair=sql_repair,
        reasoning_verifier=verifier,
    )
    return AgentBundle(
        graph=graph,
        policy_engine=engine,
        mode=mode,
        provider=selected_provider,
        model=selected_model,
        db_path=runtime_db_path,
        agent_label=agent_label,
        scaffold_config=dict(scaffold_config),
        version_metadata=dict(version_metadata or {}),
        runtime_metadata={
            "contract": "testbed-runtime-v2",
            "mode": mode,
            "provider": selected_provider,
            "model": selected_model,
            "provider_parameters": provider_runtime,
            "structured_output_max_retries": schema_retries,
            "prompt_contract_sha256": prompt_contract_sha256(),
            "python": {
                "implementation": platform.python_implementation(),
                "version": platform.python_version(),
            },
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
            },
            "sqlite_version": sqlite3.sqlite_version,
        },
        structured_output_retries=schema_retries,
        sql_strategy=sql_strategy,
        fault_profile=fault_profile,
        runtime_api_key=runtime_api_key,
    )
