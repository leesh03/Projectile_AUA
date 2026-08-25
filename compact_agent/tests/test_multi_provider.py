from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from policy_runtime.multi_provider import (
    GeminiClient,
    GroqClient,
    MultiProviderError,
)
from policy_runtime.openai_provider import VERIFIER_SCHEMA


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class MultiProviderTests(unittest.TestCase):
    def test_gemini_key_is_required(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(MultiProviderError):
                GeminiClient()

    def test_groq_key_is_required(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(MultiProviderError):
                GroqClient()

    def test_gemini_structured_request_and_usage_are_parsed(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return _FakeResponse(
                {
                    "responseId": "gem_test",
                    "candidates": [
                        {
                            "finishReason": "STOP",
                            "content": {
                                "parts": [
                                    {"text": '{"status":"PASS","issues":[]}'},
                                ]
                            },
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 8,
                        "candidatesTokenCount": 4,
                        "totalTokenCount": 12,
                    },
                }
            )

        client = GeminiClient(
            api_key="test-secret", model="models/test-model", max_retries=0
        )
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = client.structured(
                developer_instruction="verify",
                payload="payload",
                schema_name="verifier",
                schema=VERIFIER_SCHEMA,
            )
        self.assertEqual('{"status":"PASS","issues":[]}', result.text)
        self.assertEqual(12, result.usage.counted_total)
        self.assertEqual("test-secret", captured["request"].get_header("X-goog-api-key"))
        self.assertTrue(captured["request"].full_url.endswith("/models/test-model:generateContent"))
        sent = json.loads(captured["request"].data.decode("utf-8"))
        self.assertEqual("application/json", sent["generationConfig"]["responseMimeType"])
        self.assertEqual(VERIFIER_SCHEMA, sent["generationConfig"]["responseJsonSchema"])

    def test_groq_structured_request_and_usage_are_parsed(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return _FakeResponse(
                {
                    "id": "groq_test",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": '{"status":"PASS","issues":[]}'
                            },
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 9,
                        "completion_tokens": 5,
                        "total_tokens": 14,
                    },
                }
            )

        client = GroqClient(api_key="test-secret", model="test-model", max_retries=0)
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = client.structured(
                developer_instruction="verify",
                payload="payload",
                schema_name="verifier",
                schema=VERIFIER_SCHEMA,
            )
        self.assertEqual('{"status":"PASS","issues":[]}', result.text)
        self.assertEqual(14, result.usage.counted_total)
        self.assertEqual(
            "Bearer test-secret", captured["request"].get_header("Authorization")
        )
        sent = json.loads(captured["request"].data.decode("utf-8"))
        self.assertEqual("json_schema", sent["response_format"]["type"])
        self.assertTrue(sent["response_format"]["json_schema"]["strict"])


if __name__ == "__main__":
    unittest.main()
