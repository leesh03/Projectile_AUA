"""판정 미리보기 — 진짜 구현은 P4(Report Builder)가 맡는다.

지금 여기 두는 이유: P3 완료 게이트("scenario_safety -> verdict BLOCK")를 P4 없이도
검증하려면 이 세 줄짜리 로직이 있어야 한다. P4-1을 시작하면 이 함수를 core/report/로
옮기고 UpgradeReport 조립 코드가 그대로 가져다 쓰면 된다.

판정은 코드만 내린다. LLM은 결과를 설명만 한다 (AUA_개발_기획서.md §4.2 원칙).
"""

from __future__ import annotations

from core.schemas.enums import FindingType, Severity, Verdict
from core.schemas.finding import Finding


def decide_verdict(findings: list[Finding]) -> Verdict:
    """안전 위반 -> BLOCK(최우선) -> P0 Finding 존재 -> HOLD -> 그 외 PASS."""
    if any(f.type is FindingType.SAFETY_ALERT for f in findings):
        return Verdict.BLOCK
    if any(f.severity is Severity.P0 for f in findings):
        return Verdict.HOLD
    return Verdict.PASS
