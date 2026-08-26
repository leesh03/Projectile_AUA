"""L5 — LLM 진단 계층. Finding에 사람 언어 설명과 묶음을 붙인다.

계약 3가지:
1. **숫자는 절대 안 바꾼다.** Finding.evidence는 손대지 않는다. explanation/cluster_*만 채운다.
2. **각 호출은 독립 실패한다.** cluster가 실패해도 explain은 시도하고, 둘 다 실패해도
   원본 Finding 목록이 그대로 반환된다.
3. **순서는 코드가 정한다.** LLM의 rank는 참고용으로만 받고, 최종 정렬은 P4 build.py의
   severity 기준을 그대로 쓴다. LLM이 P0를 뒤로 미루는 걸 허용하면 안 되기 때문이다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from core.diagnosis.client import LLMClient
from core.diagnosis.guard import scrub_numbers
from core.diagnosis.schemas import ClusterResponse, ExplainResponse
from core.schemas.finding import Finding

logger = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


@dataclass
class DiagnosisResult:
    findings: list[Finding]
    clustered: bool = False
    explained: bool = False
    scrubbed_count: int = 0
    notes: list[str] = field(default_factory=list)


def _load_prompt(name: str) -> str:
    return (PROMPT_DIR / f"{name}.txt").read_text(encoding="utf-8")


def _findings_block(findings: list[Finding]) -> str:
    """LLM에 넘길 Finding 요약. 수치는 넣지 않는다 — LLM이 숫자를 되뇌일 빌미를 주지 않는다."""
    lines = []
    for f in findings:
        lines.append(
            f"- finding_id={f.finding_id} | rule_id={f.rule_id} | 유형={f.type.value} "
            f"| 심각도={f.severity.value} | 영향 케이스 수는 생략 | 제목: {f.title}"
        )
    return "\n".join(lines)


def _apply_clusters(findings: list[Finding], response: ClusterResponse) -> tuple[list[Finding], list[str]]:
    valid_ids = {f.finding_id for f in findings}
    notes: list[str] = []

    assignment: dict[str, tuple[str, str]] = {}
    for cluster in response.clusters:
        title, _ = scrub_numbers(cluster.title, context=f"cluster {cluster.cluster_id}")
        for fid in cluster.finding_ids:
            if fid not in valid_ids:
                notes.append(f"LLM이 존재하지 않는 finding_id를 반환해 무시함: {fid}")
                continue
            if fid in assignment:
                notes.append(f"LLM이 {fid}을 여러 묶음에 넣어 첫 번째만 사용함")
                continue
            assignment[fid] = (cluster.cluster_id, title)

    updated = [
        f.model_copy(update={"cluster_id": assignment[f.finding_id][0], "cluster_title": assignment[f.finding_id][1]})
        if f.finding_id in assignment
        else f
        for f in findings
    ]
    return updated, notes


def _apply_explanations(
    findings: list[Finding], response: ExplainResponse
) -> tuple[list[Finding], list[str], int]:
    valid_ids = {f.finding_id for f in findings}
    notes: list[str] = []
    scrubbed_count = 0

    by_id: dict[str, str] = {}
    for item in response.explanations:
        if item.finding_id not in valid_ids:
            notes.append(f"LLM이 존재하지 않는 finding_id를 반환해 무시함: {item.finding_id}")
            continue
        text, changed = scrub_numbers(item.explanation, context=f"finding {item.finding_id}")
        if changed:
            scrubbed_count += 1
        by_id[item.finding_id] = text

    updated = [
        f.model_copy(update={"explanation": by_id[f.finding_id]}) if f.finding_id in by_id else f
        for f in findings
    ]
    return updated, notes, scrubbed_count


def _safe_call(client: LLMClient, *, function: str, prompt: str, response_model: type):
    """LLMClient는 자체적으로 예외를 흡수하지만, 여기서 한 겹 더 막는다.

    이 함수가 예외를 흘리면 보고서 전체가 안 나온다. 그 대가가 너무 커서 중복 방어를 감수한다.
    """
    try:
        return client.complete_json(function=function, prompt=prompt, response_model=response_model)
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s 호출에서 예외가 새어나와 폴백합니다: %s", function, exc)
        return None


def diagnose(findings: list[Finding], client: LLMClient | None) -> DiagnosisResult:
    """Finding에 LLM 설명·묶음을 붙인다. 실패하면 원본을 그대로 돌려준다 (예외 없음)."""
    if not findings:
        return DiagnosisResult(findings=findings)
    if client is None or not client.available:
        return DiagnosisResult(findings=findings, notes=["LLM 비활성 — 규칙 기반 결과만 사용"])

    result = DiagnosisResult(findings=list(findings))
    block = _findings_block(findings)

    cluster_response = _safe_call(
        client,
        function="cluster_findings",
        prompt=_load_prompt("cluster_findings").format(findings_block=block),
        response_model=ClusterResponse,
    )
    if cluster_response is not None:
        result.findings, notes = _apply_clusters(result.findings, cluster_response)
        result.clustered = True
        result.notes.extend(notes)
    else:
        result.notes.append("cluster_findings 실패 — rule_id 그대로 나열")

    explain_response = _safe_call(
        client,
        function="explain_and_rank",
        prompt=_load_prompt("explain_and_rank").format(findings_block=block),
        response_model=ExplainResponse,
    )
    if explain_response is not None:
        result.findings, notes, scrubbed = _apply_explanations(result.findings, explain_response)
        result.explained = True
        result.scrubbed_count = scrubbed
        result.notes.extend(notes)
    else:
        result.notes.append("explain_and_rank 실패 — severity 정렬만 사용")

    return result
