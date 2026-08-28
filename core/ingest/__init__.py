"""실행 기록을 AuditBundle로 들여오는 계층.

Testbed는 케이스별 trial_*.json까지만 만든다. 그 로그를 Auditor의 계약
(core/schemas)으로 옮기고 검증한 뒤 번들 하나로 묶는 일은 스키마를 소유한
Auditor가 한다. 대상 에이전트는 Auditor를 알지 못한다.

    에이전트 로그 ──> mapper (계약 검증) ──> collect (번들 조립) ──> Auditor
"""

from core.ingest.collect import collect_run, make_bundle
from core.ingest.mapper import IngestError, to_trace_steps, to_trial_result

__all__ = [
    "IngestError",
    "collect_run",
    "make_bundle",
    "to_trace_steps",
    "to_trial_result",
]
