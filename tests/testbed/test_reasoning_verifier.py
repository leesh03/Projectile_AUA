"""Reasoning Verifier 단위 테스트.

통합 기획서 §7.1의 Verifier stop rule 검증에 해당한다.
LLM과 Policy Reasoner는 대역으로 주입하므로 API 키 없이 실행된다.

reflection 0/1/2 비교가 프로젝트 전체의 독립변수이므로 횟수별 동작을 각각 고정한다.
"""

import json

import pytest

from agents.policy_agent.scaffolds._state_stub import new_state
from agents.policy_agent.scaffolds.config import with_overrides
from agents.policy_agent.scaffolds.llm import ScriptedLLM
from agents.policy_agent.scaffolds.reasoning_verifier import (
    REASONING_FAILED,
    build_verify_prompt,
    parse_verifier_output,
    verify_loop,
    verify_once,
)

PASS_JSON = json.dumps({"status": "PASS", "issues": []}, ensure_ascii=False)
FAIL_JSON = json.dumps(
    {"status": "FAIL", "issues": ["배송 완료일 기준 14일 조항을 적용하지 않았다"]},
    ensure_ascii=False,
)


class ScriptedReasoner:
    """Policy Reasoner 대역. 재추론 때마다 판정 근거를 바꾼다."""

    def __init__(self, reasons=("재추론 근거",)):
        self._reasons = list(reasons)
        self.calls = 0
        self.seen_issues = []

    def __call__(self, state):
        self.seen_issues.append(list(state.get("verifier_issues") or []))
        state["policy_reason"] = self._reasons[min(self.calls, len(self._reasons) - 1)]
        self.calls += 1
        return state


@pytest.fixture
def decided_state():
    """정책 판정까지 끝나 검토를 기다리는 상태."""
    return new_state(
        user_query="A-10293 주문 환불 되나요?",
        policy_context="§3 배송 완료 후 14일 이내 환불 가능",
        policy_decision="APPROVED",
        applied_policy_clauses=["§3"],
        policy_reason="배송 완료 후 5일이 지났으므로 환불 가능하다",
        sql_result=[{"order_id": "A-10293", "delivered_at": "2026-08-13"}],
    )


# --- 출력 파싱: PASS/FAIL 판정과 파싱 실패를 구분해야 한다 ---


def test_parses_plain_json():
    assert parse_verifier_output(PASS_JSON) == ("PASS", [], None)


def test_parses_json_wrapped_in_text():
    """LLM이 코드펜스나 설명을 덧붙이는 경우가 흔하다."""
    status, issues, error = parse_verifier_output(f"검토 결과입니다.\n```json\n{FAIL_JSON}\n```")

    assert status == "FAIL"
    assert issues == ["배송 완료일 기준 14일 조항을 적용하지 않았다"]
    assert error is None


def test_fail_without_issues_gets_placeholder():
    """사유가 없으면 재추론이 무엇을 고칠지 알 수 없으므로 빈 목록을 두지 않는다."""
    _, issues, _ = parse_verifier_output('{"status": "FAIL", "issues": []}')

    assert len(issues) == 1


def test_unparsable_output_fails_closed():
    """읽지 못한 응답을 PASS로 넘기면 검증되지 않은 판정이 통과한다."""
    status, issues, error = parse_verifier_output("음... 잘 모르겠습니다")

    assert status == "FAIL"
    assert error == "VERIFIER_PARSE_ERROR"
    assert "VERIFIER_PARSE_ERROR" in issues[0]


def test_bare_pass_text_is_rejected():
    """맨 PASS 한 단어도 이제는 통과시키지 않는다.

    예전엔 관대하게 받았는데, 같은 폴백이 BYPASS·compass·"NOT PASS"까지
    통과시켰다. 검증기가 뚫리는 쪽이 엄격해서 놓치는 쪽보다 위험하다.
    """
    status, _, error = parse_verifier_output("PASS")
    assert status == "FAIL"
    assert error == "VERIFIER_PARSE_ERROR"


# --- verify_once: LLM 호출 1회, 재추론 없음 (연동 계약 §7) ---


