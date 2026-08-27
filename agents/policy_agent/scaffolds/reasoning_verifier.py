"""Reasoning Verifier.

정책 판정과 그 근거를 다시 읽어 논리 일관성·조항 적용을 점검한다.
FAIL이면 발견한 문제를 돌려주고, 재추론은 호출자(graph 또는 verify_loop)가 맡는다.

DB 재조회와 새 SQL 생성은 하지 않는다(v2 기획서 §25). 이 경계를 넘으면
성능 향상이 Verifier 덕인지 재조회 덕인지 구분되지 않아 Scaffold Utility 측정이 무의미해진다.

verify_once와 verify_loop 두 가지를 제공한다.
graph가 반복을 제어하면 verify_once를, 반복까지 맡기려면 verify_loop을 사용한다.
"""

import json
import re
from typing import Any, Protocol

from core.schemas.enums import NodeRole, StepOutcome, StepType, StopReason

from .llm import LLMClient
from .trace import append_step, timed

# 어댑터(nodes/scaffold_adapters.py)가 정규화 없이 그대로 읽는 값. 다른 문자열을 쓰면 안 된다.
PASS = "PASS"
FAIL = "FAIL"

# 판정 자체의 FAIL과 출력을 못 읽은 FAIL을 error_type으로 구분한다.
# 둘을 섞으면 Auditor가 Verifier 실패 유형을 분류하지 못한다(R-04).
PARSE_ERROR = "VERIFIER_PARSE_ERROR"
REJECTED = "VERIFIER_REJECTED"


class ReasonFn(Protocol):
    """Policy Reasoner 재호출용. 준원의 노드를 인자로 주입받는다."""

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]: ...


VERIFY_PROMPT = """\
아래 환불 정책 판정을 검토하라. 너는 판정을 새로 내리지 않고 검토만 한다.

[정책]
{policy}

[고객 질문]
{question}

[조회된 사실]
{facts}

[판정]
{decision}

[적용한 조항]
{clauses}

[판정 근거]
{reason}

다음 다섯 가지를 확인하라.
1. 적용한 조항이 이 상황에 실제로 해당하는가
2. 조항 간 우선순위가 맞는가 (다른 조항을 무효화해야 하는데 그대로 적용했는가)
3. 판정과 근거가 논리적으로 이어지는가
4. 놓친 예외 조항이 있는가
5. 근거가 위 [조회된 사실]에 실제로 있는 내용인가 (없는 사실을 지어냈는가)

DB를 다시 조회하거나 SQL을 만들지 마라. 위에 주어진 정보만으로 판단하라.
문제가 없으면 status는 PASS, 하나라도 있으면 FAIL이다.

문제를 적을 때는 관련 조항 ID(예: POL-10.03)를 함께 쓴다.
조항 ID가 있어야 Auditor가 같은 문제를 실행 간에 대조할 수 있다.

아래 JSON 형식으로만 답하라.
{{"status": "PASS 또는 FAIL", "issues": ["POL-10.03: 반품 기한이 지나지 않았는데 만료 조항을 적용했다"]}}"""


def build_verify_prompt(state: dict[str, Any]) -> str:
    """검토 요청 프롬프트를 만든다.

    policy_facts는 이미 조회가 끝난 값이다. 이것을 넣는 것은 재조회가 아니라,
    근거가 실제 사실에 기반하는지(4번 항목) 확인하기 위한 것이다.
    """
    clauses = state.get("applied_policy_clauses") or []
    facts = state.get("policy_facts")
    if facts is None:
        facts = state.get("sql_result") or []

    return VERIFY_PROMPT.format(
        policy=state.get("policy_context") or "(제공되지 않음)",
        question=state.get("user_query") or "",
        facts=json.dumps(facts, ensure_ascii=False, default=str),
        decision=state.get("policy_decision") or "(없음)",
        clauses="\n".join(f"- {c}" for c in clauses) if clauses else "(없음)",
        reason=state.get("policy_reason") or "(없음)",
    )


def parse_verifier_output(text: str) -> tuple[str, list[str], str | None]:
    """LLM 응답에서 (status, issues, error_type)을 뽑는다.

    error_type이 None이 아니면 판정이 아니라 파싱이 실패한 것이다.
    LLM이 설명이나 코드펜스를 덧붙이는 경우가 흔해 JSON 부분만 잘라서 읽는다.
    읽지 못하면 PASS로 넘기지 않고 FAIL로 막는다. 검증되지 않은 판정을 통과시키는 쪽이
    더 위험하기 때문이다.
    """
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            status = str(data.get("status", "")).strip().upper()
            if status in (PASS, FAIL):
                raw_issues = data.get("issues") or []
                if not isinstance(raw_issues, list):
                    raw_issues = [raw_issues]
                issues = [str(i).strip() for i in raw_issues if str(i).strip()]
                # FAIL인데 이유가 비면 재추론이 뭘 고쳐야 할지 알 수 없다.
                if status == FAIL and not issues:
                    issues = ["검증기가 FAIL로 판정했으나 사유를 제시하지 않았다"]
                return status, ([] if status == PASS else issues), None

    # JSON을 못 읽으면 무조건 FAIL이다.
    # 부분 문자열 폴백은 검증되지 않은 판정을 통과시킬 수 있다.
    return FAIL, [f"{PARSE_ERROR}: {text.strip()[:200]}"], PARSE_ERROR


