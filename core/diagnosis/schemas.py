"""LLM 출력 스키마 — P5-3 숫자 방어의 1차 방어선.

★ 여기에는 수치 필드가 하나도 없다. 의도적이다.
LLM이 숫자를 만들 자리를 아예 없애면 "AI 설명과 계산 결과가 충돌"하는 상황이 구조적으로
불가능해진다. LLM은 finding_id로 기존 Finding을 가리키기만 하고, 숫자는 전부 L2/L3가
계산한 값을 렌더러가 붙인다.

2차 방어선은 guard.py(설명문 안에 숫자가 섞여 들어오는 경우)가 맡는다.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FindingCluster(BaseModel):
    """비슷한 원인의 Finding 묶음 1개."""

    model_config = ConfigDict(extra="forbid")

    cluster_id: str = Field(..., description='예: "C1"')
    title: str = Field(..., description="이 묶음을 한 줄로 설명하는 제목 (숫자 금지)")
    finding_ids: list[str] = Field(..., min_length=1, description="묶인 Finding의 finding_id 목록")


class ClusterResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clusters: list[FindingCluster] = Field(default_factory=list)


class FindingExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    rank: int = Field(..., ge=1, description="먼저 조사할 순서. 수치가 아니라 우선순위 인덱스다.")
    explanation: str = Field(..., description="사람이 읽는 설명 (숫자 금지 — guard.py가 검사한다)")


class ExplainResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    explanations: list[FindingExplanation] = Field(default_factory=list)
