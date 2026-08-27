"""Upstage Solar 클라이언트 래퍼 (OpenAI 호환 API).

이 모듈의 계약 하나: **절대 예외를 밖으로 던지지 않는다.** 실패하면 None을 반환한다.
데모 중 API가 죽어도 보고서는 나와야 하기 때문이다 (기획서 §4.2, P5 완료 게이트).

호출 로그(프롬프트 해시·토큰·지연)를 남겨서 나중에 "LLM이 뭘 받아서 뭘 뱉었는지"를
추적할 수 있게 한다. 프롬프트 원문 대신 해시를 남기는 이유는 로그에 데이터가 통째로
복사되는 걸 피하기 위해서다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

DEFAULT_TIMEOUT_SEC = 30.0
DEFAULT_MODEL = "solar-pro2"
DEFAULT_BASE_URL = "https://api.upstage.ai/v1"


@dataclass
class CallLog:
    function: str
    prompt_hash: str
    latency_ms: int
    ok: bool
    total_tokens: int | None = None
    error: str | None = None


@dataclass
class LLMClient:
    """Solar 호출 래퍼. 실패는 전부 None으로 흡수한다.

    `enabled=False`이거나 API 키가 없으면 아무것도 호출하지 않고 곧바로 None을 준다 —
    이 경로가 `--no-llm`과 완전히 같은 동작이 되도록 의도했다.
    """

    api_key: str | None = None
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout: float = DEFAULT_TIMEOUT_SEC
    enabled: bool = True
    call_logs: list[CallLog] = field(default_factory=list)
    _client: object | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls) -> LLMClient:
        """.env / 환경변수에서 설정을 읽는다. 키가 없으면 enabled=False로 만들어진다."""
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass

        api_key = os.getenv("UPSTAGE_API_KEY") or None
        enabled = os.getenv("AUDITOR_LLM_ENABLED", "true").lower() not in {"false", "0", "no"}
        return cls(
            api_key=api_key,
            base_url=os.getenv("UPSTAGE_BASE_URL") or DEFAULT_BASE_URL,
            model=os.getenv("AUDITOR_LLM_MODEL") or DEFAULT_MODEL,
            enabled=enabled and bool(api_key),
        )

    @property
    def available(self) -> bool:
        return self.enabled and bool(self.api_key)

    def _ensure_client(self) -> object | None:
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except ImportError:
            logger.warning("openai 패키지가 없어 LLM 진단을 건너뜁니다")
            return None
        self._client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)
        return self._client

    def complete_json(self, *, function: str, prompt: str, response_model: type[T]) -> T | None:
        """JSON 강제 출력 + Pydantic 검증. 실패하면 1회 재요청하고, 그래도 실패하면 None.

        재요청은 파싱/검증 실패와 네트워크 오류 양쪽 모두에 대해 한 번씩만 한다.
        """
        if not self.available:
            return None

        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
        started = time.monotonic()
        last_error: str | None = None
        total_tokens: int | None = None

        for attempt in (1, 2):
            try:
                # 클라이언트 생성도 try 안에 둔다 — base_url이 이상하면 OpenAI()가 여기서 던진다.
                client = self._ensure_client()
                if client is None:
                    return None

                response = client.chat.completions.create(  # type: ignore[attr-defined]
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=0,
                )
                content = response.choices[0].message.content or ""
                usage = getattr(response, "usage", None)
                total_tokens = getattr(usage, "total_tokens", None) if usage else None

                parsed = response_model.model_validate(json.loads(content))
                self.call_logs.append(
                    CallLog(
                        function=function,
                        prompt_hash=prompt_hash,
                        latency_ms=int((time.monotonic() - started) * 1000),
                        ok=True,
                        total_tokens=total_tokens,
                    )
                )
                return parsed
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = f"출력 파싱 실패(attempt {attempt}): {exc}"
                logger.warning("%s — %s", function, last_error)
            except Exception as exc:  # noqa: BLE001 — 네트워크/인증/rate limit 전부 여기서 흡수한다
                last_error = f"{type(exc).__name__}(attempt {attempt}): {exc}"
                logger.warning("%s — LLM 호출 실패: %s", function, last_error)

        self.call_logs.append(
            CallLog(
                function=function,
                prompt_hash=prompt_hash,
                latency_ms=int((time.monotonic() - started) * 1000),
                ok=False,
                total_tokens=total_tokens,
                error=last_error,
            )
        )
        return None
