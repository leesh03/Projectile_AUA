"""Enum 확정값.

여기 값을 바꾸면 팀 전원의 실행 기록이 동시에 깨진다.
변경은 `contract/*` 브랜치로만 한다. (docs/CONTRACT.md 참조)
"""

from enum import Enum


class StopReason(str, Enum):
    """TrialResult.stop_reason 허용값."""

    OK = "OK"
    SQL_FAILURE = "SQL_FAILURE"
    MAX_RETRY = "MAX_RETRY"
    MAX_REFLECTION = "MAX_REFLECTION"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    TOOL_SCHEMA_ERROR = "TOOL_SCHEMA_ERROR"
    TIMEOUT = "TIMEOUT"
    PROVIDER_ERROR = "PROVIDER_ERROR"


class NodeRole(str, Enum):
    """TraceStep.node_role 고정 목록. 양쪽 버전이 같은 이름을 써야 Trace Diff 정렬이 된다."""

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
    """TraceStep.type."""

    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    CODE = "code"


class StepOutcome(str, Enum):
    """TraceStep.outcome."""

    OK = "ok"
    FAIL = "fail"
    SKIP = "skip"


class FindingType(str, Enum):
    REGRESSION = "REGRESSION"
    IMPROVEMENT = "IMPROVEMENT"
    EFFICIENCY_WARNING = "EFFICIENCY_WARNING"
    OPTIMIZATION_OPPORTUNITY = "OPTIMIZATION_OPPORTUNITY"
    SAFETY_ALERT = "SAFETY_ALERT"
    INCONCLUSIVE = "INCONCLUSIVE"


class Severity(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


class Verdict(str, Enum):
    """UpgradeReport.verdict — 보고서 전체 판정."""

    PASS = "PASS"
    HOLD = "HOLD"
    BLOCK = "BLOCK"


class RevalidationStatus(str, Enum):
    """Candidate 재검증(P7) 판정. Verdict와 달리 INCONCLUSIVE를 허용한다."""

    PASS = "PASS"
    HOLD = "HOLD"
    BLOCK = "BLOCK"
    INCONCLUSIVE = "INCONCLUSIVE"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CandidateStatus(str, Enum):
    """Candidate.status — 재검증 전에는 절대 APPLIED가 될 수 없다 (P6-2 규칙)."""

    PROPOSED = "PROPOSED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
