"""LLM 호출 인터페이스와 테스트용 대역.

실제 모델 연결은 API 키 확보 후 추가한다. 그 전까지는 ScriptedLLM으로 개발·테스트한다.
스캐폴드는 LLM을 직접 생성하지 않고 인자로 주입받는다.
"""

from collections.abc import Sequence
from typing import NamedTuple, Protocol


class LLMResult(NamedTuple):
    """LLM 응답. 토큰 수는 TraceStep 기록에 사용한다."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class LLMClient(Protocol):
    def __call__(self, prompt: str) -> LLMResult: ...


class ScriptedLLM:
    """호출 순서대로 미리 정한 응답을 반환한다.

    응답을 모두 소진하면 마지막 값을 계속 반환한다. 반복 횟수 설정만 바꿔가며
    같은 대본으로 실험할 수 있도록 한 동작이다.
    """

    def __init__(
        self,
        responses: Sequence[str],
        input_tokens: int = 100,
        output_tokens: int = 50,
    ) -> None:
        if not responses:
            raise ValueError("responses는 최소 1개가 필요하다")
        self._responses = list(responses)
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self.prompts: list[str] = []

    @property
    def call_count(self) -> int:
        return len(self.prompts)

    def __call__(self, prompt: str) -> LLMResult:
        index = min(len(self.prompts), len(self._responses) - 1)
        self.prompts.append(prompt)
        return LLMResult(
            text=self._responses[index],
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
        )
