"""Model-independent providers used for local integration and regression tests."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from agents.policy_agent.nodes.state import ProviderResult, ProviderUsage
from agents.policy_agent.scaffolds.llm import LLMResult
from policy_runtime.engine import InputContractError, PolicyEngine


class DeterministicSQLModel:
    """Create the five canonical read-only queries without an LLM."""

    def generate_sql(self, payload: Mapping[str, Any]) -> ProviderResult:
        request = payload["trusted_request"]
        order_item_id = request["order_item_id"]
        schema = payload.get("database_schema", {})

        def columns(table: str) -> set[str]:
            raw_columns = schema.get(table, ()) if isinstance(schema, Mapping) else ()
            return {
                str(column.get("name"))
                for column in raw_columns
                if isinstance(column, Mapping) and column.get("name") is not None
            }

        # The regression DB uses independent lookup rows so missing, duplicate,
        # and mismatched snapshots can be represented through SQL alone.  The
        # legacy profile keeps compatibility with the original strict shop DB.
        regression_profile = {
            "lookup_order_item_id",
            "record_present",
        }.issubset(columns("orders"))
        if regression_profile:
            order_sql = (
                "SELECT record_present AS _record_present, order_id, order_item_id, "
                "customer_id, product_id, order_snapshot_id, ordered_at, "
                "status AS order_status, paid_item_amount, currency FROM orders "
                "WHERE lookup_order_item_id = ?"
            )
            customer_sql = (
                "SELECT record_present AS _record_present, customer_id, "
                "order_snapshot_id, tier AS customer_tier_at_order, snapshotted_at "
                "FROM customers WHERE lookup_order_item_id = ?"
            )
            product_sql = (
                "SELECT record_present AS _record_present, product_id, "
                "order_snapshot_id, category, final_sale, snapshotted_at "
                "FROM products WHERE lookup_order_item_id = ?"
            )
            shipment_sql = (
                "SELECT record_present AS _record_present, shipment_id, order_item_id, "
                "delivered_at, package_opened, issue_code, "
                "evidence_status AS evidence__evidence_status, "
                "verified_by AS evidence__verified_by, "
                "verified_at AS evidence__verified_at, "
                "evidence_source AS evidence__evidence_source, "
                "attested AS evidence__provenance_attested FROM shipments "
                "WHERE lookup_order_item_id = ? ORDER BY shipment_id"
            )
        else:
            order_sql = (
                "SELECT order_id, order_item_id, customer_id, product_id, "
                "order_snapshot_id, ordered_at, status AS order_status, "
                "paid_item_amount, currency FROM orders WHERE order_item_id = ?"
            )
            customer_sql = (
                "SELECT customer_id, order_snapshot_id, "
                "customer_tier_at_order, ordered_at AS snapshotted_at "
                "FROM orders WHERE order_item_id = ?"
            )
            product_sql = (
                "SELECT product_id, order_snapshot_id, "
                "product_category_at_order AS category, "
                "product_final_sale_at_order AS final_sale, "
                "ordered_at AS snapshotted_at FROM orders WHERE order_item_id = ?"
            )
            shipment_sql = (
                "SELECT shipment_id, order_item_id, delivered_at, package_opened, issue_code, "
                "evidence_status AS evidence__evidence_status, "
                "verified_by AS evidence__verified_by, "
                "verified_at AS evidence__verified_at, "
                "evidence_source AS evidence__evidence_source, "
                "attested AS evidence__provenance_attested "
                "FROM shipments WHERE order_item_id = ? ORDER BY shipment_id"
            )

        queries = [
            {
                "name": "order",
                "sql": order_sql,
                "parameters": [order_item_id],
            },
            {
                "name": "customer_snapshot",
                "sql": customer_sql,
                "parameters": [order_item_id],
            },
            {
                "name": "product",
                "sql": product_sql,
                "parameters": [order_item_id],
            },
            {
                "name": "shipment",
                "sql": shipment_sql,
                "parameters": [order_item_id],
            },
            {
                "name": "refund_history",
                "sql": (
                    "SELECT refund_id, order_item_id, status, amount, currency "
                    "FROM refunds WHERE order_item_id = ? ORDER BY refund_id"
                ),
                "parameters": [order_item_id],
            },
        ]
        return ProviderResult(
            output={"queries": queries},
            usage=ProviderUsage(),
            provider="local-deterministic",
            model_id="sql-plan-v1",
            finish_reason="stop",
        )


class FaultInjectingSQLModel:
    """Inject a reproducible SQL failure for Repair ON/OFF experiments."""

    def __init__(self, base: DeterministicSQLModel, profile: str) -> None:
        if profile not in {"sql-typo", "unsafe-delete"}:
            raise ValueError("SQL fault profile must be 'sql-typo' or 'unsafe-delete'")
        self.base = base
        self.profile = profile

    def generate_sql(self, payload: Mapping[str, Any]) -> ProviderResult:
        result = self.base.generate_sql(payload)
        output = dict(result.output) if isinstance(result.output, Mapping) else {}
        raw_queries = output.get("queries")
        if not isinstance(raw_queries, list) or not raw_queries:
            return result
        queries = [dict(query) for query in raw_queries]
        first_sql = str(queries[0].get("sql", ""))
        if self.profile == "sql-typo":
            queries[0]["sql"] = re.sub(r"\sFROM\s", " FORM ", first_sql, count=1)
        else:
            queries[0]["sql"] = "DELETE FROM orders"
            queries[0]["parameters"] = []
        output["queries"] = queries
        return ProviderResult(
            output=output,
            usage=result.usage,
            provider="local-fault-injection",
            model_id=f"{result.model_id}+{self.profile}",
            finish_reason=result.finish_reason,
        )


class DeterministicSQLRepairLLM:
    """Repair the bounded ``sql-typo`` profile without using Gold data."""

    _FAILED_SQL = re.compile(r"\[실패한 SQL\]\n(.*?)\n\n\[오류\]", re.DOTALL)

    def __init__(self) -> None:
        self.call_count = 0

    def __call__(self, prompt: str) -> LLMResult:
        self.call_count += 1
        match = self._FAILED_SQL.search(prompt)
        failed = match.group(1).strip() if match else ""
        repaired = re.sub(r"\sFORM\s", " FROM ", failed, count=1, flags=re.IGNORECASE)
        return LLMResult(text=repaired, input_tokens=0, output_tokens=0)


class DeterministicPolicyModel:
    """Expose the MD-based policy engine through Jun-won's ReasoningModel contract."""

    def __init__(self, engine: PolicyEngine) -> None:
        self.engine = engine

    def reason(self, payload: Mapping[str, Any]) -> ProviderResult:
        result = self.engine.evaluate(payload["trusted_facts"])
        output = {
            "decision": result.decision,
            "clauses": result.value["matched_clauses"],
            "rationale": self.engine.rationale(result),
            "confidence": 1.0,
        }
        return ProviderResult(
            output=output,
            usage=ProviderUsage(),
            provider="local-deterministic",
            model_id="policy-engine-v1",
            finish_reason="stop",
        )


