"""Policy Agent가 자기 실행을 기록할 때 쓰는 어휘.

이 에이전트는 **자기 실행 로그만 남긴다.** 그 로그를 누가 어떤 형식으로
읽어가는지는 알지 못하고, 알 필요도 없다.

- 이 모듈은 `core/`(Agent Upgrade Auditor)를 import하지 않는다.
- 로그를 Auditor의 계약(`core.schemas`)으로 옮기는 일은 `core/ingest/`가 한다.
  거기가 스키마를 소유한 쪽이다.

값 자체는 발주·환불 에이전트가 원래 남기던 것이다 — 어느 단계에서
무슨 이유로 끝났는지, 토큰과 지연은 얼마였는지. 표준 관측 항목이다.
"""

from __future__ import annotations

from enum import Enum


class StopReason(str, Enum):
    """실행이 끝난 이유."""

    OK = "OK"
    SQL_FAILURE = "SQL_FAILURE"
    MAX_RETRY = "MAX_RETRY"
    MAX_REFLECTION = "MAX_REFLECTION"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    TOOL_SCHEMA_ERROR = "TOOL_SCHEMA_ERROR"
    TIMEOUT = "TIMEOUT"
    PROVIDER_ERROR = "PROVIDER_ERROR"


class NodeRole(str, Enum):
    """실행 그래프의 단계 이름."""

    CLASSIFY = "CLASSIFY"
    PLAN = "PLAN"
    RETRIEVE_SCHEMA = "RETRIEVE_SCHEMA"
    GENERATE_QUERY = "GENERATE_QUERY"
    VALIDATE_QUERY = "VALIDATE_QUERY"
    EXECUTE_TOOL = "EXECUTE_TOOL"
    REPAIR_QUERY = "REPAIR_QUERY"
    CHECK_EVIDENCE = "CHECK_EVIDENCE"
    SELECT_POLICY = "SELECT_POLICY"
    DECIDE = "DECIDE"
    VERIFY_REASONING = "VERIFY_REASONING"
    GENERATE_RESPONSE = "GENERATE_RESPONSE"


class StepType(str, Enum):
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    CODE = "code"


class StepOutcome(str, Enum):
    OK = "ok"
    FAIL = "fail"
    SKIP = "skip"


#: 한 단계 기록이 갖는 키. `core/ingest/`가 이 목록을 보고 매핑한다.
STEP_FIELDS = (
    "testcase_id",
    "agent_label",
    "run_id",
    "trial",
    "step_index",
    "node_role",
    "type",
    "outcome",
    "tool_name",
    "arguments_valid",
    "error_type",
    "iteration",
    "input_tokens",
    "output_tokens",
    "latency_ms",
)
