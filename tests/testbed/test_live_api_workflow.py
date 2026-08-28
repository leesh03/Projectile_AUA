from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_live_api_workflow_is_opt_in_and_uses_only_github_secrets() -> None:
    workflow = (ROOT / ".github" / "workflows" / "testbed-live-api.yml").read_text(
        encoding="utf-8"
    )

    assert "vars.LIVE_API_TESTS_ENABLED == 'true'" in workflow
    assert "secrets.GEMINI_API_KEY" in workflow
    assert "secrets.GROQ_API_KEY" in workflow
    assert "tools/verify_live_api.py --provider gemini" in workflow
    assert "tools/verify_live_api.py --provider groq" in workflow
    assert "--isolation container" in workflow


def test_container_build_context_explicitly_excludes_gold() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    dockerfile = (ROOT / "containers" / "testbed.Dockerfile").read_text(
        encoding="utf-8"
    )

    assert "!data/shop.db" in dockerignore
    assert "answer_key.db" not in dockerignore
    assert "test_cases.json" not in dockerignore
    assert "COPY --chown=65532:65532 data/shop.db" in dockerfile
    assert "COPY --chown=65532:65532 data " not in dockerfile
    assert "policy_oracle.py" not in dockerfile
