"""AgentState 임시 stub.

준원의 nodes/state.py가 나오면 이 파일을 지우고 import를 교체한다.
필드 이름은 기획서 §22를 그대로 옮겼다.
"""

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    # testcase_id, agent_label은 기획서 §22에 없지만 CONTRACT.md §2 TraceStep이 필수로 요구한다.
    # 스캐폴드는 자기가 V0인지 V1인지 알 수 없으므로 실행기가 state에 넣어주는 것으로 가정했다.
    testcase_id: str
    agent_label: str
    run_id: str
    trial: int

    request_id: str
    user_query: str

    plan: dict

    schema_context: str
    policy_context: str

    # sql_repair가 읽고 쓰는 범위
    # sql_error_message는 MVP 기획서 §22에 없으나 v2 §20과 통합 기획서 §6.2가 요구한다.
    # 오류 문장 없이는 수정 SQL을 생성할 수 없어 추가했다.
    sql: str
    sql_history: list[str]
    sql_result: list[dict]
    sql_success: bool
    sql_error_type: str | None
    sql_error_message: str | None
    sql_retry_count: int

    evidence_complete: bool

    # reasoning_verifier가 읽는 범위
    policy_decision: str
    applied_policy_clauses: list[str]
    policy_reason: str
    # verify_once가 "근거가 실제 사실에 있는가"를 검사할 때 읽는다.
    policy_facts: dict[str, Any] | None

    # reasoning_verifier가 쓰는 범위
    verifier_status: str
    verifier_issues: list[str]
    reflection_count: int

    final_answer: str
    stop_reason: str | None

    total_step_count: int
    trace: list[dict]


def new_state(**overrides: Any) -> AgentState:
    """테스트용 초기 state. 필요한 값만 덮어쓴다."""
    state: AgentState = {
        "testcase_id": "tc_stub",
        "agent_label": "V0",
        "run_id": "run_stub",
        "trial": 1,
        "request_id": "req_stub",
        "user_query": "",
        # nodes/scaffold_adapters.py가 넘기는 키와 같아야 한다.
        # 빠지면 프롬프트가 "(제공되지 않음)" 경로로만 테스트된다.
        "schema_context": "",
        "policy_context": "",
        "policy_facts": None,
        "sql": "",
        "sql_history": [],
        "sql_result": [],
        "sql_success": False,
        "sql_error_type": None,
        "sql_error_message": None,
        "sql_retry_count": 0,
        "policy_decision": "",
        "applied_policy_clauses": [],
        "policy_reason": "",
        "verifier_status": "",
        "verifier_issues": [],
        "reflection_count": 0,
        "stop_reason": None,
        "total_step_count": 0,
        "trace": [],
    }
    state.update(overrides)  # type: ignore[typeddict-item]
    return state
