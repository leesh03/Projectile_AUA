from __future__ import annotations

import io
import json
import urllib.error
from email.message import Message
from pathlib import Path
from typing import Any, Self

import pytest

import policy_runtime.multi_provider as providers
from policy_runtime.factory import build_agent
from policy_runtime.multi_provider import GeminiClient, GroqClient, MultiProviderError

ROOT = Path(__file__).resolve().parents[2]


def test_api_factory_requires_explicit_provider() -> None:
    with pytest.raises(ValueError, match="requires an explicit provider"):
        build_agent(ROOT, mode="api")


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _gemini_payload() -> dict[str, Any]:
    return {
        "responseId": "gemini-response",
        "candidates": [
            {
                "content": {"parts": [{"text": '{"status":"ok"}'}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 7,
            "candidatesTokenCount": 3,
            "totalTokenCount": 12,
            "thoughtsTokenCount": 2,
        },
    }


def _groq_payload() -> dict[str, Any]:
    return {
        "id": "groq-response",
        "choices": [
            {
                "message": {"content": '{"status":"ok"}'},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13},
    }


def test_gemini_usage_and_reasoning_tokens_are_parsed() -> None:
    result = GeminiClient._parse(_gemini_payload(), latency_ms=12)
    assert result.usage.input_tokens == 7
    assert result.usage.output_tokens == 3
    assert result.usage.total_tokens == 12
    assert result.usage.reasoning_tokens == 2
    assert result.response_id == "gemini-response"


def test_groq_usage_and_response_id_are_parsed() -> None:
    result = GroqClient._parse(_groq_payload(), latency_ms=8)
    assert result.usage.input_tokens == 9
    assert result.usage.output_tokens == 4
    assert result.usage.total_tokens == 13
    assert result.response_id == "groq-response"


def test_gemini_retries_a_rate_limit_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_urlopen(*args: Any, **kwargs: Any) -> _Response:
        nonlocal calls
        del args, kwargs
        calls += 1
        if calls == 1:
            headers = Message()
            headers["retry-after"] = "0"
            raise urllib.error.HTTPError(
                "https://example.invalid",
                429,
                "rate limited",
                headers,
                io.BytesIO(b"{}"),
            )
        return _Response(_gemini_payload())

    monkeypatch.setattr(providers.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(providers, "_retry_delay", lambda *args: None)
    client = GeminiClient(api_key="synthetic-key", base_url="https://example.invalid")
    result = client.text(developer_instruction="test", prompt="test")
    assert calls == 2
    assert result.finish_reason == "STOP"


def test_provider_timeout_becomes_sanitized_contract_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timeout(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise TimeoutError

    monkeypatch.setattr(providers.urllib.request, "urlopen", timeout)
    client = GroqClient(
        api_key="synthetic-key",
        base_url="https://example.invalid",
        max_retries=0,
    )
    with pytest.raises(MultiProviderError, match="connection/response error: TimeoutError"):
        client.text(developer_instruction="test", prompt="test")


def test_http_error_never_leaks_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "synthetic-secret-never-log"

    def unauthorized(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        body = json.dumps({"error": {"message": f"invalid key {secret}"}}).encode()
        raise urllib.error.HTTPError(
            "https://example.invalid",
            401,
            "unauthorized",
            Message(),
            io.BytesIO(body),
        )

    monkeypatch.setattr(providers.urllib.request, "urlopen", unauthorized)
    client = GeminiClient(
        api_key=secret,
        base_url="https://example.invalid",
        max_retries=0,
    )
    with pytest.raises(MultiProviderError) as raised:
        client.text(developer_instruction="test", prompt="test")
    assert secret not in str(raised.value)
    assert "[redacted]" in str(raised.value)
