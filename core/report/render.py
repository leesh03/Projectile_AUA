"""UpgradeReport(JSON) -> Markdown. 6개 섹션 고정 순서, 비어 있으면 "해당 없음".

숫자는 전부 UpgradeReport JSON에서만 가져온다 — 그래야 "같은 JSON이면 같은 보고서"가
구조적으로 보장된다. Trace Diff의 화살표 다이어그램만 예외적으로 원본 LoadResult(선택
인자)를 함께 받는다. 없어도 렌더링은 되고, 그 경우 첫 분기 지점 정보만 텍스트로 보여준다.

Regression/Efficiency 2개 섹션으로 Finding을 나누는 기준: FindingType.EFFICIENCY_WARNING만
"3. Efficiency"로, 나머지 전부(REGRESSION/SAFETY_ALERT/IMPROVEMENT/OPTIMIZATION_OPPORTUNITY/
INCONCLUSIVE)는 "2. Regression"으로 모은다 — 계획서가 6개 섹션만 고정했고 Finding 5종을
전부 담을 별도 섹션은 없기 때문에, "그 외 전부"를 담는 섹션으로 Regression을 쓴다.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from core.schemas.finding import Finding
from core.schemas.loader import LoadResult
from core.schemas.report import MetricComparison, UpgradeReport
from core.schemas.trace import TraceStep

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)

_VERDICT_LABEL = {"PASS": "PASS", "HOLD": "HOLD", "BLOCK": "BLOCK"}


def _rate_row(label: str, mc: MetricComparison) -> dict:
    delta = "N/A" if mc.delta_pp is None else f"{mc.delta_pp:+.1f}pp"
    return {"label": label, "v0": f"{mc.v0 * 100:.1f}%", "v1": f"{mc.v1 * 100:.1f}%", "delta": delta}


def _pct_row(label: str, mc: MetricComparison) -> dict:
    delta = "N/A" if mc.delta_pct is None else f"{mc.delta_pct:+.1f}%"
    return {"label": label, "v0": f"{mc.v0:,.0f}", "v1": f"{mc.v1:,.0f}", "delta": delta}


def _count_row(label: str, mc: MetricComparison, digits: int = 2) -> dict:
    delta = "N/A" if mc.delta is None else f"{mc.delta:+.{digits}f}"
    return {"label": label, "v0": f"{mc.v0:.{digits}f}", "v1": f"{mc.v1:.{digits}f}", "delta": delta}


def _summary_rows(report: UpgradeReport) -> list[dict]:
    s = report.summary
    return [
        _rate_row("성공률 (success_rate)", s.success_rate),
        _rate_row("Tool 오류율 (tool_error_rate)", s.tool_error_rate),
        _count_row("평균 재시도 (avg_retry)", s.avg_retry),
        _pct_row("평균 토큰 (avg_tokens)", s.avg_tokens),
        _pct_row("평균 지연 ms (avg_latency_ms)", s.avg_latency_ms),
        _count_row("안전 위반 건수 (safety_violation)", s.safety_violation, digits=0),
    ]


def _finding_row(f: Finding) -> dict:
    ev = f.evidence
    parts = [f"{ev.metric}: V0={ev.v0:.3g} / V1={ev.v1:.3g}"]
    if ev.delta_pp is not None:
        parts.append(f"Δ{ev.delta_pp:+.1f}pp")
    if ev.delta_pct is not None:
        parts.append(f"Δ{ev.delta_pct:+.1f}%")
    if ev.delta is not None:
        parts.append(f"Δ{ev.delta:+.2f}")
    if ev.threshold:
        parts.append(f"(임계 {ev.threshold})")

    preview = ", ".join(f.affected_testcases[:5])
    if len(f.affected_testcases) > 5:
        preview += f" 외 {len(f.affected_testcases) - 5}건"

    return {
        "finding_id": f.finding_id,
        "rule_id": f.rule_id,
        "severity": f.severity.value,
        "type": f.type.value,
        "title": f.title,
        "affected_count": len(f.affected_testcases),
        "affected_preview": preview,
        "evidence": " · ".join(parts),
        "explanation": f.explanation,
        "low_confidence": f.low_confidence,
    }


def _sequence_for(traces: list[TraceStep], testcase_id: str, label: str) -> list[TraceStep]:
    matches = [s for s in traces if s.testcase_id == testcase_id and s.agent_label == label]
    if not matches:
        return []
    trial = min(s.trial for s in matches if s.trial is not None) if any(s.trial for s in matches) else None
    if trial is not None:
        matches = [s for s in matches if s.trial == trial]
    return sorted(matches, key=lambda s: s.step_index)


def _arrow(steps: list[TraceStep]) -> str:
    parts = []
    for s in steps:
        marker = "(FAIL)" if s.outcome.value == "fail" else ("(ok)" if s.type.value == "tool_call" else "")
        parts.append(f"{s.node_role.value}{marker}")
    tail = "✔" if steps and steps[-1].outcome.value == "ok" else "✘"
    return " → ".join(parts) + f"  {tail}"


def _build_trace_diffs(report: UpgradeReport, load_result: LoadResult | None, max_cases: int = 3) -> list[dict]:
    if load_result is None or not load_result.traces:
        return []
    v0_label, v1_label = load_result.baseline.label, load_result.candidate.label

    diffs: list[dict] = []
    seen: set[str] = set()
    for f in report.findings:
        if f.first_divergence is None:
            continue
        for tc in f.affected_testcases:
            if tc in seen:
                continue
            v0_steps = _sequence_for(load_result.traces, tc, v0_label)
            v1_steps = _sequence_for(load_result.traces, tc, v1_label)
            if not v0_steps or not v1_steps:
                continue
            seen.add(tc)
            diffs.append(
                {
                    "testcase_id": tc,
                    "v0_label": v0_label,
                    "v1_label": v1_label,
                    "v0_arrow": _arrow(v0_steps),
                    "v1_arrow": _arrow(v1_steps),
                    "step_index": f.first_divergence.step_index,
                    "node_role": f.first_divergence.node_role.value,
                    "detail": f.first_divergence.detail,
                }
            )
            if len(diffs) >= max_cases:
                return diffs
    return diffs


def render_markdown(report: UpgradeReport, load_result: LoadResult | None = None) -> str:
    efficiency = [f for f in report.findings if f.type.value == "EFFICIENCY_WARNING"]
    regression = [f for f in report.findings if f.type.value != "EFFICIENCY_WARNING"]

    template = _env.get_template("report.md.j2")
    return template.render(
        report=report,
        verdict_label=_VERDICT_LABEL[report.verdict.value],
        trials_per_case_label=f"{report.summary.trials_per_case:g}",
        summary_rows=_summary_rows(report),
        regression_rows=[_finding_row(f) for f in regression],
        efficiency_rows=[_finding_row(f) for f in efficiency],
        trace_diffs=_build_trace_diffs(report, load_result),
        trace_available=bool(load_result and load_result.traces),
        candidates=report.candidates,
        revalidation=report.revalidation,
        limitations=report.limitations,
        unpaired_testcases=report.unpaired_testcases,
    )