def verify_once(state: dict[str, Any], llm: LLMClient) -> dict[str, Any]:
    """판정을 1회 검토한다. 재추론은 하지 않는다.

    LLM 호출은 정확히 1회다. 2회 이상이면 Core graph가 계약 위반으로 중단시킨다
    (nodes/graph.py의 VerifierContractError).
    """
    prompt = build_verify_prompt(state)

    with timed() as t:
        result = llm(prompt)

    status, issues, parse_error = parse_verifier_output(result.text)

    state["verifier_status"] = status
    state["verifier_issues"] = issues

    append_step(
        state,
        node_role=NodeRole.VERIFY_REASONING,
        step_type=StepType.LLM_CALL,
        outcome=StepOutcome.OK if status == PASS else StepOutcome.FAIL,
        # graph의 반복 번호와 맞춘다. 첫 검증이 0, 재추론 뒤 검증이 1..N이다.
        iteration=state.get("reflection_count", 0),
        error_type=None if status == PASS else (parse_error or REJECTED),
        latency_ms=t["ms"],
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )
    return state


REASONING_FAILED = "REASONING_FAILED"


def _record_reasoning(state: dict[str, Any], latency_ms: int, *, ok: bool = True) -> None:
    """재추론 1회를 trace에 남긴다.

    최초 판정은 Core가 기록하므로 여기서는 Verifier가 유발한 재추론만 남긴다.
    재추론이 실패해도 ok로 남기면 Auditor의 O-01이 개입 횟수를 잘못 센다.
    """
    append_step(
        state,
        node_role=NodeRole.DECIDE,
        step_type=StepType.LLM_CALL,
        outcome=StepOutcome.OK if ok else StepOutcome.FAIL,
        iteration=state.get("reflection_count", 0),
        error_type=None if ok else REASONING_FAILED,
        latency_ms=latency_ms,
    )


def verify_loop(
    state: dict[str, Any],
    config: dict[str, Any],
    llm: LLMClient,
    reason_fn: ReasonFn,
) -> dict[str, Any]:
    """설정 횟수만큼 검토와 재추론을 반복한다.

    반복 구조를 nodes/graph.py의 _run_reasoning_verifier와 일부러 똑같이 맞췄다.
    두 경로가 같은 config에서 다른 trace를 만들면 0/1/2 비교가 성립하지 않는다.
    같은 이유로 sql_repair의 stop_on_repeated_error에 해당하는 조기 중단은 넣지 않았다.
    Core가 Verifier에는 그 규칙을 적용하지 않기 때문이다.

    종료 조건:
      - PASS: stop_reason을 설정하지 않고 반환(후속 노드가 계속 진행)
      - verifier 미사용: 검토 없이 그대로 통과. stop_reason 없음
      - 한도까지 FAIL: MAX_REFLECTION
    """
    # verifier가 꺼져 있으면 판정을 그대로 신뢰한다. 실패가 아니므로 stop_reason을 두지 않는다.
    if not config.get("use_reasoning_verifier"):
        return state

    max_reflections = config.get("max_reflections", 0)
    max_total_steps = config.get("max_total_steps")

    # max_reflections=0이면 검토는 1회 하고 재추론은 하지 않는다.
    for _ in range(max_reflections + 1):
        # 개별 카운터와 별개로 두는 전역 상한. 다른 노드의 단계까지 합산한다.
        if max_total_steps is not None and state.get("total_step_count", 0) >= max_total_steps:
            state["stop_reason"] = StopReason.MAX_REFLECTION.value
            return state

        verify_once(state, llm)

        if state["verifier_status"] == PASS:
            return state

        if state.get("reflection_count", 0) >= max_reflections:
            state["stop_reason"] = StopReason.MAX_REFLECTION.value
            return state

        state["reflection_count"] = state.get("reflection_count", 0) + 1

        with timed() as t:
            try:
                reason_fn(state)
                reasoning_ok = bool(state.get("policy_decision"))
            except Exception:
                reasoning_ok = False
        _record_reasoning(state, t["ms"], ok=reasoning_ok)

        # 재추론이 실패하면 다시 검증해봐야 같은 판정이 나온다.
        if not reasoning_ok:
            state["stop_reason"] = StopReason.MAX_REFLECTION.value
            return state

    state["stop_reason"] = StopReason.MAX_REFLECTION.value
    return state
