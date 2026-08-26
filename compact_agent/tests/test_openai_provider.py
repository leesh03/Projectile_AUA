from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from policy_runtime.openai_provider import (
    OpenAIProviderError,
    OpenAIResponsesClient,
    VERIFIER_SCHEMA,
)


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class OpenAIProviderTests(unittest.TestCase):
    def test_key_is_required(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(OpenAIProviderError):
                OpenAIResponsesClient()

    def test_responses_structured_output_and_usage_are_parsed(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return _FakeResponse(
                {
                    "id": "resp_test",
                    "status": "completed",
                    "output_text": '{"status":"PASS","issues":[]}',
                    "usage": {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10},
                }
            )

        client = OpenAIResponsesClient(api_key="test-secret", model="test-model", max_retries=0)
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = client.structured(
                developer_instruction="verify",
                payload="payload",
                schema_name="verifier",
                schema=VERIFIER_SCHEMA,
            )
        self.assertEqual('{"status":"PASS","issues":[]}', result.text)
        self.assertEqual(10, result.usage.counted_total)
        self.assertEqual("Bearer test-secret", captured["request"].get_header("Authorization"))
        sent = json.loads(captured["request"].data.decode("utf-8"))
        self.assertEqual("json_schema", sent["text"]["format"]["type"])
        self.assertTrue(sent["text"]["format"]["strict"])


if __name__ == "__main__":
    unittest.main()
