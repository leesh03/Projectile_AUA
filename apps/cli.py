"""로컬 실행 진입점.

    uv run auditor run --bundle fixtures/bundles/scenario_a.json --out reports/rpt_a --no-llm

`--no-llm`은 지금 만들어 두지만 아직 효과가 없다 — L5(core/diagnosis/, P5)가 생기기 전까지는
모든 실행이 사실상 --no-llm이다. P5가 들어오면 여기서 분기한다.
"""

from __future__ import annotations

from pathlib import Path

import typer

from core.detector import DetectionContext, run_rules
from core.diff.aggregate import aggregate
from core.diff.compare import compare
from core.report import build_report, render_markdown
from core.schemas.loader import load_bundle

app = typer.Typer(help="Agent Upgrade Auditor CLI")


@app.callback()
def _callback() -> None:
    """`run` 서브커맨드를 강제하기 위한 콜백. 커맨드가 하나뿐이면 Typer가 서브커맨드 이름을 생략해버린다."""


@app.command()
def run(
    bundle: Path = typer.Option(..., "--bundle", exists=True, help="AuditBundle JSON 경로"),  # noqa: B008
    out: Path = typer.Option(..., "--out", help="출력 경로 접두사. <out>.json / <out>.md로 저장된다"),  # noqa: B008
    no_llm: bool = typer.Option(
        False, "--no-llm", help="LLM 진단을 건너뛴다 (P5 전까지는 이 값과 무관하게 항상 no-llm으로 동작)"
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
