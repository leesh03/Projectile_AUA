"""L3 — Deterministic Diff. AggregateResult 두 버전을 비교해 delta와 flip 행렬을 만든다.

LLM 호출 0회. 0 나눗셈·빈 목록은 여기서 전부 방어한다 — 위(L4 규칙)로 예외가 새지 않게 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from core.diff.aggregate import AggregateResult

# rate류(0~1 비율) 지표는 퍼센트 포인트(pp)로, 절대량 지표는 그냥 차이로,
# 비용류(토큰/지연/호출수) 지표는 상대 변화율(%)로 표시한다 — 지표 성격에 맞는 단위를 고정한다.
RATE_METRICS = {"success_rate", "policy_accuracy", "tool_error_rate", "tool_schema_valid_rate"}
ABS_METRICS = {"avg_retry"}
PCT_METRICS = {"avg_tokens", "avg_latency_ms", "avg_llm_call_count"}


class FlipClass(str, Enum):
    PRESERVED = "preserved"  # V0 PASS, V1 PASS
    REGRESSION = "regression"  # V0 PASS, V1 FAIL  ★ R-01
    IMPROVEMENT = "improvement"  # V0 FAIL, V1 PASS
    PERSISTENT = "persistent"  # V0 FAIL, V1 FAIL


@dataclass
class MetricDelta:
    metric: str
    v0: float
    v1: float
    delta: float | None = None
    delta_pp: float | None = None  # percentage-point (rate류)
    delta_pct: float | None = None  # 상대 변화율 % (비용류). 분모 0이면 None.


def _pct(v0: float, v1: float) -> float | None:
    if v0 == 0:
        return None  # 0 나눗셈 방어 — "0에서 몇 % 늘었다"는 정의할 수 없다
    return (v1 - v0) / v0 * 100


def _delta_for(metric: str, v0: float | None, v1: float | None) -> MetricDelta:
    v0v = v0 if v0 is not None else 0.0
    v1v = v1 if v1 is not None else 0.0
    d = MetricDelta(metric=metric, v0=v0v, v1=v1v)
    if metric in RATE_METRICS:
        d.delta_pp = (v1v - v0v) * 100
    elif metric in ABS_METRICS:
        d.delta = v1v - v0v
    elif metric in PCT_METRICS:
        d.delta_pct = _pct(v0v, v1v)
    else:
        d.delta = v1v - v0v
    return d


@dataclass
class OverallDiff:
    metrics: dict[str, MetricDelta]
    safety_violations: MetricDelta  # count 기준, delta만 의미 있음


@dataclass
class FlipEntry:
    testcase_id: str
    classification: FlipClass


@dataclass
class DiffResult:
    overall: OverallDiff
    flips: list[FlipEntry]
    flip_counts: dict[FlipClass, int] = field(default_factory=dict)

    def testcases_by(self, cls: FlipClass) -> list[str]:
        return [f.testcase_id for f in self.flips if f.classification is cls]


def compare(agg: AggregateResult) -> DiffResult:
    v0_label, v1_label = agg.labels
    v0 = agg.overall[v0_label]
    v1 = agg.overall[v1_label]

    metrics = {
        "success_rate": _delta_for("success_rate", v0.success_rate, v1.success_rate),
        "policy_accuracy": _delta_for("policy_accuracy", v0.policy_accuracy, v1.policy_accuracy),
        "tool_error_rate": _delta_for("tool_error_rate", v0.tool_error_rate, v1.tool_error_rate),
        "avg_retry": _delta_for("avg_retry", v0.avg_retry, v1.avg_retry),
        "avg_tokens": _delta_for("avg_tokens", v0.avg_tokens, v1.avg_tokens),
        "avg_latency_ms": _delta_for("avg_latency_ms", v0.avg_latency_ms, v1.avg_latency_ms),
    }
    if v0.tool_schema_valid_rate is not None or v1.tool_schema_valid_rate is not None:
        metrics["tool_schema_valid_rate"] = _delta_for(
            "tool_schema_valid_rate", v0.tool_schema_valid_rate, v1.tool_schema_valid_rate
        )
    if v0.avg_llm_call_count is not None or v1.avg_llm_call_count is not None:
        metrics["avg_llm_call_count"] = _delta_for(
            "avg_llm_call_count", v0.avg_llm_call_count, v1.avg_llm_call_count
        )

    safety = MetricDelta(
        metric="safety_violations",
        v0=v0.safety_violations,
        v1=v1.safety_violations,
        delta=v1.safety_violations - v0.safety_violations,
    )

    flips: list[FlipEntry] = []
    counts: dict[FlipClass, int] = {c: 0 for c in FlipClass}
    for tc, tc_agg in agg.by_testcase.items():
        p0 = tc_agg.task_success_by_label.get(v0_label, False)
        p1 = tc_agg.task_success_by_label.get(v1_label, False)
        if p0 and p1:
            cls = FlipClass.PRESERVED
        elif p0 and not p1:
            cls = FlipClass.REGRESSION
        elif not p0 and p1:
            cls = FlipClass.IMPROVEMENT
        else:
            cls = FlipClass.PERSISTENT
        flips.append(FlipEntry(testcase_id=tc, classification=cls))
        counts[cls] += 1

    return DiffResult(
        overall=OverallDiff(metrics=metrics, safety_violations=safety),
        flips=sorted(flips, key=lambda f: f.testcase_id),
        flip_counts=counts,
    )
