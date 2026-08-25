"""Composition root for deterministic and real-API Agent modes."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

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
    PolicyAwareVerifierLLM,
)
from policy_runtime.engine import PolicyEngine
from policy_runtime.fixtures import FixtureFactsAdapter
from policy_runtime.openai_provider import (
    OpenAICoreModel,
    OpenAIResponsesClient,
    OpenAIScaffoldLLM,
)
from policy_runtime.multi_provider import (
    GeminiClient,
    GroqClient,
    MultiProviderCoreModel,
    MultiProviderScaffoldLLM,
)

ALLOWED_TABLES = ("customers", "orders", "products", "refunds", "shipments")


@dataclass(frozen=True, slots=True)
class AgentBundle:
    graph: PolicyAgentGraph
    policy_engine: PolicyEngine
    mode: str
    provider: str
    model: str | None = None
    runtime_api_key: str | None = field(default=None, repr=False, compare=False)


def build_agent(
    root: str | Path,
    *,
    mode: str = "deterministic",
    provider: str = "openai",
    api_key: str | None = None,
    model: str | None = None,
) -> AgentBundle:
    project_root = Path(root).resolve()
    db_path = project_root / "data" / "shop.db"
    policy_path = project_root / "policies" / "policy_rules.json"
    fixture_path = project_root / "data" / "adapter_fixtures.json"
    engine = PolicyEngine.from_path(policy_path)
    context_provider = ContextProvider(
        db_path,
        policy_path,
        allowed_tables=ALLOWED_TABLES,
    )
    executor = SQLExecutor(db_path, allowed_tables=ALLOWED_TABLES)
    facts_adapter = FixtureFactsAdapter(fixture_path) if fixture_path.is_file() else None

    if mode == "deterministic":
        # SQL repair is intentionally dormant in the deterministic baseline:
        # the fixed plan is already valid.  The real repair scaffold is still
        # integrated and unit-tested, and becomes active in API mode.
        scaffold_config = with_overrides(use_sql_repair=False)
        core_model = None
        sql_model = DeterministicSQLModel()
        policy_model = DeterministicPolicyModel(engine)
        verifier_llm = PolicyAwareVerifierLLM(engine)
        sql_repair = None
        selected_provider = "deterministic"
        selected_model = None
        runtime_api_key = None
    elif mode == "api":
        scaffold_config = dict(AGENT_CONFIG)
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
        # The compact shop schema has one stable five-query evidence contract.
        # Use its canonical parameterized plan in API mode as well: the LLM is
        # still responsible for policy reasoning and verification, while SQL
        # shape/aliases remain complete, reproducible, and injection-resistant.
        sql_model = DeterministicSQLModel()
        policy_model = core_model
        verifier_llm = scaffold_llm
        sql_repair = SQLRepairAdapter(repair_once, scaffold_llm)
    else:
        raise ValueError("mode must be 'deterministic' or 'api'")

    config = agent_config_from_scaffold(scaffold_config, max_queries=5)
    verifier = ReasoningVerifierAdapter(verify_once, verifier_llm)
    graph = PolicyAgentGraph(
        context_provider=context_provider,
        sql_generator=SQLGenerator(sql_model),
        sql_executor=executor,
        evidence_checker=EvidenceChecker(),
        policy_reasoner=PolicyReasoner(policy_model),
        response_writer=ResponseWriter(),
        config=config,
        sql_repair=sql_repair,
        reasoning_verifier=verifier,
        facts_adapter=facts_adapter,
    )
    return AgentBundle(
        graph=graph,
        policy_engine=engine,
        mode=mode,
        provider=selected_provider,
        model=selected_model,
        runtime_api_key=runtime_api_key,
    )
