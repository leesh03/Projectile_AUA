"""L(Report Renderer). AuditBundle 파이프라인의 마지막 단계 — UpgradeReport 조립 + Markdown 렌더링."""

from core.report.build import build_report
from core.report.render import render_markdown

__all__ = ["build_report", "render_markdown"]
