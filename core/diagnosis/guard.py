"""P5-3 숫자 방어 장치 — 2차 방어선.

1차 방어선(schemas.py)은 LLM 출력 스키마에서 수치 필드를 아예 없앴다. 하지만 설명문
텍스트 안에 "성공률이 25% 떨어졌다" 같은 문장이 섞여 들어오는 건 스키마로 못 막는다.
여기서 그걸 잡는다.

정책: **지우는 게 아니라 중립 표현으로 치환한다.** 지우면 문장이 깨지고, 그대로 두면
코드가 계산한 값과 충돌할 수 있다. "25%p" -> "(수치는 표 참조)"로 바꾸면 문장은 읽히고
정확한 값은 독자가 표에서 본다.

finding_id(F-01), rule_id(R-02) 같은 식별자는 숫자를 포함하지만 수치가 아니므로
치환 대상에서 뺀다.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

REPLACEMENT = "(수치는 표 참조)"

# 식별자 패턴 — 이건 수치가 아니므로 먼저 가려낸다. (F-01, R-02, E-01, O-02, S-01, C1, V0, V1, P0~P2)
# \b를 쓰면 안 된다: "F-01은"처럼 한글이 바로 붙으면 한글도 word 문자라 경계가 성립하지 않는다.
_IDENTIFIER = re.compile(r"(?<![0-9A-Za-z])(?:[FREOSC]-?\d+|V\d+|P[012])(?![0-9A-Za-z])")

# 수치 패턴 — 퍼센트/퍼센트포인트/배수/건수/소수/정수 순으로 넓게 잡는다.
_NUMERIC_PATTERNS = [
    re.compile(r"\d+(?:\.\d+)?\s*%\s*p\b", re.IGNORECASE),  # 25%p
    re.compile(r"\d+(?:\.\d+)?\s*퍼센트\s*포인트"),
    re.compile(r"\d+(?:\.\d+)?\s*%"),  # 21%
    re.compile(r"\d+(?:\.\d+)?\s*퍼센트"),
    re.compile(r"\d+(?:\.\d+)?\s*배\b"),  # 3배
    re.compile(r"\d+(?:\.\d+)?\s*(?:건|개|회|초|ms|밀리초|토큰)\b"),  # 5건, 1.8회
    re.compile(r"\d+\.\d+"),  # 남은 소수
    re.compile(r"\d+"),  # 남은 정수
]

# 자리표시자에 인덱스 숫자를 넣으면 아래 수치 패턴이 그 숫자를 잡아먹는다.
# 그래서 전부 같은 토큰으로 바꾸고, 복원할 때 등장 순서대로 되돌린다.
_PLACEHOLDER = "\x00IDENT\x00"


def scrub_numbers(text: str, *, context: str = "") -> tuple[str, bool]:
    """설명문에서 수치 표현을 중립 문구로 치환한다.

    Returns:
        (치환된 텍스트, 치환이 일어났는지 여부)
    """
    if not text:
        return text, False

    # 식별자를 자리표시자로 빼둔다 — "F-01"의 01이 수치로 오인되면 안 된다.
    identifiers: list[str] = []

    def _stash(match: re.Match[str]) -> str:
        identifiers.append(match.group(0))
        return _PLACEHOLDER

    stashed = _IDENTIFIER.sub(_stash, text)

    scrubbed = stashed
    for pattern in _NUMERIC_PATTERNS:
        scrubbed = pattern.sub(REPLACEMENT, scrubbed)

    # 연속 치환으로 "(수치는 표 참조)(수치는 표 참조)"가 생기면 하나로 줄인다.
    scrubbed = re.sub(rf"(?:{re.escape(REPLACEMENT)}\s*){{2,}}", REPLACEMENT + " ", scrubbed)

    for ident in identifiers:
        scrubbed = scrubbed.replace(_PLACEHOLDER, ident, 1)

    changed = scrubbed != text
    if changed:
        logger.warning(
            "LLM 설명문에 수치가 포함돼 치환했습니다%s: %r -> %r",
            f" ({context})" if context else "",
            text,
            scrubbed,
        )
    return scrubbed, changed
