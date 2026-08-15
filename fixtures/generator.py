"""Mock 실행 기록(AuditBundle) 생성기 — 소현 담당.

팀원 산출물(Testbed) 없이 core/(P2~P8)를 개발하기 위한 핵심 도구.
시드를 고정했기 때문에 다시 실행해도 항상 바이트 단위로 같은 JSON이 나온다.
`created_at` 같은 시각 필드도 고정값을 쓴다 — wall-clock을 쓰면 재현성이 깨진다.

시나리오 6종은 각각 core/detector(P3)의 규칙 하나만 의도적으로 발화시키도록 설계했다.
직접 실행하면 fixtures/bundles/ 아래에 6개 JSON을 쓴다:

    uv run python -m fixtures.generator
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.schemas import AgentVersion, AuditBundle, SuiteInfo, TraceStep, TrialResult

KST = timezone(timedelta(hours=9))
BUNDLE_DIR = Path(__file__).resolve().parent / "bundles"

# ── 공통 자리표시자 ──────────────────────────────────────────────────────
# 우혁의 실제 test_cases.json이 오기 전까지 쓰는 20개 Mock TestCase.
# 난이도 분포(Easy 6 / Medium 8 / Hard 6)는 data/README.md 계획과 맞췄다.
TESTCASE_IDS: list[str] = [f"case_{i:02d}" for i in range(1, 21)]
DIFFICULTY_BY_CASE: dict[str, str] = {
    **{tc: "Easy" for tc in TESTCASE_IDS[0:6]},
    **{tc: "Medium" for tc in TESTCASE_IDS[6:14]},
    **{tc: "Hard" for tc in TESTCASE_IDS[14:20]},
}
TRIALS_PER_CASE = 2

# 시나리오별 고정 시드. hash()는 프로세스마다 값이 달라질 수 있어 쓰지 않는다.
SEEDS = {
    "scenario_a": 101,
    "scenario_clean": 102,
    "scenario_c": 103,
    "scenario_b": 104,
    "scenario_safety": 105,
    "scenario_broken": 106,
}


def _v0() -> AgentVersion:
    return AgentVersion(
        label="V0",
        agent_id="policy_agent",
        version="v0",
        model_id="MODEL_A",
        prompt_version="p1",
        tool_schema_version="t1",
        workflow_version="w1",
        retry_policy="max_retry=2",
        verifier_policy="reflection=0",
        commit="mock0000",
    )


def _v1(**overrides: Any) -> AgentVersion:
    base = dict(
        label="V1",
        agent_id="policy_agent",
        version="v1",
        model_id="MODEL_B",
        prompt_version="p2",
        tool_schema_version="t1",
        workflow_version="w1",
        retry_policy="max_retry=2",
        verifier_policy="reflection=0",
        commit="mock1111",
    )
    base.update(overrides)
    return AgentVersion(**base)


def _suite() -> SuiteInfo:
    return SuiteInfo(suite_id="refund_suite_mock_v1", testcase_ids=TESTCASE_IDS, dataset_version="mock_v1")


def _jitter(rng: random.Random, base: int, spread: int) -> int:
    return max(1, base + rng.randint(-spread, spread))


def _clean_pair(rng: random.Random, testcase_id: str, trial_no: int) -> tuple[TrialResult, TrialResult]:
    """양쪽 버전이 동일하게 동작하는 "문제 없는" trial 쌍. 모든 시나리오의 배경 케이스로 쓴다."""
    common = dict(
        testcase_id=testcase_id,
        trial=trial_no,
        task_success=True,
        policy_correct=True,
        tool_error_count=0,
        retry_count=rng.choice([0, 0, 1]),
        safety_violation=False,
        stop_reason="OK",
        tool_schema_valid=True,
        error_type=None,
        llm_call_count=3,
        difficulty=DIFFICULTY_BY_CASE[testcase_id],
    )
    v0 = TrialResult(agent_label="V0", total_tokens=_jitter(rng, 2400, 150), latency_ms=_jitter(rng, 3400, 300), **common)
    v1 = TrialResult(agent_label="V1", total_tokens=_jitter(rng, 2450, 150), latency_ms=_jitter(rng, 3450, 300), **common)
    return v0, v1


def _bundle_id(name: str) -> str:
    return f"audit_mock_{name}"


def _write(bundle_or_raw: AuditBundle | dict, name: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{name}.json"
    if isinstance(bundle_or_raw, AuditBundle):
        data = bundle_or_raw.model_dump(mode="json")
    else:
        data = bundle_or_raw
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


# ── 시나리오 1순위: scenario_a — R-02 tool 인자 스키마 유효율 하락 ────────
AFFECTED_A = ["case_03", "case_07", "case_12", "case_15", "case_18"]


def build_scenario_a() -> AuditBundle:
    rng = random.Random(SEEDS["scenario_a"])
    trials: list[TrialResult] = []

    for tc in TESTCASE_IDS:
        for trial_no in range(1, TRIALS_PER_CASE + 1):
            if tc in AFFECTED_A:
                v0 = TrialResult(
                    testcase_id=tc, agent_label="V0", trial=trial_no,
                    task_success=True, policy_correct=True, tool_error_count=0,
                    retry_count=0, total_tokens=_jitter(rng, 2400, 150), latency_ms=_jitter(rng, 3400, 300),
                    safety_violation=False, stop_reason="OK", tool_schema_valid=True,
                    error_type=None, llm_call_count=3, difficulty=DIFFICULTY_BY_CASE[tc],
                )
                v1 = TrialResult(
                    testcase_id=tc, agent_label="V1", trial=trial_no,
                    task_success=False, policy_correct=True, tool_error_count=1,
                    retry_count=1, total_tokens=_jitter(rng, 2600, 150), latency_ms=_jitter(rng, 3700, 300),
                    safety_violation=False, stop_reason="TOOL_SCHEMA_ERROR", tool_schema_valid=False,
                    error_type="TOOL_ARG_SCHEMA_MISMATCH", llm_call_count=4, difficulty=DIFFICULTY_BY_CASE[tc],
                )
                trials += [v0, v1]
            else:
                trials += list(_clean_pair(rng, tc, trial_no))

    return AuditBundle(
        bundle_id=_bundle_id("scenario_a"),
        created_at=datetime(2026, 8, 16, 9, 0, 0, tzinfo=KST),
        suite=_suite(),
        baseline=_v0(),
        candidate=_v1(),
        change_note="order_lookup tool 스키마 변경: 인자 이름 order_id -> id",
        trials=trials,
        traces=None,  # 의도적으로 trace 없음: R-02는 trace 없이도 동작해야 하고,
        # O-01/O-02/TraceDiff가 SKIPPED·NOT_AVAILABLE로 우아하게 저하되는지 이 픽스처로 검증한다.
    )


# ── 시나리오 2순위: scenario_clean — 문제 없는 정상 변경 (Finding 0건이 목표) ─
def build_scenario_clean() -> AuditBundle:
    rng = random.Random(SEEDS["scenario_clean"])
    trials: list[TrialResult] = []
    for tc in TESTCASE_IDS:
        for trial_no in range(1, TRIALS_PER_CASE + 1):
            trials += list(_clean_pair(rng, tc, trial_no))

    return AuditBundle(
        bundle_id=_bundle_id("scenario_clean"),
        created_at=datetime(2026, 8, 16, 9, 5, 0, tzinfo=KST),
        suite=_suite(),
        baseline=_v0(),
        candidate=_v1(prompt_version="p1_refactor"),
        change_note="로그 포맷 리팩터링 — 동작 변화 없음",
        trials=trials,
        traces=None,
    )


# ── 시나리오 3순위: scenario_c — E-01 재시도 증가 + O-02 회복률 0 ─────────
AFFECTED_C = ["case_02", "case_06", "case_09", "case_13", "case_17", "case_20"]


def _ok_trace(tc: str, label: str, trial_no: int) -> list[TraceStep]:
    run_id = f"{tc}-{label}-{trial_no}"
    steps = [
        ("CLASSIFY", "llm_call", "ok"),
        ("GENERATE_QUERY", "llm_call", "ok"),
        ("EXECUTE_TOOL", "tool_call", "ok"),
        ("SELECT_POLICY", "code", "ok"),
        ("DECIDE", "code", "ok"),
    ]
    return [
        TraceStep(
            testcase_id=tc, agent_label=label, run_id=run_id, trial=trial_no,
            step_index=i, node_role=role, type=typ, outcome=outcome, iteration=0,
        )
        for i, (role, typ, outcome) in enumerate(steps)
    ]


def _repeated_failure_trace(tc: str, label: str, trial_no: int, *, retries: int) -> list[TraceStep]:
    """같은 error_type으로 iteration마다 재시도하지만 한 번도 회복하지 못하는 trace (O-02)."""
    run_id = f"{tc}-{label}-{trial_no}"
    steps: list[TraceStep] = [
        TraceStep(
            testcase_id=tc, agent_label=label, run_id=run_id, trial=trial_no,
            step_index=0, node_role="CLASSIFY", type="llm_call", outcome="ok", iteration=0,
        )
    ]
    idx = 1
    for it in range(retries):
        steps.append(
            TraceStep(
                testcase_id=tc, agent_label=label, run_id=run_id, trial=trial_no,
                step_index=idx, node_role="GENERATE_QUERY", type="llm_call", outcome="ok", iteration=it,
            )
        )
        idx += 1
        steps.append(
            TraceStep(
                testcase_id=tc, agent_label=label, run_id=run_id, trial=trial_no,
                step_index=idx, node_role="EXECUTE_TOOL", type="tool_call", outcome="fail",
                error_type="SQL_SYNTAX_ERROR", iteration=it,
            )
        )
        idx += 1
        steps.append(
            TraceStep(
                testcase_id=tc, agent_label=label, run_id=run_id, trial=trial_no,
                step_index=idx, node_role="REPAIR_QUERY", type="code", outcome="fail",
                error_type="SQL_SYNTAX_ERROR", iteration=it,
            )
        )
        idx += 1
    return steps


def build_scenario_c() -> AuditBundle:
    rng = random.Random(SEEDS["scenario_c"])
    trials: list[TrialResult] = []
    traces: list[TraceStep] = []

    for tc in TESTCASE_IDS:
        for trial_no in range(1, TRIALS_PER_CASE + 1):
            if tc in AFFECTED_C:
                v0 = TrialResult(
                    testcase_id=tc, agent_label="V0", trial=trial_no,
                    task_success=True, policy_correct=True, tool_error_count=0,
                    retry_count=0, total_tokens=_jitter(rng, 2400, 150), latency_ms=_jitter(rng, 3400, 300),
                    safety_violation=False, stop_reason="OK", tool_schema_valid=True,
                    error_type=None, llm_call_count=3, difficulty=DIFFICULTY_BY_CASE[tc],
                )
                v1 = TrialResult(
                    testcase_id=tc, agent_label="V1", trial=trial_no,
                    task_success=False, policy_correct=True, tool_error_count=5,
                    retry_count=5, total_tokens=_jitter(rng, 5200, 300), latency_ms=_jitter(rng, 7800, 500),
                    safety_violation=False, stop_reason="MAX_RETRY", tool_schema_valid=True,
                    error_type="SQL_SYNTAX_ERROR", llm_call_count=11, difficulty=DIFFICULTY_BY_CASE[tc],
                )
                trials += [v0, v1]
                traces += _ok_trace(tc, "V0", trial_no)
                traces += _repeated_failure_trace(tc, "V1", trial_no, retries=5)
            else:
                v0, v1 = _clean_pair(rng, tc, trial_no)
                trials += [v0, v1]
                traces += _ok_trace(tc, "V0", trial_no)
                traces += _ok_trace(tc, "V1", trial_no)

    return AuditBundle(
        bundle_id=_bundle_id("scenario_c"),
        created_at=datetime(2026, 8, 16, 9, 10, 0, tzinfo=KST),
        suite=_suite(),
        baseline=_v0(),
        candidate=_v1(retry_policy="max_retry=5"),
        change_note="max_retry 2 -> 5로 상향, SQL Repair Loop 재시도 조건 완화",
        trials=trials,
        traces=traces,
    )


# ── 시나리오 4순위: scenario_b — O-01 Verifier가 판정을 한 번도 안 바꿈 ───
def _verify_trace(tc: str, label: str, trial_no: int, *, with_verifier: bool) -> list[TraceStep]:
    run_id = f"{tc}-{label}-{trial_no}"
    steps = [
        ("CLASSIFY", "llm_call", "ok"),
        ("SELECT_POLICY", "code", "ok"),
    ]
    if with_verifier:
        steps.append(("VERIFY_REASONING", "llm_call", "ok"))  # 한 번도 판정을 바꾸지 않음(outcome=ok 고정)
    steps.append(("DECIDE", "code", "ok"))
    return [
        TraceStep(
            testcase_id=tc, agent_label=label, run_id=run_id, trial=trial_no,
            step_index=i, node_role=role, type=typ, outcome=outcome, iteration=0,
        )
        for i, (role, typ, outcome) in enumerate(steps)
    ]


def build_scenario_b() -> AuditBundle:
    rng = random.Random(SEEDS["scenario_b"])
    trials: list[TrialResult] = []
    traces: list[TraceStep] = []

    for tc in TESTCASE_IDS:
        for trial_no in range(1, TRIALS_PER_CASE + 1):
            common = dict(
                testcase_id=tc, trial=trial_no, task_success=True, policy_correct=True,
                tool_error_count=0, retry_count=0, safety_violation=False, stop_reason="OK",
                tool_schema_valid=True, error_type=None, difficulty=DIFFICULTY_BY_CASE[tc],
            )
            v0 = TrialResult(
                agent_label="V0", total_tokens=_jitter(rng, 2400, 120), latency_ms=_jitter(rng, 3400, 250),
                llm_call_count=3, **common,
            )
            v1 = TrialResult(
                # Verifier(VERIFY_REASONING)가 추가돼 LLM 호출 1회·토큰이 소폭 늘지만
                # 성공률·정책정확도는 V0과 동일 — 순수 Opportunity, Regression은 아니다.
                agent_label="V1", total_tokens=_jitter(rng, 2580, 120), latency_ms=_jitter(rng, 3650, 250),
                llm_call_count=4, **common,
            )
            trials += [v0, v1]
            traces += _verify_trace(tc, "V0", trial_no, with_verifier=False)
            traces += _verify_trace(tc, "V1", trial_no, with_verifier=True)

    return AuditBundle(
        bundle_id=_bundle_id("scenario_b"),
        created_at=datetime(2026, 8, 16, 9, 15, 0, tzinfo=KST),
        suite=_suite(),
        baseline=_v0(),
        candidate=_v1(verifier_policy="reflection=1"),
        change_note="정책 판정 뒤에 Reasoning Verifier 단계 추가",
        trials=trials,
        traces=traces,
    )


# ── 시나리오 5순위: scenario_safety — safety_violation 1건 → BLOCK ───────
SAFETY_CASE = "case_10"


def build_scenario_safety() -> AuditBundle:
    rng = random.Random(SEEDS["scenario_safety"])
    trials: list[TrialResult] = []

    for tc in TESTCASE_IDS:
        for trial_no in range(1, TRIALS_PER_CASE + 1):
            if tc == SAFETY_CASE and trial_no == 1:
                v0 = TrialResult(
                    testcase_id=tc, agent_label="V0", trial=trial_no,
                    task_success=True, policy_correct=True, tool_error_count=0,
                    retry_count=0, total_tokens=_jitter(rng, 2400, 150), latency_ms=_jitter(rng, 3400, 300),
                    safety_violation=False, stop_reason="OK", tool_schema_valid=True,
                    error_type=None, llm_call_count=3, difficulty=DIFFICULTY_BY_CASE[tc],
                )
                v1 = TrialResult(
                    testcase_id=tc, agent_label="V1", trial=trial_no,
                    task_success=False, policy_correct=False, tool_error_count=1,
                    retry_count=0, total_tokens=_jitter(rng, 2500, 150), latency_ms=_jitter(rng, 3500, 300),
                    safety_violation=True, stop_reason="PROVIDER_ERROR", tool_schema_valid=True,
                    error_type="FORBIDDEN_SQL_COMMAND", llm_call_count=3, difficulty=DIFFICULTY_BY_CASE[tc],
                )
                trials += [v0, v1]
            else:
                trials += list(_clean_pair(rng, tc, trial_no))

    return AuditBundle(
        bundle_id=_bundle_id("scenario_safety"),
        created_at=datetime(2026, 8, 16, 9, 20, 0, tzinfo=KST),
        suite=_suite(),
        baseline=_v0(),
        candidate=_v1(),
        change_note="프롬프트 수정 중 SQL Guard 우회 시도 1건 발생 (차단됨)",
        trials=trials,
        traces=None,
    )


# ── 시나리오 6순위: scenario_broken — 계약 위반 (페어링 실패 + 필수 필드 누락) ─
# 이 픽스처는 의도적으로 AuditBundle 스키마를 어긴다.
# Pydantic 모델을 거치지 않고 raw dict로 직접 만든다 — loader.py(P2)가
# "전체 실패시키지 않고 규칙별 SKIPPED로 우아하게 저하"하는지 검증하는 스트레스 테스트용이다.
UNPAIRED_CASES = ["case_19", "case_20"]  # V0에만 있고 V1에는 없음
MISSING_FIELD_CASE = "case_05"  # 이 케이스의 V1 trial 1건에서 stop_reason 키 자체를 뺀다


def build_scenario_broken() -> dict:
    rng = random.Random(SEEDS["scenario_broken"])
    trials: list[dict] = []

    for tc in TESTCASE_IDS:
        for trial_no in range(1, TRIALS_PER_CASE + 1):
            v0, v1 = _clean_pair(rng, tc, trial_no)
            trials.append(v0.model_dump(mode="json"))

            if tc in UNPAIRED_CASES:
                continue  # V1 쪽을 아예 안 남김 -> UNPAIRED

            v1_dict = v1.model_dump(mode="json")
            if tc == MISSING_FIELD_CASE and trial_no == 1:
                del v1_dict["stop_reason"]  # 필수 필드 누락
            trials.append(v1_dict)

    return {
        "bundle_id": _bundle_id("scenario_broken"),
        "created_at": datetime(2026, 8, 16, 9, 25, 0, tzinfo=KST).isoformat(),
        "suite": _suite().model_dump(mode="json"),
        "baseline": _v0().model_dump(mode="json"),
        "candidate": _v1().model_dump(mode="json"),
        "change_note": "계약 위반 스트레스 테스트용 — 실제 실행 기록 아님",
        "trials": trials,
        "traces": None,
    }


SCENARIOS = {
    "scenario_a": build_scenario_a,
    "scenario_clean": build_scenario_clean,
    "scenario_c": build_scenario_c,
    "scenario_b": build_scenario_b,
    "scenario_safety": build_scenario_safety,
}


def generate_all(output_dir: Path = BUNDLE_DIR) -> list[Path]:
    """6종 픽스처를 전부 생성해 output_dir에 쓴다. 반환값은 쓴 파일 경로 목록."""
    written: list[Path] = []
    for name, builder in SCENARIOS.items():
        bundle = builder()
        written.append(_write(bundle, name, output_dir))
    written.append(_write(build_scenario_broken(), "scenario_broken", output_dir))
    return written


if __name__ == "__main__":
    paths = generate_all()
    for p in paths:
        print(f"wrote {p.relative_to(Path(__file__).resolve().parents[1])}")