class FaultInjectingPolicyModel:
    """Produce a reproducible policy regression without touching Gold data."""

    def __init__(self, base: Any) -> None:
        self.base = base

    def reason(self, payload: Mapping[str, Any]) -> ProviderResult:
        result = self.base.reason(payload)
        if not isinstance(result.output, Mapping):
            return result
        output = dict(result.output)
        current = output.get("decision")
        output["decision"] = "REJECT" if current == "APPROVE" else "APPROVE"
        output["rationale"] = "fault-injection: deliberately incorrect policy decision"
        return ProviderResult(
            output=output,
            usage=result.usage,
            provider=result.provider,
            model_id=f"{result.model_id or 'unknown'}+wrong-policy",
            finish_reason=result.finish_reason,
            latency_ms=result.latency_ms,
            provider_request_id=result.provider_request_id,
        )


class PolicyAwareVerifierLLM:
    """Run Chae-rin's real verify_once path without an external API.

    The class receives the textual verifier prompt, extracts only the supplied
    facts and decision, and checks them against the independent local engine.
    It does not query the database or inspect Gold answers.
    """

    _FACTS = re.compile(r"\[조회된 사실\]\n(.*?)\n\n\[판정\]", re.DOTALL)
    _DECISION = re.compile(r"\[판정\]\n(.*?)\n\n\[적용한 조항\]", re.DOTALL)
    _CLAUSES = re.compile(r"\[적용한 조항\]\n(.*?)\n\n\[판정 근거\]", re.DOTALL)

    def __init__(self, engine: PolicyEngine) -> None:
        self.engine = engine
        self.call_count = 0

    def __call__(self, prompt: str) -> LLMResult:
        self.call_count += 1
        issues: list[str] = []
        facts_match = self._FACTS.search(prompt)
        decision_match = self._DECISION.search(prompt)
        clauses_match = self._CLAUSES.search(prompt)
        if not facts_match or not decision_match or not clauses_match:
            issues.append("검증 프롬프트에서 사실·판정·조항을 읽을 수 없습니다")
        else:
            try:
                facts = json.loads(facts_match.group(1).strip())
                expected = self.engine.evaluate(facts)
                actual_decision = decision_match.group(1).strip()
                actual_clauses = {
                    line[2:].strip()
                    for line in clauses_match.group(1).splitlines()
                    if line.strip().startswith("- ")
                }
                if actual_decision != expected.decision:
                    issues.append(
                        f"판정 불일치: 현재 {actual_decision}, 정책 기준 {expected.decision}"
                    )
                expected_clauses = set(expected.value["matched_clauses"])
                if actual_clauses != expected_clauses:
                    missing = sorted(expected_clauses - actual_clauses)
                    extra = sorted(actual_clauses - expected_clauses)
                    if missing:
                        issues.append(f"누락 조항: {', '.join(missing)}")
                    if extra:
                        issues.append(f"잘못 적용한 조항: {', '.join(extra)}")
            except (json.JSONDecodeError, InputContractError, KeyError, TypeError) as exc:
                issues.append(f"검증 입력 오류: {exc}")
        text = json.dumps(
            {"status": "FAIL" if issues else "PASS", "issues": issues},
            ensure_ascii=False,
        )
        return LLMResult(text=text, input_tokens=0, output_tokens=0)
