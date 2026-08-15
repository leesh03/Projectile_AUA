"""AgentVersion — AuditBundle.baseline / AuditBundle.candidate."""

from pydantic import BaseModel, ConfigDict, Field


class AgentVersion(BaseModel):
    """비교 대상이 되는 Agent 버전 1개의 메타데이터.

    baseline(V0)과 candidate(V1)가 각각 이 형식으로 들어온다.
    수치 비교에는 쓰이지 않는다 — 보고서 상단에 "무엇을 무엇과 비교했는지" 표시하는 용도.
    """

    model_config = ConfigDict(extra="forbid")

    label: str = Field(..., description='보통 "V0" / "V1", 재검증 시 "V2"도 허용')
    agent_id: str
    version: str
    model_id: str
    prompt_version: str
    tool_schema_version: str
    workflow_version: str
    retry_policy: str
    verifier_policy: str
    commit: str | None = None