def test_verify_once_calls_llm_exactly_once(decided_state):
    """2회 이상이면 Core graph가 VerifierContractError로 중단시킨다."""
    llm = ScriptedLLM([FAIL_JSON, PASS_JSON])

    verify_once(decided_state, llm)

    assert llm.call_count == 1
    assert decided_state["verifier_status"] == "FAIL"
    assert decided_state["verifier_issues"]


def test_verify_once_returns_contract_fields(decided_state):
    result = verify_once(decided_state, ScriptedLLM([PASS_JSON]))

    assert result["verifier_status"] == "PASS"
    assert result["verifier_issues"] == []


def test_verify_once_does_not_reason_again(decided_state):
    """재추론은 호출자의 몫이다. 판정은 그대로 남아야 한다."""
    original = decided_state["policy_reason"]

    verify_once(decided_state, ScriptedLLM([FAIL_JSON]))

    assert decided_state["policy_reason"] == original
    assert decided_state["policy_decision"] == "APPROVED"
    assert decided_state["reflection_count"] == 0


# --- 역할 경계: DB 재조회·SQL 생성 금지 (v2 기획서 §25) ---


def test_prompt_carries_decision_and_facts(decided_state):
    prompt = build_verify_prompt(decided_state)

    assert "APPROVED" in prompt
    assert "§3" in prompt
    assert "배송 완료 후 5일이 지났으므로 환불 가능하다" in prompt
    assert "A-10293" in prompt  # 이미 조회된 사실. 재조회가 아니라 근거 대조용


def test_prompt_forbids_requerying(decided_state):
    assert "SQL" in build_verify_prompt(decided_state)


def test_verify_once_leaves_sql_fields_untouched(decided_state):
    verify_once(decided_state, ScriptedLLM([FAIL_JSON]))

    assert decided_state["sql"] == ""
    assert decided_state["sql_history"] == []
    assert decided_state["sql_retry_count"] == 0


# --- reflection 0/1/2 ---


def test_verifier_disabled_skips_verification(decided_state):
    """판정을 그대로 신뢰한다. 실패가 아니므로 stop_reason을 두지 않는다."""
    llm = ScriptedLLM([FAIL_JSON])
    reasoner = ScriptedReasoner()

    verify_loop(decided_state, with_overrides(use_reasoning_verifier=False), llm, reasoner)

    assert llm.call_count == 0
    assert reasoner.calls == 0
    assert decided_state["stop_reason"] is None


def test_zero_reflections_verifies_once_without_retry(decided_state):
    """reflection 0은 검토만 하고 재추론하지 않는다. 1·2와의 비교 기준."""
    llm = ScriptedLLM([FAIL_JSON, PASS_JSON])
    reasoner = ScriptedReasoner()

    verify_loop(decided_state, with_overrides(max_reflections=0), llm, reasoner)

    assert llm.call_count == 1
    assert reasoner.calls == 0
    assert decided_state["stop_reason"] == "MAX_REFLECTION"


def test_pass_on_first_check_stops_immediately(decided_state):
    llm = ScriptedLLM([PASS_JSON])
    reasoner = ScriptedReasoner()

    verify_loop(decided_state, with_overrides(max_reflections=2), llm, reasoner)

    assert llm.call_count == 1
    assert reasoner.calls == 0
    assert decided_state["reflection_count"] == 0
    assert decided_state["stop_reason"] is None


@pytest.mark.parametrize("reflections", [1, 2])
def test_recovers_after_reflection(decided_state, reflections):
    """FAIL 한 번 뒤 재추론으로 회복하면 한도가 남아도 더 돌지 않는다."""
    llm = ScriptedLLM([FAIL_JSON, PASS_JSON])
    reasoner = ScriptedReasoner()

    verify_loop(decided_state, with_overrides(max_reflections=reflections), llm, reasoner)

    assert decided_state["verifier_status"] == "PASS"
    assert decided_state["stop_reason"] is None
    assert reasoner.calls == 1
    assert decided_state["reflection_count"] == 1


@pytest.mark.parametrize("reflections", [0, 1, 2])
def test_exhausted_reflections_stop_with_max_reflection(decided_state, reflections):
    """끝까지 FAIL이면 조용히 끝내지 않고 MAX_REFLECTION을 남긴다(규칙 2)."""
    llm = ScriptedLLM([FAIL_JSON])
    reasoner = ScriptedReasoner()

    verify_loop(decided_state, with_overrides(max_reflections=reflections), llm, reasoner)

    assert decided_state["stop_reason"] == "MAX_REFLECTION"
    assert decided_state["reflection_count"] == reflections
    assert reasoner.calls == reflections
    assert llm.call_count == reflections + 1


