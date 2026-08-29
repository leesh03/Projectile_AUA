"""실행 로그 조각을 파일 하나로 묶는다. 계약은 모른다.

이 스크립트는 **운반 도구**다. zip을 뜨는 것과 같은 일을 한다.
필드가 무슨 뜻인지, 어떤 값이 유효한지 판단하지 않는다.
그 판단은 로그를 받는 쪽(Auditor / 스킬)이 한다.

사용:
  python tools/pack_logs.py \
      --run V0=reports/runs/<V0_run> \
      --run V1=reports/runs/<V1_run> \
      --change-note "무엇을 바꿨는지 한 줄" \
      --out reports/logs/agent_logs.json

  --limit N        케이스를 앞에서 N개만 담는다 (샘플용)
  --max-trials N   케이스당 trial을 N개만 담는다 (샘플용)
  --drop KEY       trial의 특정 키를 빼고 담는다 (여러 번 지정 가능)

--drop은 운반 편의를 위한 것이다. 기록을 고르거나 값을 바꾸지 않고,
받는 쪽이 읽지 않는 키를 통째로 뺄 뿐이다. 예를 들어 traces는 용량의 대부분을
차지하는데 판정 규칙이 쓰지 않는다면 빼도 결과가 달라지지 않는다.
무엇을 뺐는지는 출력에 남는다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def pack_run(
    run_dir: Path,
    *,
    limit: int | None,
    max_trials: int | None,
    drop: tuple[str, ...] = (),
) -> dict[str, Any]:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest.json이 없습니다: {run_dir}")

    by_case: dict[str, list[Path]] = {}
    for path in sorted(run_dir.glob("*/*/trial_*.json")):
        by_case.setdefault(path.parent.name, []).append(path)

    cases = sorted(by_case)
    if limit is not None:
        cases = cases[:limit]

    trials: list[Any] = []
    for case in cases:
        paths = by_case[case]
        if max_trials is not None:
            paths = paths[:max_trials]
        for path in paths:
            record = _read(path)
            if drop and isinstance(record, dict):
                record = {k: v for k, v in record.items() if k not in drop}
            trials.append(record)

    if not trials:
        raise ValueError(f"trial 파일을 찾지 못했습니다: {run_dir}")
    return {"manifest": _read(manifest_path), "trials": trials}


def main() -> int:
    parser = argparse.ArgumentParser(description="실행 로그 조각을 파일 하나로 묶는다")
    parser.add_argument(
        "--run",
        action="append",
        required=True,
        metavar="LABEL=DIR",
        help="예: --run V0=reports/runs/xxx (두 번 이상 지정)",
    )
    parser.add_argument("--change-note", default=None)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-trials", type=int, default=None)
    parser.add_argument(
        "--drop",
        action="append",
        default=[],
        metavar="KEY",
        help="trial에서 뺄 키. 예: --drop traces",
    )
    args = parser.parse_args()

    runs = []
    for spec in args.run:
        if "=" not in spec:
            parser.error(f"--run 은 LABEL=DIR 형식이어야 합니다: {spec}")
        label, _, raw = spec.partition("=")
        packed = pack_run(
            Path(raw),
            limit=args.limit,
            max_trials=args.max_trials,
            drop=tuple(args.drop),
        )
        packed["label"] = label
        runs.append(packed)

    payload: dict[str, Any] = {"runs": runs}
    if args.change_note:
        payload["change_note"] = args.change_note
    if args.drop:
        payload["dropped_keys"] = sorted(set(args.drop))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    size_kb = args.out.stat().st_size // 1024
    print(f"logs: {args.out}  ({size_kb}KB)")
    for run in runs:
        print(f"  {run['label']}  trials {len(run['trials'])}")
    if args.drop:
        print(f"  뺀 키: {', '.join(sorted(set(args.drop)))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
