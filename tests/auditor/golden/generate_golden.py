"""골든 파일을 (재)생성한다. 집계 로직을 의도적으로 바꿀 때만 수동으로 실행한다.

    uv run python -m tests.auditor.golden.generate_golden

평소 pytest 실행에서는 절대 자동으로 갱신되지 않는다 — 그러면 회귀를 못 잡는다.
"""

from __future__ import annotations

import json

from tests.auditor._golden_utils import (
    GOLDEN_DIR,
    SCENARIO_NAMES,
    render_markdown_for,
    run_pipeline,
    summarize,
    summarize_detection,
    summarize_report,
)


def _write_json(name: str, data: dict) -> None:
    path = GOLDEN_DIR / f"{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path}")


def _write_text(name: str, text: str) -> None:
    path = GOLDEN_DIR / f"{name}.md"
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path}")


def main() -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for name in SCENARIO_NAMES:
        load_result, agg, diff = run_pipeline(name)
        _write_json(name, summarize(load_result, agg, diff))
        _write_json(f"p3_{name}", summarize_detection(load_result, agg, diff))

        report, markdown = render_markdown_for(name)
        _write_json(f"p4_{name}", summarize_report(report))
        _write_text(f"p4_{name}", markdown)


if __name__ == "__main__":
    main()