def test_reflection_feeds_issues_back_to_reasoner(decided_state):
    """재추론이 무엇을 고쳐야 하는지 받지 못하면 반복해도 같은 답이 나온다."""
    reasoner = ScriptedReasoner()

    verify_loop(
        decided_state, with_overrides(max_reflections=1), ScriptedLLM([FAIL_JSON]), reasoner
    )

    assert reasoner.seen_issues[0] == ["배송 완료일 기준 14일 조항을 적용하지 않았다"]


# --- 무한 루프 방지 ---


def test_global_step_limit_stops_loop(decided_state):
    """개별 한도가 남아 있어도 전역 상한에 걸리면 종료한다."""
    decided_state["total_step_count"] = 20
    llm = ScriptedLLM([FAIL_JSON])

    config = with_overrides(max_reflections=2, max_total_steps=20)
    verify_loop(decided_state, config, llm, ScriptedReasoner())

    assert decided_state["stop_reason"] == "MAX_REFLECTION"
    assert llm.call_count == 0


@pytest.mark.parametrize("reflections", [0, 1, 2, 5])
def test_loop_always_terminates(decided_state, reflections):
    llm = ScriptedLLM(["읽을 수 없는 응답"])
    reasoner = ScriptedReasoner()

    verify_loop(decided_state, with_overrides(max_reflections=reflections), llm, reasoner)

    assert decided_state["stop_reason"] == "MAX_REFLECTION"
    assert llm.call_count == reflections + 1
    assert reasoner.calls <= reflections


# --- Trace 기록 (CONTRACT.md §2) ---


def test_trace_records_verification_and_reasoning(decided_state):
    llm = ScriptedLLM([FAIL_JSON, PASS_JSON])

    verify_loop(decided_state, with_overrides(max_reflections=1), llm, ScriptedReasoner())

    roles = [step["node_role"] for step in decided_state["trace"]]
    assert roles == ["VERIFY_REASONING", "DECIDE", "VERIFY_REASONING"]


def test_trace_iteration_counts_reflections(decided_state):
    """첫 검증이 0, 재추론 뒤 검증이 1..N. 회복률 계산의 기준이다."""
    llm = ScriptedLLM([FAIL_JSON])

    verify_loop(decided_state, with_overrides(max_reflections=2), llm, ScriptedReasoner())

    iterations = [
        s["iteration"] for s in decided_state["trace"] if s["node_role"] == "VERIFY_REASONING"
    ]
    assert iterations == [0, 1, 2]


def test_trace_marks_rejection_and_parse_error(decided_state):
    """판정 FAIL과 출력 파싱 실패를 error_type으로 구분한다(R-04)."""
    verify_once(decided_state, ScriptedLLM([FAIL_JSON]))
    verify_once(decided_state, ScriptedLLM(["읽을 수 없는 응답"]))

    steps = decided_state["trace"]
    assert steps[0]["outcome"] == "fail"
    assert steps[0]["error_type"] == "VERIFIER_REJECTED"
    assert steps[1]["error_type"] == "VERIFIER_PARSE_ERROR"


def test_trace_carries_tokens_and_pairing_keys(decided_state):
    """어댑터가 trace[-1]에서 토큰을 읽어 비용을 계상한다(연동 계약 §7)."""
    verify_once(decided_state, ScriptedLLM([PASS_JSON]))

    step = decided_state["trace"][-1]
    assert step["input_tokens"] > 0
    assert step["output_tokens"] > 0
    assert step["testcase_id"] == "tc_stub"
    assert step["agent_label"] == "V0"


def test_trace_step_index_is_sequential(decided_state):
    llm = ScriptedLLM([FAIL_JSON, FAIL_JSON, PASS_JSON])

    verify_loop(decided_state, with_overrides(max_reflections=2), llm, ScriptedReasoner())

    indexes = [step["step_index"] for step in decided_state["trace"]]
    assert indexes == list(range(len(indexes)))
    assert decided_state["total_step_count"] == len(indexes)


