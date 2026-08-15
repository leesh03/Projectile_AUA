"""L4 — 규칙 탐지기 인터페이스. 레지스트리 방식으로 규칙을 하나씩 등록한다.

규칙은 L1~L3(loader/aggregate/compare) 산출물만 보고 판단한다. LLM 호출 없음.
필요한 필드가 없으면 예외가 아니라 SKIPPED로 빠진다 — 그래야 팀원 데이터에 필드가
빠져도 Auditor 전체가 죽지 않는다 (docs/CONTRACT.md §6).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from core.diff.aggregate import AggregateResult
from core.diff.compare import DiffResult
from core.schemas.enums import FindingType, Severity
from core.schemas.finding import Finding
from core.schemas.loader import LoadResult

# 하나의 Finding이 "표본이 너무 적다"고 판단하는 기준 (P3-3 오탐 방지).
MIN_TRIALS_FOR_CONFIDENCE = 2


@dataclass
class DetectionContext:
    """규칙 하나가 판단을 내리는 데 필요한 모든 것. L1~L3 산출물을 그대로 묶는다."""

    load_result: LoadResult
    agg: AggregateResult
    diff: DiffResult

    @property
    def v0_label(self) -> str:
        return self.agg.labels[0]

    @property
    def v1_label(self) -> str:
        return self.agg.labels[1]

    @property
    def has_trace(self) -> bool:
        return bool(self.load_result.traces)


class Rule(ABC):
    rule_id: str
    severity: Severity
    requires: tuple[str, ...] = ()  # 예: ("tool_schema_valid",). 없으면 SKIPPED.

    @abstractmethod
    def evaluate(self, ctx: DetectionContext) -> list[Finding]:
        """조건을 만족하는 만큼 Finding을 만든다 (보통 0개 또는 1개, R-01만 최대 2개).

        requires 체크는 run_rules()가 먼저 하므로 여기서는 신경 쓰지 않아도 된다.
        """


@dataclass
class SkippedRule:
    rule_id: str
    reason: str


REGISTRY: list[Rule] = []


def register(rule_cls: type[Rule]) -> type[Rule]:
    """`@register`는 클래스 위에 붙인다. 인스턴스 하나를 만들어 REGISTRY에 넣고 클래스는 그대로 반환한다."""
    REGISTRY.append(rule_cls())
    return rule_cls


def _check_requirement(ctx: DetectionContext, field_name: str) -> str | None:
    """요구 필드가 있는지 확인한다. 있으면 None, 없으면 SKIPPED 사유 문자열."""
    if field_name == "trace":
        return None if ctx.has_trace else "traces 없음"

    v0m = ctx.agg.overall.get(ctx.v0_label)
    v1m = ctx.agg.overall.get(ctx.v1_label)
    if field_name == "tool_schema_valid":
        present = (v0m and v0m.tool_schema_valid_rate is not None) or (
            v1m and v1m.tool_schema_valid_rate is not None
        )
        return None if present else "tool_schema_valid 필드 없음 (권장 필드, CONTRACT.md §1.2)"
    if field_name == "llm_call_count":
        present = (v0m and v0m.avg_llm_call_count is not None) or (v1m and v1m.avg_llm_call_count is not None)
        return None if present else "llm_call_count 필드 없음 (권장 필드, CONTRACT.md §1.2)"
    if field_name == "difficulty":
        return None if ctx.agg.by_difficulty else "difficulty 필드 없음 (권장 필드, CONTRACT.md §1.2)"
    return None  # 필수 필드(testcase_id, task_success 등)는 로더 단계에서 이미 보장됨


def _demote_if_low_confidence(ctx: DetectionContext, finding: Finding) -> Finding:
    """영향 케이스 1건뿐이고 그 케이스의 trial 수가 부족하면 INCONCLUSIVE로 강등한다."""
    if len(finding.affected_testcases) > 1:
        return finding

    for tc in finding.affected_testcases:
        tc_agg = ctx.agg.by_testcase.get(tc)
        if tc_agg is None:
            continue
        v1m = tc_agg.metrics_by_label.get(ctx.v1_label)
        if v1m is not None and v1m.trial_count < MIN_TRIALS_FOR_CONFIDENCE:
            return finding.model_copy(update={"type": FindingType.INCONCLUSIVE, "low_confidence": True})
    return finding


def run_rules(ctx: DetectionContext, rules: list[Rule] | None = None) -> tuple[list[Finding], list[SkippedRule]]:
    """등록된 규칙을 전부 돌려 (Finding 목록, SKIPPED 목록)을 반환한다."""
    findings: list[Finding] = []
    skipped: list[SkippedRule] = []

    for rule in rules if rules is not None else REGISTRY:
        missing = [reason for f in rule.requires if (reason := _check_requirement(ctx, f))]
        if missing:
            skipped.append(SkippedRule(rule_id=rule.rule_id, reason="; ".join(missing)))
            continue
        for finding in rule.evaluate(ctx):
            findings.append(_demote_if_low_confidence(ctx, finding))

    return findings, skipped
