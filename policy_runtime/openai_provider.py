"""Dependency-free OpenAI Responses API adapters.

Only ``OPENAI_API_KEY`` is required.  ``OPENAI_MODEL`` defaults to the model
shown in the current official Responses API examples; endpoint and timeout are
overridable for compatible gateways.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from agents.policy_agent.nodes.state import ProviderResult, ProviderUsage
from agents.policy_agent.scaffolds.llm import LLMResult
from policy_runtime.prompt_contract import (
    POLICY_DEVELOPER_INSTRUCTION,
    SQL_DEVELOPER_INSTRUCTION,
    SQL_REPAIR_DEVELOPER_INSTRUCTION,
    VERIFIER_DEVELOPER_INSTRUCTION,
)


class OpenAIProviderError(RuntimeError):
    """A sanitized API, transport, or response-contract error."""


@dataclass(frozen=True, slots=True)
class _APIResult:
    text: str
    usage: ProviderUsage
    response_id: str | None
    status: str | None
    latency_ms: int


class OpenAIResponsesClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: int | None = None,
        max_retries: int = 2,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        if not self.api_key:
            raise OpenAIProviderError("OPENAI_API_KEY is not set")
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-5.2")
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.timeout_seconds = timeout_seconds or int(os.getenv("OPENAI_TIMEOUT_SECONDS", "120"))
        self.max_retries = max_retries
        if self.timeout_seconds <= 0 or self.max_retries < 0:
            raise ValueError("timeout must be positive and max_retries non-negative")

    @staticmethod
    def _extract_text(data: Mapping[str, Any]) -> str:
        direct = data.get("output_text")
        if isinstance(direct, str) and direct:
            return direct
        parts: list[str] = []
        output = data.get("output", [])
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, Mapping):
                    continue
                content = item.get("content", [])
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, Mapping):
                        continue
                    if block.get("type") in {"output_text", "text"} and isinstance(block.get("text"), str):
                        parts.append(block["text"])
                    elif block.get("type") == "refusal" and isinstance(block.get("refusal"), str):
                        raise OpenAIProviderError(f"model refused the request: {block['refusal'][:160]}")
        if not parts:
            raise OpenAIProviderError("Responses API returned no output text")
        return "".join(parts)

    def _request(self, body: Mapping[str, Any]) -> _APIResult:
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/responses",
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        retry_statuses = {408, 409, 429, 500, 502, 503, 504}
        started = time.perf_counter_ns()
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    raw = response.read()
                    data = json.loads(raw.decode("utf-8"))
                    if not isinstance(data, Mapping):
                        raise OpenAIProviderError("Responses API payload is not an object")
                    usage_raw = data.get("usage", {})
                    if not isinstance(usage_raw, Mapping):
                        usage_raw = {}
                    usage = ProviderUsage(
                        input_tokens=int(usage_raw.get("input_tokens", 0) or 0),
                        output_tokens=int(usage_raw.get("output_tokens", 0) or 0),
                        total_tokens=int(usage_raw["total_tokens"]) if usage_raw.get("total_tokens") is not None else None,
                        cached_tokens=(
                            int(usage_raw.get("input_tokens_details", {}).get("cached_tokens", 0) or 0)
                            if isinstance(usage_raw.get("input_tokens_details"), Mapping)
                            else None
                        ),
                        reasoning_tokens=(
                            int(usage_raw.get("output_tokens_details", {}).get("reasoning_tokens", 0) or 0)
                            if isinstance(usage_raw.get("output_tokens_details"), Mapping)
                            else None
                        ),
                    )
                    return _APIResult(
                        text=self._extract_text(data),
                        usage=usage,
                        response_id=str(data["id"]) if data.get("id") is not None else None,
                        status=str(data["status"]) if data.get("status") is not None else None,
                        latency_ms=max(0, (time.perf_counter_ns() - started) // 1_000_000),
                    )
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in retry_statuses or attempt >= self.max_retries:
                    request_id = exc.headers.get("x-request-id") if exc.headers else None
                    suffix = f" request_id={request_id}" if request_id else ""
                    raise OpenAIProviderError(f"OpenAI API HTTP {exc.code}.{suffix}") from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise OpenAIProviderError(f"OpenAI API connection/response error: {type(exc).__name__}") from exc
            time.sleep(min(2**attempt, 4))
        raise OpenAIProviderError(f"OpenAI request failed: {type(last_error).__name__}")

    def structured(
        self,
        *,
        developer_instruction: str,
        payload: Mapping[str, Any] | str,
        schema_name: str,
        schema: Mapping[str, Any],
    ) -> _APIResult:
        user_content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return self._request(
            {
                "model": self.model,
                "store": False,
                "input": [
                    {"role": "developer", "content": developer_instruction},
                    {"role": "user", "content": user_content},
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "strict": True,
                        "schema": schema,
                    }
                },
            }
        )

    def text(self, *, developer_instruction: str, prompt: str) -> _APIResult:
        return self._request(
            {
                "model": self.model,
                "store": False,
                "input": [
                    {"role": "developer", "content": developer_instruction},
                    {"role": "user", "content": prompt},
                ],
            }
        )


_SCALAR = {
    "anyOf": [
        {"type": "string"}, {"type": "number"},
        {"type": "boolean"}, {"type": "null"},
    ]
}
SQL_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "queries": {
            "type": "array", "minItems": 1, "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "sql": {"type": "string"},
                    "parameters": {"type": "array", "items": _SCALAR},
                },
                "required": ["name", "sql", "parameters"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["queries"],
    "additionalProperties": False,
}
POLICY_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["APPROVE", "REJECT", "NEED_MORE_INFO", "NOT_APPLICABLE"]},
        "clauses": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
        "confidence": {"type": ["number", "null"]},
    },
    "required": ["decision", "clauses", "rationale", "confidence"],
    "additionalProperties": False,
}
VERIFIER_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["PASS", "FAIL"]},
        "issues": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "issues"],
    "additionalProperties": False,
}


class OpenAICoreModel:
    """One API client implementing both SQLModel and ReasoningModel."""

    def __init__(self, client: OpenAIResponsesClient) -> None:
        self.client = client

    @staticmethod
    def _provider_result(result: _APIResult, model: str) -> ProviderResult:
        return ProviderResult(
            output=result.text,
            usage=result.usage,
            provider="openai",
            model_id=model,
            finish_reason=result.status,
            latency_ms=result.latency_ms,
            provider_request_id=result.response_id,
            raw_output=result.text,
        )

    def generate_sql(self, payload: Mapping[str, Any]) -> ProviderResult:
        result = self.client.structured(
            developer_instruction=SQL_DEVELOPER_INSTRUCTION,
            payload=payload,
            schema_name="policy_agent_sql_plan",
            schema=SQL_PLAN_SCHEMA,
        )
        return self._provider_result(result, self.client.model)

    def reason(self, payload: Mapping[str, Any]) -> ProviderResult:
        result = self.client.structured(
            developer_instruction=POLICY_DEVELOPER_INSTRUCTION,
            payload=payload,
            schema_name="policy_agent_decision",
            schema=POLICY_DECISION_SCHEMA,
        )
        return self._provider_result(result, self.client.model)


class OpenAIScaffoldLLM:
    """Adapter for Chae-rin's string-in/LLMResult-out scaffold contract."""

    def __init__(self, client: OpenAIResponsesClient) -> None:
        self.client = client
        self.provider = "openai"
        self.model_id = client.model
        self.last_result: _APIResult | None = None

    def __call__(self, prompt: str) -> LLMResult:
        if "[조회된 사실]" in prompt and "[판정]" in prompt:
            result = self.client.structured(
                developer_instruction=VERIFIER_DEVELOPER_INSTRUCTION,
                payload=prompt,
                schema_name="policy_reasoning_verification",
                schema=VERIFIER_SCHEMA,
            )
            text = result.text
        else:
            result = self.client.text(
                developer_instruction=SQL_REPAIR_DEVELOPER_INSTRUCTION,
                prompt=prompt,
            )
            text = result.text.strip()
            if text.startswith("```"):
                lines = text.splitlines()
                text = "\n".join(lines[1:-1]).strip() if len(lines) >= 3 else text
                if text.lower().startswith("sql\n"):
                    text = text[4:].strip()
        self.last_result = result
        return LLMResult(
            text=text,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
        )

