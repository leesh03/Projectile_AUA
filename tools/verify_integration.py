"""통합 직후 검증 — 준원의 구조 개편이 무엇을 깨뜨렸는지 한 번에 본다.

compact_agent가 루트로 합쳐지면 import 경로와 데이터 위치가 바뀐다.
그때 "안 깨졌다"를 증명하려면 매번 같은 항목을 같은 순서로 확인해야 한다.

    python tools/verify_integration.py

종료코드 0이면 통합 성공. 실패한 항목만 자세히 출력한다.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

# Windows 기본 콘솔은 CP949라 한글/기호 출력에서 UnicodeEncodeError로 죽는다.
# PYTHONUTF8=1을 안 걸어도 돌아가게 여기서 직접 맞춘다.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

REPO_ROOT = Path(__file__).resolve().parents[1]

# 통합 후에도 반드시 있어야 하는 것 — 없으면 이동 중 유실된 것이다.
REQUIRED = {
    "Auditor 탐지기": "core/detector",
    "Auditor 비교엔진": "core/diff",
    "Auditor 보고서": "core/report",
    "계약 스키마": "core/schemas/bundle.py",
    "내 SQL Repair": "agents/policy_agent/scaffolds/sql_repair.py",
    "내 Verifier": "agents/policy_agent/scaffolds/reasoning_verifier.py",
    "내 Bundle 생성기": "tools/make_audit_bundle.py",
    "60건 데이터": "data/agent_cases.json",
    "Gold": "data/test_cases.json",
}

# 실행기는 통합 전후로 위치가 달라진다. 둘 중 하나만 있으면 된다.
RUNNER_CANDIDATES = ("run_agent.py", "compact_agent/run_agent.py")

results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    results.append((ok, name, detail))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha_text(path: Path) -> str:
    """줄바꿈을 정규화해서 해싱한다."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def find_runner() -> Path | None:
    for candidate in RUNNER_CANDIDATES:
        path = REPO_ROOT / candidate
        if path.is_file():
            return path
    return None


def step_files() -> None:
    for name, rel in REQUIRED.items():
        exists = (REPO_ROOT / rel).exists()
        check(exists, f"파일 존재 · {name}", "" if exists else f"{rel} 없음")

    runner = find_runner()
    check(runner is not None, "실행기 위치",
          "" if runner else f"{' 또는 '.join(RUNNER_CANDIDATES)} 모두 없음")


def step_scaffold_sync() -> None:
    """루트 스캐폴드가 실행본에 반영됐는지.

    통합으로 사본이 사라졌다면 검사 대상이 없으므로 통과로 본다.
    """
    root_dir = REPO_ROOT / "agents/policy_agent/scaffolds"
    copy_dir = REPO_ROOT / "compact_agent/agents/policy_agent/scaffolds"
    if not copy_dir.exists():
        check(True, "스캐폴드 사본", "사본 없음 — 단일 트리로 통합됨")
        return

    stale = [
        name for name in ("sql_repair.py", "reasoning_verifier.py", "config.py",
                          "trace.py", "llm.py")
        if (root_dir / name).is_file() and (copy_dir / name).is_file()
        and sha_text(root_dir / name) != sha_text(copy_dir / name)
    ]
    check(not stale, "스캐폴드 사본 동기화",
          f"루트와 다름: {stale}" if stale else "")


def step_manifests() -> None:
    for rel in ("data/version_manifest.json", "artifacts/version_manifest.json"):
        path = REPO_ROOT / rel
        if not path.is_file():
            check(False, f"매니페스트 · {rel}", "파일 없음")
            continue
        manifest = json.loads(path.read_text(encoding="utf-8"))
        bad = [
            key for key, expected in manifest["artifact_sha256"].items()
            if not (REPO_ROOT / key).is_file() or sha(REPO_ROOT / key) != expected
        ]
        check(not bad, f"매니페스트 · {rel}", f"불일치 {bad}" if bad else "")


def run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr)


def step_tests() -> None:
    code, out = run([sys.executable, "-m", "pytest", "tests/", "-q",
                     "-p", "no:cacheprovider"], REPO_ROOT)
    check(code == 0, "루트 테스트", "" if code == 0 else out.strip()[-400:])

    compact_tests = REPO_ROOT / "compact_agent/tests"
    if compact_tests.is_dir():
        code, out = run([sys.executable, "-m", "pytest", "tests/", "-q",
                         "-p", "no:cacheprovider"], REPO_ROOT / "compact_agent")
        check(code == 0, "compact 테스트", "" if code == 0 else out.strip()[-400:])


def step_e2e() -> None:
    """60건 실제 실행. 통합이 깨졌으면 여기서 잡힌다."""
    runner = find_runner()
    if runner is None:
        check(False, "60건 E2E", "실행기를 찾지 못해 건너뜀")
        return

    code, out = run([sys.executable, "-B", runner.name, "run-suite",
                     "--mode", "deterministic"], runner.parent)
    if code != 0:
        check(False, "60건 E2E", out.strip()[-500:])
        return

    try:
        summary = json.loads(out[out.index("{"):out.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError):
        check(False, "60건 E2E", f"결과 JSON을 읽지 못함: {out.strip()[-200:]}")
        return

    expected = 60
    bad = [
        f"{key}={summary.get(key)}"
        for key in ("total_trials", "task_successes", "policy_correct")
        if summary.get(key) != expected
    ]
    check(not bad, "60건 E2E", f"{bad} (기대 {expected})" if bad else "")
    check(summary.get("gold_agreements") == expected, "Gold 대조",
          "" if summary.get("gold_agreements") == expected
          else f"gold_agreements={summary.get('gold_agreements')} — "
               "evaluation/private가 유실됐을 수 있음")
    return summary.get("summary")


def step_bundle(summary_path: str | None) -> None:
    """실행 결과가 소현 Loader를 통과하는지."""
    if not summary_path:
        check(False, "AuditBundle", "E2E 실패로 건너뜀")
        return
    run_dir = Path(summary_path).parent

    sys.path.insert(0, str(REPO_ROOT))
    try:
        from core.schemas.loader import load_bundle  # noqa: PLC0415

        sys.path.insert(0, str(REPO_ROOT / "tools"))
        from make_audit_bundle import make_bundle  # noqa: PLC0415

        bundle = make_bundle(run_dir, run_dir, "통합 검증")
        loaded = load_bundle(bundle)
    except Exception as exc:  # noqa: BLE001
        check(False, "AuditBundle", f"{type(exc).__name__}: {exc}")
        return

    dropped = len(loaded.skipped_trials) + len(loaded.skipped_traces)
    check(dropped == 0, "AuditBundle → Loader",
          f"버려진 레코드 {dropped}건" if dropped else "")


def main() -> int:
    print("통합 검증 시작\n")
    step_files()
    step_scaffold_sync()
    step_manifests()
    step_tests()
    summary_path = step_e2e()
    step_bundle(summary_path)

    failed = [r for r in results if not r[0]]
    for ok, name, detail in results:
        mark = "OK  " if ok else "FAIL"
        line = f"  {mark} {name}"
        if detail:
            line += f"\n         {detail}"
        print(line)

    print(f"\n{'=' * 46}")
    if failed:
        print(f"  실패 {len(failed)} / {len(results)}건 — 위 FAIL 항목 확인")
        return 1
    print(f"  전체 통과 ({len(results)}건) — 통합 이상 없음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
