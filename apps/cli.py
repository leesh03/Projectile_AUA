"""로컬 실행 진입점.

    uv run python -m apps.cli run --bundle fixtures/bundles/scenario_a.json --out reports/rpt_a --no-llm

실행 순서가 곧 숫자 방어 장치다: **보고서를 먼저 완성한 뒤에 LLM을 부른다.**
summary·evidence가 이미 확정된 다음에 LLM이 들어오므로, LLM은 구조적으로 수치를 만질 수 없다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from core.candidate import generate_candidates
from core.detector import DetectionContext, run_rules
from core.diagnosis import LLMClient, diagnose
from core.diff.aggregate import aggregate
from core.diff.compare import compare
from core.report import build_report, render_markdown
from core.schemas.loader import load_bundle
from core.validation import candidate_with_result, validate_candidate

app = typer.Typer(help="Agent Upgrade Auditor CLI")


def _make_console_utf8_safe() -> None:
    """Windows 기본 콘솔(cp949)에서 '—' 같은 문자를 찍다가 죽는 걸 막는다.

    보고서 파일은 항상 utf-8로 쓰므로 영향이 없고 콘솔 출력만 문제였다.
    데모 도중 CLI가 UnicodeEncodeError로 죽는 사고를 막기 위한 방어다.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


@app.callback()
def _callback() -> None:
    """`run` 서브커맨드를 강제하기 위한 콜백. 커맨드가 하나뿐이면 Typer가 서브커맨드 이름을 생략해버린다."""
    _make_console_utf8_safe()


@app.command()
def run(
    bundle: Path = typer.Option(..., "--bundle", exists=True, help="AuditBundle JSON 경로"),
    out: Path = typer.Option(..., "--out", help="출력 경로 접두사. <out>.json / <out>.md로 저장된다"),
    no_llm: bool = typer.Option(False, "--no-llm", help="LLM 진단을 건너뛰고 규칙 기반 보고서만 만든다"),
    no_candidates: bool = typer.Option(False, "--no-candidates", help="규칙 기반 수정 후보 생성을 건너뛴다"),
    revalidation_bundle: Path | None = typer.Option(
        None,
        "--revalidation-bundle",
        exists=True,
        help="후보 적용 전후의 별도 AuditBundle. 지정하면 품질·안전·효율 Gate를 실행한다.",
    ),
    candidate_id: str | None = typer.Option(
        None,
        "--candidate-id",
        help="재검증할 candidate_id. 생략하면 첫 번째 후보를 사용한다.",
    ),
    quality_margin: float = typer.Option(0.0, "--quality-margin", min=0.0),
    allowed_safety_violations: int = typer.Option(
        0,
        "--allowed-safety-violations",
        min=0,
    ),
) -> None:
    load_result = load_bundle(bundle)
    agg = aggregate(load_result)
    diff = compare(agg)
    ctx = DetectionContext(load_result=load_result, agg=agg, diff=diff)
    findings, skipped_rules = run_rules(ctx)

    report_id = out.stem if out.stem.startswith("rpt") else f"rpt_{out.stem}"
    report = build_report(
        report_id=report_id,
        load_result=load_result,
        agg=agg,
        diff=diff,
        findings=findings,
    )

    # 여기서부터 LLM. 위에서 report가 이미 확정됐으므로 summary/evidence는 못 바뀐다.
    if not no_llm:
        result = diagnose(report.findings, LLMClient.from_env())
        report = report.model_copy(update={"findings": result.findings})
        for note in result.notes:
            typer.echo(f"[llm] {note}")
        if result.scrubbed_count:
            typer.echo(f"[llm] 설명문 {result.scrubbed_count}건에서 수치를 제거했습니다")

    candidates = [] if no_candidates else generate_candidates(report.findings)
    revalidation = []
    if revalidation_bundle is not None:
        if not candidates:
            raise typer.BadParameter(
                "재검증할 Candidate가 없습니다. --no-candidates를 제거하거나 Finding이 있는 Bundle을 사용하세요."
            )
        selected_id = candidate_id or candidates[0].candidate_id
        selected = next((item for item in candidates if item.candidate_id == selected_id), None)
        if selected is None:
            raise typer.BadParameter(
                f"알 수 없는 candidate_id={selected_id!r}; 가능한 값: "
                f"{[item.candidate_id for item in candidates]}"
            )
        revalidation_load = load_bundle(revalidation_bundle)
        result = validate_candidate(
            selected,
            revalidation_load,
            quality_margin=quality_margin,
            allowed_safety_violations=allowed_safety_violations,
        )
        candidates = [
            candidate_with_result(item, result) if item.candidate_id == selected_id else item
            for item in candidates
        ]
        revalidation.append(result)

    report = report.model_copy(
        update={"candidates": candidates, "revalidation": revalidation}
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    json_path = out.with_suffix(".json")
    md_path = out.with_suffix(".md")
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report, load_result=load_result), encoding="utf-8")

    typer.echo(f"verdict: {report.verdict.value}")
    typer.echo(f"findings: {len(report.findings)}건 (SKIPPED 규칙 {len(skipped_rules)}개)")
    if load_result.unpaired_testcases:
        typer.echo(f"unpaired testcases: {load_result.unpaired_testcases}")
    typer.echo(f"wrote {json_path}")
    typer.echo(f"wrote {md_path}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
