"""P4 완료 게이트 검증.

체크리스트 (AUA_Phase별_개발순서.md):
- 픽스처 전부에서 보고서 Markdown이 생성된다
- LLM 없이 사람이 읽을 수 있는 보고서가 완성된다
- 같은 입력 -> 같은 보고서 (골든 테스트)
"""

from __future__ import annotations

import json

import pytest

from core.report.render import _arrow, _build_trace_diffs, _sequence_for
from core.schemas.enums import NodeRole, StepOutcome, StepType, Verdict
from core.schemas.finding import Evidence, Finding, FirstDivergence
from core.schemas.loader import LoadResult, load_bundle
from core.schemas.report import UpgradeReport
from core.schemas.trace import TraceStep
from tests.auditor._golden_utils import (
    BUNDLE_DIR,
    GOLDEN_DIR,
    SCENARIO_NAMES,
    build_report_for,
    render_markdown_for,
    summarize_report,
)


@pytest.mark.parametrize("name", SCENARIO_NAMES)
def test_report_matches_golden(name: str) -> None:
    golden_path = GOLDEN_DIR / f"p4_{name}.json"
    expected = json.loads(golden_path.read_text(encoding="utf-8"))
    report, _load_result = build_report_for(name)
    assert summarize_report(report) == expected


@pytest.mark.parametrize("name", SCENARIO_NAMES)
def test_markdown_matches_golden(name: str) -> None:
    golden_path = GOLDEN_DIR / f"p4_{name}.md"
    expected = golden_path.read_text(encoding="utf-8")
    _report, markdown = render_markdown_for(name)
    assert markdown == expected


@pytest.mark.parametrize("name", SCENARIO_NAMES)
def test_report_json_round_trips_through_schema(name: str) -> None:
    """CLI가 쓰는 model_dump_json()과 정확히 같은 경로로 왕복 검증한다."""
    report, _load_result = build_report_for(name)
    dumped = report.model_dump_json()
    reloaded = UpgradeReport.model_validate_json(dumped)
    assert reloaded == report


@pytest.mark.parametrize("name", SCENARIO_NAMES)
def test_same_input_produces_same_report_twice(name: str) -> None:
    """재현성: 같은 입력을 두 번 돌리면 완전히 같은 JSON·Markdown이 나와야 한다."""
    report1, md1 = render_markdown_for(name)
    report2, md2 = render_markdown_for(name)
    assert report1 == report2
    assert md1 == md2


def test_scenario_clean_shows_no_finding_sections() -> None:
    _report, markdown = render_markdown_for("scenario_clean")
    assert "PASS" in markdown
    # 2번(Regression), 3번(Efficiency) 섹션 모두 비어 있어야 한다
    regression_section = markdown.split("## 2. Regression")[1].split("## 3. Efficiency")[0]
    efficiency_section = markdown.split("## 3. Efficiency")[1].split("## 4. Trace Diff")[0]
    assert "해당 없음" in regression_section
    assert "해당 없음" in efficiency_section


def test_scenario_a_trace_diff_not_available() -> None:
    """scenario_a는 trace 없이 R-02를 발화시키도록 만든 픽스처라 4번 섹션이 NOT_AVAILABLE이어야 한다."""
    _report, markdown = render_markdown_for("scenario_a")
    trace_section = markdown.split("## 4. Trace Diff")[1].split("## 5. Recommendation")[0]
    assert "NOT_AVAILABLE" in trace_section


def test_scenario_safety_verdict_is_block_in_report() -> None:
    report, _load_result = build_report_for("scenario_safety")
    assert report.verdict is Verdict.BLOCK


def test_recommendation_section_says_pending_before_p6() -> None:
    for name in SCENARIO_NAMES:
        _report, markdown = render_markdown_for(name)
        assert "준비 중" in markdown  # P6(후보 생성) 전에는 항상 이 문구여야 한다


