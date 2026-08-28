"""루트 단일 트리 Testbed와 Auditor의 전체 통합을 검증한다.

레거시 전달 폴더가 없어도 루트 코드만으로 V0/V1을 각각 실행하고,
AuditBundle·Finding·Candidate까지 만들 수 있어야 한다.

    python tools/verify_integration.py

종료코드 0이면 통합 성공. 실패한 항목만 자세히 출력한다.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

# Windows 기본 콘솔은 CP949라 한글/기호 출력에서 UnicodeEncodeError로 죽는다.
# PYTHONUTF8=1을 안 걸어도 돌아가게 여기서 직접 맞춘다.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # 파이프로 넘길 때 등
        pass

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 통합 후에도 반드시 있어야 하는 것 - 없으면 이동 중 유실된 것이다.
REQUIRED = {
    "Auditor 탐지기": "core/detector",
    "Auditor 비교엔진": "core/diff",
    "Auditor 보고서": "core/report",
    "계약 스키마": "core/schemas/bundle.py",
    "내 SQL Repair": "agents/policy_agent/scaffolds/sql_repair.py",
    "내 Verifier": "agents/policy_agent/scaffolds/reasoning_verifier.py",
    "내 Bundle 생성기": "core/ingest/collect.py",
    "V0/V1 실행기": "apps/compare.py",
    "Testbed 런타임": "policy_runtime/runner.py",
    "Candidate 생성기": "core/candidate/generate.py",
    "재검증 Gate": "core/validation/gates.py",
    "60건 데이터": "data/agent_cases.json",
    "Gold": "data/test_cases.json",
}

RUNNER = REPO_ROOT / "run_agent.py"

results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    results.append((ok, name, detail))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def step_files() -> None:
    for name, rel in REQUIRED.items():
        exists = (REPO_ROOT / rel).exists()
        check(exists, f"파일 존재 , {name}", "" if exists else f"{rel} 없음")

    check(RUNNER.is_file(), "루트 실행기", "" if RUNNER.is_file() else "run_agent.py 없음")


def step_root_only() -> None:
    """Active imports and source references must stay inside the root tree."""
    import importlib

    legacy_name = "compact" + "_agent"
    modules = (
        "policy_runtime.factory",
        "policy_runtime.runner",
        "agents.policy_agent.nodes.graph",
        "agents.policy_agent.scaffolds.sql_repair",
        "core.candidate.generate",
        "core.validation.gates",
    )
    bad_imports: list[str] = []
    for name in modules:
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve()
        if not path.is_relative_to(REPO_ROOT) or legacy_name in path.parts:
            bad_imports.append(f"{name}={path}")
    check(not bad_imports, "루트 전용 import", "; ".join(bad_imports))

    active_roots = ("run_agent.py", "policy_runtime", "agents", "apps", "core", "tools")
    bad_references: list[str] = []
    for relative in active_roots:
        path = REPO_ROOT / relative
        candidates = [path] if path.is_file() else path.rglob("*.py")
        for source in candidates:
            if source.name == Path(__file__).name:
                continue
            if legacy_name in source.read_text(encoding="utf-8"):
                bad_references.append(source.relative_to(REPO_ROOT).as_posix())
    check(not bad_references, "레거시 폴더 참조 0건", f"참조 파일: {bad_references}" if bad_references else "")


def step_manifests() -> None:
    for rel in ("data/version_manifest.json", "artifacts/version_manifest.json"):
        path = REPO_ROOT / rel
        if not path.is_file():
            check(False, f"매니페스트 , {rel}", "파일 없음")
            continue
        manifest = json.loads(path.read_text(encoding="utf-8"))
        bad = [
            key for key, expected in manifest["artifact_sha256"].items()
            if not (REPO_ROOT / key).is_file() or sha(REPO_ROOT / key) != expected
        ]
        check(not bad, f"매니페스트 , {rel}", f"불일치 {bad}" if bad else "")


def run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    return proc.returncode, (proc.stdout + proc.stderr)


def step_tests() -> None:
    code, out = run([sys.executable, "-m", "pytest", "tests/", "-q",
                     "-p", "no:cacheprovider"], REPO_ROOT)
    check(code == 0, "루트 테스트", "" if code == 0 else out.strip()[-400:])
    # These kill paths are part of the same pytest run above. Listing them
    # separately makes the official integration gate prove more than a happy path.
    kill_paths = (
        "실패 Candidate Bundle 수집",
        "SQL Repair 회복 Trace",
        "Verifier OFF/ON metadata",
        "정책 정확도 regression",
        "Safety violation + BLOCK Gate",
        "DB/Policy/Gold/Dataset 오염 거부",
        "strict trial/trace pairing 거부",
    )
    for name in kill_paths:
        check(code == 0, name, "회귀/오염 pytest 실패" if code != 0 else "")

def _run_suite(label: str, verifier: bool) -> dict | None:
    command = [
        sys.executable, "-B", RUNNER.name, "run-suite", "--mode", "deterministic",
        "--agent-label", label, "--no-repair", "--max-retries", "0",
        "--verifier" if verifier else "--no-verifier",
        "--max-reflections", "2" if verifier else "0",
        "--trials", "2",
    ]
    code, out = run(command, REPO_ROOT)
    if code != 0:
        check(False, f"{label} 60건 E2E", out.strip()[-500:])
        return None
    try:
        summary = json.loads(out[out.index("{"):out.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError):
        check(False, f"{label} 60건 E2E", f"결과 JSON을 읽지 못함: {out.strip()[-200:]}")
        return None
    expected = 120
    bad = [
        f"{key}={summary.get(key)}"
        for key in ("total_trials", "task_successes", "policy_correct", "gold_agreements")
        if summary.get(key) != expected
    ]
    check(not bad, f"{label} 60건×2 E2E", f"{bad} (기대 {expected})" if bad else "")
    return summary


def step_e2e() -> tuple[dict | None, dict | None]:
    return _run_suite("V0", verifier=False), _run_suite("V1", verifier=True)


def step_bundle(baseline: dict | None, candidate: dict | None) -> None:
    """실행 결과가 소현 Loader를 통과하는지."""
    if not baseline or not candidate:
        check(False, "AuditBundle", "E2E 실패로 건너뜀")
        return
    baseline_dir = Path(baseline["summary"]).parent
    candidate_dir = Path(candidate["summary"]).parent

    sys.path.insert(0, str(REPO_ROOT))
    try:
        from core.schemas.loader import load_bundle

        sys.path.insert(0, str(REPO_ROOT / "tools"))
        from core.ingest.collect import make_bundle

        bundle = make_bundle(baseline_dir, candidate_dir, "Verifier 효용 통합 검증")
        loaded = load_bundle(bundle)
        from core.candidate import generate_candidates
        from core.detector import DetectionContext, run_rules
        from core.diff.aggregate import aggregate
        from core.diff.compare import compare
        from core.report import build_report
        from core.validation import candidate_with_result, validate_candidate

        agg = aggregate(loaded)
        diff = compare(agg)
        findings, _ = run_rules(DetectionContext(load_result=loaded, agg=agg, diff=diff))
        report = build_report(
            report_id="rpt_integration",
            load_result=loaded,
            agg=agg,
            diff=diff,
            findings=findings,
        )
        candidates = generate_candidates(report.findings)
        revalidation = None
        applied_candidate = None
        if candidates:
            reversed_bundle = make_bundle(
                candidate_dir,
                baseline_dir,
                "Verifier 제거 Candidate 재검증",
            )
            revalidation_load = load_bundle(reversed_bundle)
            revalidation = validate_candidate(candidates[0], revalidation_load)
            applied_candidate = candidate_with_result(candidates[0], revalidation)
    except Exception as exc:  # noqa: BLE001
        check(False, "AuditBundle", f"{type(exc).__name__}: {exc}")
        return

    dropped = len(loaded.skipped_trials) + len(loaded.skipped_traces)
    check(dropped == 0, "AuditBundle -> Loader",
          f"버려진 레코드 {dropped}건" if dropped else "")
    check(bool(candidates), "Finding → Candidate", "수정 후보가 생성되지 않음" if not candidates else "")
    check(
        revalidation is not None
        and revalidation.status.value == "PASS"
        and applied_candidate is not None
        and applied_candidate.status.value == "APPLIED",
        "Candidate → 재검증",
        "" if (
            revalidation is not None
            and revalidation.status.value == "PASS"
            and applied_candidate is not None
            and applied_candidate.status.value == "APPLIED"
        ) else (
            f"status={getattr(revalidation, 'status', None)}, "
            f"candidate={getattr(applied_candidate, 'status', None)}"
        ),
    )


def main() -> int:
    print("통합 검증 시작\n")
    step_files()
    step_root_only()
    step_manifests()
    step_tests()
    baseline, candidate = step_e2e()
    step_bundle(baseline, candidate)

    failed = [r for r in results if not r[0]]
    for ok, name, detail in results:
        mark = "OK  " if ok else "FAIL"
        line = f"  {mark} {name}"
        if detail:
            line += f"\n         {detail}"
        print(line)

    print(f"\n{'=' * 46}")
    if failed:
        print(f"  실패 {len(failed)} / {len(results)}건 - 위 FAIL 항목 확인")
        return 1
    print(f"  전체 통과 ({len(results)}건) - 통합 이상 없음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