class TestReasoningFailure:
    """재추론이 실패했을 때. Auditor의 O-01이 개입 횟수를 세므로 정직해야 한다."""

    @staticmethod
    def _fail_state():
        state = new_state()
        state["policy_decision"] = "APPROVE"
        return state

    def test_예외가_나면_fail로_남는다(self):
        state = self._fail_state()

        def broken_reason_fn(_state):
            raise RuntimeError("reasoner 죽음")

        config = with_overrides(use_reasoning_verifier=True, max_reflections=2)
        verify_loop(state, config, ScriptedLLM(['{"status":"FAIL","issues":["조항 오적용"]}']), broken_reason_fn)

        decide_steps = [s for s in state["trace"] if s["node_role"] == "DECIDE"]
        assert decide_steps[-1]["outcome"] == "fail"
        assert decide_steps[-1]["error_type"] == REASONING_FAILED
        assert state["stop_reason"] == "MAX_REFLECTION"

    def test_판정이_비면_fail로_남는다(self):
        state = self._fail_state()

        def clearing_reason_fn(s):
            s["policy_decision"] = None  # 판정을 못 냈다
            return s

        config = with_overrides(use_reasoning_verifier=True, max_reflections=2)
        verify_loop(state, config, ScriptedLLM(['{"status":"FAIL","issues":["조항 오적용"]}']), clearing_reason_fn)

        decide_steps = [s for s in state["trace"] if s["node_role"] == "DECIDE"]
        assert decide_steps[-1]["outcome"] == "fail"

    def test_정상이면_ok로_남는다(self):
        state = self._fail_state()
        calls = []

        def good_reason_fn(s):
            calls.append(1)
            s["policy_decision"] = "REJECT"
            return s

        config = with_overrides(use_reasoning_verifier=True, max_reflections=1)
        verify_loop(state, config, ScriptedLLM(['{"status":"FAIL","issues":["조항 오적용"]}']), good_reason_fn)

        decide_steps = [s for s in state["trace"] if s["node_role"] == "DECIDE"]
        assert len(calls) == 1
        assert decide_steps[-1]["outcome"] == "ok"
        assert decide_steps[-1]["error_type"] is None


class TestVerifyPromptCoverage:
    """기획서 §6.2가 요구하는 검사 항목이 프롬프트에 다 있는지 고정한다."""

    def test_기획서_검사항목_4종이_모두_있다(self):
        prompt = build_verify_prompt(new_state())
        assert "우선순위" in prompt          # 조항 간 우선순위
        assert "예외 조항" in prompt          # 정책 누락·예외
        assert "논리적으로" in prompt         # decision/evidence 모순
        assert "지어냈는가" in prompt         # evidence 환각

    def test_조항ID를_함께_적으라고_요구한다(self):
        # 조항 ID가 없으면 Auditor가 실행 간 같은 문제를 대조하지 못한다
        assert "POL-" in build_verify_prompt(new_state())

    def test_DB_재조회_금지가_명시된다(self):
        prompt = build_verify_prompt(new_state())
        assert "다시 조회" in prompt and "SQL을 만들지" in prompt


class TestParserCannotBeBypassed:
    """JSON이 깨졌을 때 PASS로 뚫리면 안 된다.

    예전 폴백은 부분 문자열 검사라 PASS가 들어간 아무 단어에나 통과했다.
    검증기가 뚫리면 Auditor의 O-01이 "Verifier가 일하고 있다"고 오판한다.
    """

    @pytest.mark.parametrize("text", [
        "BYPASS", "compass", "NOT PASS", "PASS 아님",
        "판정: PASS라고 보기 어렵습니다", "", "   ",
        '{"status": "MAYBE"}', "```json\n{broken",
    ])
    def test_JSON이_아니면_FAIL(self, text):
        status, issues, error = parse_verifier_output(text)
        assert status == "FAIL"
        assert error == "VERIFIER_PARSE_ERROR"
        assert issues  # 재추론이 뭘 고쳐야 할지 알 수 있어야 한다

    def test_정상_JSON은_그대로_PASS(self):
        assert parse_verifier_output(PASS_JSON) == ("PASS", [], None)

    def test_코드펜스로_감싼_JSON도_읽는다(self):
        wrapped = f"```json\n{PASS_JSON}\n```"
        assert parse_verifier_output(wrapped)[0] == "PASS"
