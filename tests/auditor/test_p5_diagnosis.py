"""P5 완료 게이트 검증.

체크리스트 (AUA_Phase별_개발순서.md):
- `--no-llm`과 기본 실행 모두 보고서가 나온다
- 두 경우의 수치가 100% 동일하다 ★
- 네트워크를 끊어도 보고서가 생성된다
- 비슷한 Regression 3건이 하나로 묶여 나온다

실제 Solar 엔드포인트는 호출하지 않는다. 이 계층의 계약이 "어떤 실패든 None으로 흡수하고
규칙 기반 결과로 폴백한다"이므로, 검증해야 할 것은 대부분 실패 경로다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from core.diagnosis import LLMClient, diagnose, scrub_numbers
from core.diagnosis.schemas import ClusterResponse, ExplainResponse
from core.report import render_markdown
from tests.auditor._golden_utils import SCENARIO_NAMES, build_report_for


@dataclass
class FakeClient:
    """LLMClient와 같은 표면만 흉내낸다. responses에 없는 function은 실패로 간주한다."""

    responses: dict[str, BaseModel] = field(default_factory=dict)
    available: bool = True
    calls: list[str] = field(default_factory=list)

    def complete_json(self, *, function: str, prompt: str, response_model: type) -> Any:
        self.calls.append(function)
        return self.responses.get(function)


class ExplodingClient:
    """네트워크가 끊긴 상황. 실제 LLMClient의 내부 호출이 예외를 던지는 걸 흉내낸다."""

    available = True

    def complete_json(self, *, function: str, prompt: str, response_model: type) -> Any:
        raise ConnectionError("network is unreachable")


# ── 수치 동일성 (P5 핵심 게이트) ──────────────────────────────────────────
def _numeric_view(report) -> dict:
    """보고서에서 '숫자'에 해당하는 부분만 뽑는다. LLM on/off로 이게 달라지면 안 된다."""
    s = report.summary
    return {
        "verdict": report.verdict.value,
        "summary": s.model_dump(),
        "evidence": [f.evidence.model_dump() for f in report.findings],
        "finding_ids": [f.finding_id for f in report.findings],
        "severities": [f.severity.value for f in report.findings],
        "affected": [sorted(f.affected_testcases) for f in report.findings],
        "limitations": report.limitations,
    }


def test_llm_on_off_produces_identical_numbers() -> None:
    """★ 가장 중요한 게이트. LLM이 붙어도 수치·판정·영향 케이스는 한 글자도 안 바뀐다."""
    for name in SCENARIO_NAMES:
        report_off, _ = build_report_for(name)

        client = FakeClient(
            responses={
                "cluster_findings": ClusterResponse(
                    clusters=[
                        {
                            "cluster_id": "C1",
                            "title": "도구 인자 형식이 바뀌면서 생긴 문제",
                            "finding_ids": [f.finding_id for f in report_off.findings],
                        }
                    ]
                    if report_off.findings
                    else []
                ),
                "explain_and_rank": ExplainResponse(
                    explanations=[
                        {"finding_id": f.finding_id, "rank": i + 1, "explanation": "설명문입니다."}
                        for i, f in enumerate(report_off.findings)
                    ]
                ),
            }
        )
        result = diagnose(report_off.findings, client)
        report_on = report_off.model_copy(update={"findings": result.findings})

        assert _numeric_view(report_on) == _numeric_view(report_off), f"{name}에서 수치가 달라짐"


def test_network_failure_still_produces_report() -> None:
    """네트워크가 죽어도 보고서가 나와야 한다. diagnose()는 예외를 밖으로 안 낸다."""
    report, load_result = build_report_for("scenario_a")
    result = diagnose(report.findings, ExplodingClient())

    assert result.findings == report.findings  # 원본 그대로
    assert result.clustered is False
    assert result.explained is False
    markdown = render_markdown(report.model_copy(update={"findings": result.findings}), load_result=load_result)
    assert "Agent Upgrade Risk Report" in markdown


def test_each_call_fails_independently() -> None:
    """cluster가 실패해도 explain은 진행돼야 한다."""
    report, _ = build_report_for("scenario_a")
    client = FakeClient(
        responses={
            "explain_and_rank": ExplainResponse(
                explanations=[
                    {"finding_id": f.finding_id, "rank": 1, "explanation": "설명"} for f in report.findings
                ]
            )
        }
    )
    result = diagnose(report.findings, client)

    assert result.clustered is False
    assert result.explained is True
    assert all(f.explanation == "설명" for f in result.findings)


def test_disabled_client_is_noop() -> None:
    report, _ = build_report_for("scenario_a")
    result = diagnose(report.findings, FakeClient(available=False))
    assert result.findings == report.findings
    assert result.notes == ["LLM 비활성 — 규칙 기반 결과만 사용"]


def test_none_client_is_noop() -> None:
    report, _ = build_report_for("scenario_a")
    result = diagnose(report.findings, None)
    assert result.findings == report.findings


# ── 클러스터링 ────────────────────────────────────────────────────────────
def test_similar_findings_are_clustered_in_markdown() -> None:
    """scenario_a의 Finding 3건(R-01/R-02/R-04)이 하나로 묶여 보고서에 나온다."""
    report, load_result = build_report_for("scenario_a")
    assert len(report.findings) == 3

    client = FakeClient(
        responses={
            "cluster_findings": ClusterResponse(
                clusters=[
                    {
                        "cluster_id": "C1",
                        "title": "도구 인자 형식 변경에서 파생된 실패",
                        "finding_ids": [f.finding_id for f in report.findings],
                    }
                ]
            )
        }
    )
    result = diagnose(report.findings, client)
    markdown = render_markdown(report.model_copy(update={"findings": result.findings}), load_result=load_result)

    assert "같은 원인으로 묶인 Finding" in markdown
    assert "도구 인자 형식 변경에서 파생된 실패" in markdown
    assert "F-01, F-02, F-03" in markdown


def test_unknown_finding_id_from_llm_is_ignored() -> None:
    report, _ = build_report_for("scenario_a")
    client = FakeClient(
        responses={
            "cluster_findings": ClusterResponse(
                clusters=[{"cluster_id": "C1", "title": "제목", "finding_ids": ["F-99", "F-01"]}]
            )
        }
    )
    result = diagnose(report.findings, client)

    assert any("F-99" in n for n in result.notes)
    assert [f.cluster_id for f in result.findings if f.finding_id == "F-01"] == ["C1"]


def test_single_member_cluster_not_shown() -> None:
    """혼자인 묶음은 '묶었다'고 표시할 게 없으므로 렌더링하지 않는다."""
    report, load_result = build_report_for("scenario_a")
    client = FakeClient(
        responses={
            "cluster_findings": ClusterResponse(
                clusters=[{"cluster_id": "C1", "title": "혼자", "finding_ids": ["F-01"]}]
            )
        }
    )
    result = diagnose(report.findings, client)
    markdown = render_markdown(report.model_copy(update={"findings": result.findings}), load_result=load_result)
    assert "같은 원인으로 묶인 Finding" not in markdown


# ── 숫자 방어 (P5-3) ──────────────────────────────────────────────────────
def test_scrub_numbers_replaces_percentages() -> None:
    text, changed = scrub_numbers("성공률이 25%p 떨어졌습니다.")
    assert changed is True
    assert "25" not in text
    assert "(수치는 표 참조)" in text


def test_scrub_numbers_keeps_identifiers() -> None:
    """F-01, R-02, V0/V1, P0 같은 식별자는 수치가 아니므로 살려둔다."""
    text, changed = scrub_numbers("F-01은 R-02 규칙이며 V0 대비 V1에서 나빠졌습니다. 심각도는 P0입니다.")
    assert changed is False
    assert "F-01" in text
    assert "R-02" in text
    assert "V0" in text and "V1" in text
    assert "P0" in text


def test_scrub_numbers_replaces_counts_and_multiples() -> None:
    text, changed = scrub_numbers("5건에서 재시도가 3배로 늘었고 평균 1.8회입니다.")
    assert changed is True
    for token in ("5건", "3배", "1.8회"):
        assert token not in text


def test_scrub_numbers_noop_on_clean_text() -> None:
    original = "도구 인자 형식이 바뀌면서 일부 요청이 실패한 것으로 보입니다."
    text, changed = scrub_numbers(original)
    assert changed is False
    assert text == original


def test_explanation_from_llm_is_scrubbed_end_to_end() -> None:
    report, _ = build_report_for("scenario_a")
    client = FakeClient(
        responses={
            "explain_and_rank": ExplainResponse(
                explanations=[
                    {
                        "finding_id": report.findings[0].finding_id,
                        "rank": 1,
                        "explanation": "성공률이 100%에서 75%로 떨어졌습니다.",
                    }
                ]
            )
        }
    )
    result = diagnose(report.findings, client)

    assert result.scrubbed_count == 1
    explanation = result.findings[0].explanation
    assert "100%" not in explanation
    assert "75%" not in explanation


# ── 클라이언트 설정 ───────────────────────────────────────────────────────
def test_client_without_api_key_is_unavailable() -> None:
    """키가 없으면 호출을 시도조차 하지 않는다 — --no-llm과 같은 경로로 떨어진다."""
    client = LLMClient(api_key=None)
    assert client.available is False
    assert client.complete_json(function="x", prompt="p", response_model=ClusterResponse) is None
    assert client.call_logs == []
