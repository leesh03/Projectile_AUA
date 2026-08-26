"""SQL Repair Loop 단위 테스트.

통합 기획서 §7.1의 "고정 오류 객체를 이용한 SQL Repair와 stop rule 단위 테스트"에 해당한다.
LLM과 executor는 대역으로 주입하므로 API 키 없이 실행된다.
"""

import pytest

from agents.policy_agent.scaffolds._state_stub import new_state
from agents.policy_agent.scaffolds.config import with_overrides
from agents.policy_agent.scaffolds.llm import ScriptedLLM
from agents.policy_agent.scaffolds.sql_repair import (
    REPAIR_PARSE_ERROR,
    ExecResult,
    extract_sql,
    repair_loop,
    repair_once,
)

FAIL_TABLE = ExecResult(False, None, "NO_SUCH_TABLE", "no such table: order")
FAIL_COLUMN = ExecResult(False, None, "NO_SUCH_COLUMN", "no such column: id")
SUCCESS = ExecResult(True, [{"order_id": "A-10293"}])

REPAIRED_SQLS = [
    "SELECT * FROM orders",
    "SELECT * FROM orders WHERE order_id = 'A-10293'",
]


class ScriptedExecutor:
    """호출 순서대로 미리 정한 실행 결과를 반환한다."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    def __call__(self, sql):
        result = self._results[min(self.calls, len(self._results) - 1)]
        self.calls += 1
        return result


@pytest.fixture
def failed_state():
    """최초 SQL이 이미 실패한 상태."""
    return new_state(
        user_query="A-10293 주문 환불 되나요?",
        schema_context="orders(order_id, customer_id, delivered_at)",
        sql="SELECT * FROM order WHERE id = 'A-10293'",
        sql_success=False,
        sql_error_type="NO_SUCH_TABLE",
        sql_error_message="no such table: order",
    )


# --- repair_once: 1회 수정만 담당하고 재실행은 하지 않는다 ---


def test_repair_once_replaces_sql_and_keeps_history(failed_state):
    llm = ScriptedLLM(["SELECT * FROM orders"])
    original = failed_state["sql"]

    repair_once(failed_state, llm)

    assert failed_state["sql"] == "SELECT * FROM orders"
    assert failed_state["sql_history"] == [original]
    assert failed_state["sql_retry_count"] == 1
    assert llm.call_count == 1


def test_repair_once_prompt_includes_error_message(failed_state):
    llm = ScriptedLLM(["SELECT 1"])

    repair_once(failed_state, llm)

    prompt = llm.prompts[0]
    assert "no such table: order" in prompt
    assert "A-10293 주문 환불 되나요?" in prompt


def test_repair_once_leaves_execution_untouched(failed_state):
    """재실행은 repair_loop의 몫이므로 성공 여부를 바꾸지 않는다."""
    repair_once(failed_state, ScriptedLLM(["SELECT 1"]))

    assert failed_state["sql_success"] is False


# --- stop rule: 모든 종료가 명시적 stop_reason으로 끝나야 한다 ---


def test_repair_disabled_stops_with_sql_failure(failed_state):
    llm = ScriptedLLM(REPAIRED_SQLS)
    executor = ScriptedExecutor([SUCCESS])

    repair_loop(failed_state, with_overrides(use_sql_repair=False), llm, executor)

    assert failed_state["stop_reason"] == "SQL_FAILURE"
    assert llm.call_count == 0
    assert executor.calls == 0


def test_zero_retries_stops_with_sql_failure(failed_state):
    """retry 0은 repair를 끈 것과 같은 결과여야 비교 기준이 된다."""
    llm = ScriptedLLM(REPAIRED_SQLS)

    repair_loop(failed_state, with_overrides(max_sql_retries=0), llm, ScriptedExecutor([SUCCESS]))

    assert failed_state["stop_reason"] == "SQL_FAILURE"
    assert llm.call_count == 0


def test_exhausted_retries_stops_with_max_retry(failed_state):
    llm = ScriptedLLM(REPAIRED_SQLS)
    executor = ScriptedExecutor([FAIL_COLUMN, FAIL_TABLE])

    repair_loop(failed_state, with_overrides(max_sql_retries=2), llm, executor)

    assert failed_state["stop_reason"] == "MAX_RETRY"
    assert failed_state["sql_retry_count"] == 2
    assert executor.calls == 2


def test_already_successful_state_is_untouched():
    state = new_state(sql_success=True, sql="SELECT 1")
    llm = ScriptedLLM(["SELECT 2"])

    repair_loop(state, with_overrides(), llm, ScriptedExecutor([SUCCESS]))

    assert llm.call_count == 0
    assert state["stop_reason"] is None


# --- 회복 성공 ---


@pytest.mark.parametrize("retries,failures,expected_calls", [(1, [], 1), (2, [FAIL_COLUMN], 2)])
def test_recovers_within_limit(failed_state, retries, failures, expected_calls):
    llm = ScriptedLLM(REPAIRED_SQLS)
    executor = ScriptedExecutor([*failures, SUCCESS])

    repair_loop(failed_state, with_overrides(max_sql_retries=retries), llm, executor)

    assert failed_state["sql_success"] is True
    assert failed_state["stop_reason"] is None
    assert llm.call_count == expected_calls


# --- 동일 오류 반복 감지 (통합 기획서 §6.2) ---


def test_repeated_error_stops_before_exhausting_retries(failed_state):
    """같은 error_type이 다시 나오면 남은 횟수를 사용하지 않는다."""
    llm = ScriptedLLM(REPAIRED_SQLS)
    executor = ScriptedExecutor([FAIL_TABLE, FAIL_TABLE])

    repair_loop(failed_state, with_overrides(max_sql_retries=2), llm, executor)

    assert failed_state["stop_reason"] == "MAX_RETRY"
    assert failed_state["sql_retry_count"] == 1
    assert llm.call_count == 1


def test_repeated_error_detection_can_be_disabled(failed_state):
    """감지를 끄면 횟수를 모두 사용한다. 조기 종료의 효과를 비교하기 위한 조건."""
    llm = ScriptedLLM(REPAIRED_SQLS)
    executor = ScriptedExecutor([FAIL_TABLE, FAIL_TABLE])

    config = with_overrides(max_sql_retries=2, stop_on_repeated_error=False)
    repair_loop(failed_state, config, llm, executor)

    assert failed_state["sql_retry_count"] == 2
    assert llm.call_count == 2


def test_changed_error_continues(failed_state):
    """오류 종류가 바뀌면 진전으로 보고 반복을 이어간다."""
    llm = ScriptedLLM(REPAIRED_SQLS)
    executor = ScriptedExecutor([FAIL_COLUMN, SUCCESS])

    repair_loop(failed_state, with_overrides(max_sql_retries=2), llm, executor)

    assert failed_state["sql_success"] is True
    assert failed_state["sql_retry_count"] == 2


# --- 무한 루프 방지 ---


def test_global_step_limit_stops_loop(failed_state):
    """개별 retry 한도가 남아 있어도 전역 상한에 걸리면 종료한다."""
    failed_state["total_step_count"] = 20
    llm = ScriptedLLM(REPAIRED_SQLS)

    config = with_overrides(max_sql_retries=2, max_total_steps=20)
    repair_loop(failed_state, config, llm, ScriptedExecutor([FAIL_COLUMN]))

    assert failed_state["stop_reason"] == "MAX_RETRY"
    assert llm.call_count == 0


@pytest.mark.parametrize("retries", [0, 1, 2, 5])
def test_loop_always_terminates(failed_state, retries):
    """어떤 설정에서도 종료하며 LLM 호출이 한도를 넘지 않는다."""
    llm = ScriptedLLM(REPAIRED_SQLS)
    config = with_overrides(max_sql_retries=retries, stop_on_repeated_error=False)

    repair_loop(failed_state, config, llm, ScriptedExecutor([FAIL_COLUMN]))

    assert failed_state["stop_reason"] in ("SQL_FAILURE", "MAX_RETRY")
    assert llm.call_count <= retries


# --- Trace 기록 (CONTRACT.md §2) ---


def test_trace_records_repair_and_execution(failed_state):
    llm = ScriptedLLM(REPAIRED_SQLS)

    repair_loop(failed_state, with_overrides(max_sql_retries=1), llm, ScriptedExecutor([SUCCESS]))

    roles = [step["node_role"] for step in failed_state["trace"]]
    assert roles == ["REPAIR_QUERY", "EXECUTE_TOOL"]


def test_trace_step_index_is_sequential(failed_state):
    llm = ScriptedLLM(REPAIRED_SQLS)
    executor = ScriptedExecutor([FAIL_COLUMN, SUCCESS])

    repair_loop(failed_state, with_overrides(max_sql_retries=2), llm, executor)

    indexes = [step["step_index"] for step in failed_state["trace"]]
    assert indexes == list(range(len(indexes)))
    assert failed_state["total_step_count"] == len(indexes)


def test_trace_carries_iteration_and_pairing_keys(failed_state):
    """iteration은 회복률 계산에, testcase_id·agent_label은 V0/V1 페어링에 쓰인다."""
    llm = ScriptedLLM(REPAIRED_SQLS)

    repair_loop(failed_state, with_overrides(max_sql_retries=1), llm, ScriptedExecutor([SUCCESS]))

    repair_step = failed_state["trace"][0]
    assert repair_step["iteration"] == 1
    assert repair_step["testcase_id"] == "tc_stub"
    assert repair_step["agent_label"] == "V0"
    assert repair_step["input_tokens"] > 0


def test_failed_execution_is_recorded_as_fail(failed_state):
    llm = ScriptedLLM(REPAIRED_SQLS)
    executor = ScriptedExecutor([FAIL_COLUMN, FAIL_COLUMN])

    config = with_overrides(max_sql_retries=1)
    repair_loop(failed_state, config, llm, executor)

    execute_steps = [s for s in failed_state["trace"] if s["node_role"] == "EXECUTE_TOOL"]
    assert execute_steps[-1]["outcome"] == "fail"
    assert execute_steps[-1]["error_type"] == "NO_SUCH_COLUMN"


# --- 설정 오타 방어 ---


def test_unknown_config_key_is_rejected():
    with pytest.raises(KeyError):
        with_overrides(max_sql_retry=2)


class TestExtractSQL:
    """LLM 응답 정제. 실제 모델은 코드펜스나 설명을 붙여서 답한다."""

    def test_코드펜스를_걷어낸다(self):
        text = "```sql\nSELECT * FROM orders;\n```"
        assert extract_sql(text) == "SELECT * FROM orders"

    def test_언어표시_없는_펜스도_처리한다(self):
        assert extract_sql("```\nSELECT 1\n```") == "SELECT 1"

    def test_앞에_붙은_설명을_걷어낸다(self):
        text = "수정한 SQL은 다음과 같습니다:\nSELECT * FROM orders;"
        assert extract_sql(text) == "SELECT * FROM orders"

    def test_뒤에_붙은_설명을_걷어낸다(self):
        text = "SELECT * FROM orders; 이제 테이블명이 맞습니다."
        assert extract_sql(text) == "SELECT * FROM orders"

    def test_WITH절도_인식한다(self):
        assert extract_sql("WITH t AS (SELECT 1) SELECT * FROM t").startswith("WITH")

    @pytest.mark.parametrize("text", ["", "   ", "죄송합니다. 수정할 수 없습니다."])
    def test_SQL이_없으면_빈_문자열(self, text):
        assert extract_sql(text) == ""


class TestRepairParseFailure:
    """수정 SQL을 못 만들었을 때. Auditor가 실패로 셀 수 있어야 한다."""

    def test_이전_SQL을_유지한다(self):
        state = new_state()
        state["sql"] = "SELECT * FROM order"
        state["sql_error_type"] = "NO_SUCH_TABLE"
        repair_once(state, ScriptedLLM(["죄송합니다. 수정할 수 없습니다."]))
        # 빈 문자열을 넣으면 어댑터 계약(비어있지 않은 문자열)이 깨진다
        assert state["sql"] == "SELECT * FROM order"
        assert state["sql_repair_parse_error"] is True

    def test_trace에_fail로_남는다(self):
        state = new_state()
        state["sql"] = "SELECT * FROM order"
        state["sql_error_type"] = "NO_SUCH_TABLE"
        repair_once(state, ScriptedLLM(["   "]))
        step = state["trace"][-1]
        assert step["outcome"] == "fail"
        assert step["error_type"] == REPAIR_PARSE_ERROR

    def test_성공하면_ok로_남는다(self):
        state = new_state()
        state["sql"] = "SELECT * FROM order"
        state["sql_error_type"] = "NO_SUCH_TABLE"
        repair_once(state, ScriptedLLM(["```sql\nSELECT * FROM orders\n```"]))
        assert state["sql"] == "SELECT * FROM orders"
        assert state["sql_repair_parse_error"] is False
        assert state["trace"][-1]["outcome"] == "ok"

    def test_루프는_재실행하지_않고_중단한다(self):
        state = new_state()
        state["sql"] = "SELECT * FROM order"
        state["sql_success"] = False
        state["sql_error_type"] = "NO_SUCH_TABLE"
        executor = ScriptedExecutor([SUCCESS])
        config = with_overrides(use_sql_repair=True, max_sql_retries=2)
        repair_loop(state, config, ScriptedLLM(["설명만 있고 SQL이 없음"]), executor)
        # 같은 SQL을 다시 실행해봐야 같은 오류만 나온다
        assert executor.calls == 0
        assert state["stop_reason"] == "MAX_RETRY"
