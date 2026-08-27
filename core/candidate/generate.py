"""Deterministic Finding-to-Candidate mapping.

Candidate generation is intentionally bounded. It never edits source code and
never invents a free-form operator; it maps detector evidence to one of the
five project-level recommendation types.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.candidate.operators import (
    CONDITIONAL,
    KEEP,
    REDUCE,
    REMOVE,
    REPLACE_WITH_CODE,
    validate_operator,
)
from core.schemas.enums import RiskLevel
from core.schemas.finding import Candidate, Finding


@dataclass(frozen=True, slots=True)
class CandidateTemplate:
    operator: str
    target: str
    change_spec: str
    expected_effect: str
    risk: RiskLevel


_RULE_TEMPLATES: dict[str, CandidateTemplate] = {
    "O-01": CandidateTemplate(
        REMOVE,
        "reasoning_verifier",
        "Reasoning Verifier를 비활성화하고 동일 Suite로 비열등성을 재검증한다.",
        "Verifier LLM 호출과 관련 토큰·지연을 제거한다.",
        RiskLevel.MEDIUM,
    ),
    "O-02": CandidateTemplate(
        REDUCE,
        "sql_repair.max_retries",
        "SQL Repair 최대 횟수를 1회 이하로 줄이고 반복 오류에서 조기 중단한다.",
        "회복되지 않는 재시도와 지연을 줄인다.",
        RiskLevel.MEDIUM,
    ),
    "E-01": CandidateTemplate(
        REDUCE,
        "sql_repair.max_retries",
        "SQL Repair 최대 횟수를 단계적으로 줄여 최소 유효 횟수를 찾는다.",
        "성공률을 유지하면서 평균 재시도를 낮춘다.",
        RiskLevel.MEDIUM,
    ),
    "E-02": CandidateTemplate(
        REDUCE,
        "scaffold.token_budget",
        "품질에 기여하지 않는 Scaffold 호출부터 제거하거나 범위를 축소한다.",
        "평균 토큰 사용량을 낮춘다.",
        RiskLevel.MEDIUM,
    ),
    "E-03": CandidateTemplate(
        REDUCE,
        "scaffold.latency_budget",
        "느린 선택적 Scaffold를 조건부 실행으로 바꾸고 시간 상한을 적용한다.",
        "평균 지연 시간을 낮춘다.",
        RiskLevel.MEDIUM,
    ),
    "E-04": CandidateTemplate(
        REMOVE,
        "redundant_trace_node",
        "결과에 영향을 주지 않는 중복 실행 단계를 제거한다.",
        "평균 실행 단계 수와 호출 비용을 줄인다.",
        RiskLevel.MEDIUM,
    ),
    "R-02": CandidateTemplate(
        REPLACE_WITH_CODE,
        "tool_schema_validator",
        "Tool 인자와 SQL 형식을 결정론적 Schema Validator로 검증한다.",
        "모델 변동과 무관하게 Tool 계약 위반을 조기에 차단한다.",
        RiskLevel.MEDIUM,
    ),
    "R-05": CandidateTemplate(
        CONDITIONAL,
        "difficulty_router",
        "회귀가 발생한 난이도 구간에서만 기존 Scaffold 또는 강한 모델을 유지한다.",
        "쉬운 사례의 비용을 줄이면서 어려운 사례의 품질을 보존한다.",
        RiskLevel.MEDIUM,
    ),
}

_KEEP_RULES = frozenset({"R-01", "R-03", "R-04", "S-01", "S-02"})


def _template_for(finding: Finding) -> CandidateTemplate | None:
    template = _RULE_TEMPLATES.get(finding.rule_id)
    if template is not None:
        return template
    if finding.rule_id in _KEEP_RULES or finding.type.value == "SAFETY_ALERT":
        return CandidateTemplate(
            KEEP,
            "baseline_configuration",
            "회귀 또는 안전 원인이 해소될 때까지 기존 V0 구성을 유지한다.",
            "검증되지 않은 업그레이드의 배포를 막는다.",
            RiskLevel.LOW,
        )
    return None


def generate_candidates(findings: list[Finding]) -> list[Candidate]:
    """Generate stable candidates and merge Findings that share one change."""

    grouped: dict[tuple[str, str], tuple[CandidateTemplate, list[str]]] = {}
    order: list[tuple[str, str]] = []
    for finding in findings:
        template = _template_for(finding)
        if template is None:
            continue
        validate_operator(template.operator)
        key = (template.operator, template.target)
        if key not in grouped:
            grouped[key] = (template, [])
            order.append(key)
        grouped[key][1].append(finding.finding_id)

    candidates: list[Candidate] = []
    for index, key in enumerate(order, start=1):
        template, addresses = grouped[key]
        candidates.append(
            Candidate(
                candidate_id=f"C-{index:02d}",
                operator=template.operator,
                target=template.target,
                addresses=addresses,
                change_spec=template.change_spec,
                expected_effect=template.expected_effect,
                risk=template.risk,
            )
        )
    return candidates