# ── Trace Diff 화살표 렌더링 (합성 데이터) ────────────────────────────────
# 6개 시나리오 픽스처 중 R-02(첫 분기 지점을 계산하는 유일한 규칙)를 발화시키는
# scenario_a는 일부러 trace가 없다 (O-01/O-02 SKIPPED 경로 검증용, P1 설계).
# 그래서 화살표 다이어그램 자체는 어떤 골든 픽스처도 실제로 통과하지 않는다 — 별도 합성
# 데이터로 직접 검증한다.
def _synthetic_trace_diff_setup() -> tuple[LoadResult, list[Finding]]:
    bundle_path = BUNDLE_DIR / "scenario_clean.json"  # 최소한의 유효 bundle 뼈대를 빌려온다
    load_result = load_bundle(bundle_path)

    v0_label, v1_label = load_result.baseline.label, load_result.candidate.label
    tc = load_result.trials[0].testcase_id

    traces = [
        TraceStep(testcase_id=tc, agent_label=v0_label, run_id="r0", trial=1, step_index=0,
                   node_role=NodeRole.CLASSIFY, type=StepType.LLM_CALL, outcome=StepOutcome.OK),
        TraceStep(testcase_id=tc, agent_label=v0_label, run_id="r0", trial=1, step_index=1,
                   node_role=NodeRole.EXECUTE_TOOL, type=StepType.TOOL_CALL, outcome=StepOutcome.OK,
                   arguments_valid=True),
        TraceStep(testcase_id=tc, agent_label=v1_label, run_id="r1", trial=1, step_index=0,
                   node_role=NodeRole.CLASSIFY, type=StepType.LLM_CALL, outcome=StepOutcome.OK),
        TraceStep(testcase_id=tc, agent_label=v1_label, run_id="r1", trial=1, step_index=1,
                   node_role=NodeRole.EXECUTE_TOOL, type=StepType.TOOL_CALL, outcome=StepOutcome.FAIL,
                   arguments_valid=False, error_type="TOOL_ARG_SCHEMA_MISMATCH"),
    ]
    load_result = LoadResult(
        bundle_id=load_result.bundle_id, created_at=load_result.created_at, suite=load_result.suite,
        baseline=load_result.baseline, candidate=load_result.candidate, change_note=load_result.change_note,
        trials=load_result.trials, traces=traces, unpaired_testcases=[],
    )

    finding = Finding(
        finding_id="F-R-02", type="REGRESSION", severity="P0", rule_id="R-02",
        title="test", affected_testcases=[tc],
        evidence=Evidence(metric="tool_schema_valid_rate", v0=1.0, v1=0.0, delta_pp=-100.0),
        first_divergence=FirstDivergence(
            node_role=NodeRole.EXECUTE_TOOL, step_index=1, detail="arguments_valid=False"
        ),
    )
    return load_result, [finding]


def test_sequence_for_orders_steps_by_index() -> None:
    load_result, _findings = _synthetic_trace_diff_setup()
    v1_label = load_result.candidate.label
    tc = load_result.trials[0].testcase_id
    steps = _sequence_for(load_result.traces, tc, v1_label)
    assert [s.step_index for s in steps] == [0, 1]


def test_arrow_marks_failed_tool_call() -> None:
    load_result, _findings = _synthetic_trace_diff_setup()
    v1_label = load_result.candidate.label
    tc = load_result.trials[0].testcase_id
    steps = _sequence_for(load_result.traces, tc, v1_label)
    arrow = _arrow(steps)
    assert "EXECUTE_TOOL(FAIL)" in arrow
    assert arrow.strip().endswith("✘")


def test_build_trace_diffs_finds_the_divergence() -> None:
    load_result, findings = _synthetic_trace_diff_setup()
    report, _ = build_report_for("scenario_clean")  # 뼈대용, findings는 아래서 직접 넣는다
    report = report.model_copy(update={"findings": findings})

    diffs = _build_trace_diffs(report, load_result)
    assert len(diffs) == 1
    assert diffs[0]["node_role"] == "EXECUTE_TOOL"
    assert "✔" in diffs[0]["v0_arrow"]
    assert "✘" in diffs[0]["v1_arrow"]
