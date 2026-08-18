"""Deterministic, evidence-grounded response formatting."""

from __future__ import annotations

from typing import ClassVar

from agents.policy_agent.nodes.state import PolicyAgentState


class ResponseWriter:
    DECISION_LABELS: ClassVar[dict[str, str]] = {
        "APPROVE": "요청을 승인할 수 있습니다.",
        "REJECT": "요청을 승인하기 어렵습니다.",
        "NEED_MORE_INFO": "판단을 위해 추가 정보가 필요합니다.",
        "NOT_APPLICABLE": "현재 요청은 새 환불 심사 대상이 아닙니다.",
    }

    def write(self, state: PolicyAgentState) -> str:
        if state.decision not in self.DECISION_LABELS:
            raise ValueError("a valid policy decision is required before writing a response")
        parts = [self.DECISION_LABELS[state.decision]]
        if state.rationale:
            parts.append(f"근거: {state.rationale}")
        if state.policy_clauses:
            parts.append(f"적용 정책: {', '.join(state.policy_clauses)}")
        response = "\n".join(parts)
        state.response = response
        return response

    def write_insufficient_evidence(self, state: PolicyAgentState) -> str:
        if state.missing_evidence:
            details = ", ".join(state.missing_evidence)
            response = f"판단에 필요한 정보가 부족합니다. 추가 확인 항목: {details}"
        else:
            response = "판단에 필요한 조회 결과가 없습니다. 주문 정보를 다시 확인해 주세요."
        state.response = response
        return response

    def write_policy_evidence_missing(self, state: PolicyAgentState) -> str:
        """Deterministically convert a clause-evidence gap to NEED_MORE_INFO."""

        state.decision = "NEED_MORE_INFO"
        details = ", ".join(state.missing_evidence) if state.missing_evidence else "미확인 항목"
        state.rationale = f"선택된 정책 조항에 필요한 근거가 부족합니다: {details}"
        return self.write(state)

    def __call__(self, state: PolicyAgentState) -> str:
        return self.write(state)
