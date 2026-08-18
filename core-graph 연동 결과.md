# core-graph 연동 결과

> 작성일: 2026-08-18 (Asia/Seoul)
>
> Core 연동 코드 커밋: `feat/core-graph`의 `f6652c7`
>
> Scaffold 기준: `origin/feat/repair-loop` 커밋 `13d3928`

## 결론

**이준원 Core 쪽에서 가능한 연동 작업은 완료했다.**

- 유채린의 현재 `repair_once(dict_state, llm)`는 실제 브랜치 코드를 불러와 Core의 `SQLRepairAdapter`와 연결했으며 정상 동작했다.
- 아직 유채린 브랜치에 없는 `reasoning_verifier.py`를 기다리지 않고, 예정된 `verify_once`의 dict 출력 형식을 받을 수 있는 `ReasoningVerifierAdapter`와 Core 반영 루프를 만들었다.
- Repair·Verifier 반복, 중단, `iteration`, LLM 호출 수, 토큰, Trace는 Core graph가 한곳에서 기록한다.
- 공용 `core/schemas/`와 유채린 담당 `agents/policy_agent/scaffolds/`는 수정하지 않았다.

다만 **유채린 브랜치에 `reasoning_verifier.py`가 아직 없으므로 실제 Verifier 구현을 사용한 최종 양쪽 브랜치 통합은 아직 완료할 수 없다.**

## 확정한 연동 방식

반복 주체는 Repair와 Verifier 모두 `PolicyAgentGraph`다.

```text
Core graph
  ├─ SQL 실패
  │    └─ SQLRepairAdapter → 유채린 repair_once 1회
  │         └─ Core가 재실행·재시도·중단·Trace 기록
  │
  └─ 정책 판정
       └─ ReasoningVerifierAdapter → 유채린 verify_once 1회
            ├─ PASS → 응답 생성
            └─ FAIL → Core PolicyReasoner 재판정
                       └─ max_reflections 한도까지 반복
```

유채린 함수 안에서 자체 반복을 돌리지 않는다. 한 함수가 여러 LLM 호출을 수행하면 Core가 계약 위반으로 중단하도록 방어했다.

## 변경한 파일

| 파일 | 변경 내용 |
|---|---|
| `agents/policy_agent/nodes/state.py` | `max_reflections`, `stop_on_repeated_error`, `max_total_steps`, `verifier_status`, `verifier_issues`, `reflection_count`, `sql_history` 추가 |
| `agents/policy_agent/nodes/graph.py` | 구조화 Verifier 결과, Reflection 반복, 재판정, 반복별 Trace·비용 기록, 동일 SQL 오류 조기 중단, step 제한 구현 |
| `agents/policy_agent/nodes/policy_reasoner.py` | Reflection 때 이전 판정과 `verifier_issues`를 신뢰 피드백으로 전달 |
| `agents/policy_agent/nodes/sql_executor.py` | SQLite 오류를 `NO_SUCH_TABLE`, `NO_SUCH_COLUMN`, `SQL_SYNTAX_ERROR` 등으로 분류 |
| `agents/policy_agent/nodes/scaffold_adapters.py` | dict 기반 `repair_once`·`verify_once` 어댑터와 config 변환 함수 신규 작성 |
| `agents/policy_agent/nodes/__init__.py` | 새 어댑터·결과 객체·config 변환 함수 공개 |
| `agents/policy_agent/nodes/README.md` | 연동 규칙과 실행 책임 문서화 |
| `tests/testbed/test_core_graph.py` | Repair·Verifier·Reflection·config·중단 규칙 테스트 추가 |

## 체크리스트 항목별 결과

| 체크리스트 항목 | 처리 결과 |
|---|---|
| 필드명 불일치 | `scaffold_adapters.py`가 dict ↔ `PolicyAgentState`를 변환 |
| Repair 함수 시그니처 불일치 | `SQLRepairAdapter`가 `(dict_state, llm)`을 `(state, query, error) -> SQLQuery`로 변환 |
| Repair 루프 주체 | 기존대로 Core graph 소유 |
| `max_reflections` 부재 | `AgentConfig.max_reflections` 추가 |
| Verifier `bool` 반환 한계 | bool 호환을 유지하면서 `verifier_status`·`verifier_issues` 구조화 출력 지원 |
| Verifier 루프 주체 | Core graph 소유로 확정 |
| Verifier `iteration` 누락 | 첫 검증 0, Reflection 후 검증 1..N으로 기록 |
| Verifier 비용 과소 계상 | 호출별 `ProviderResult`, 토큰, `llm_call_count`를 따로 기록 |
| Reflection 재추론 부재 | FAIL 이슈를 `PolicyReasoner`에 전달해 재판정 |
| 동일 SQL 오류 중단 | `stop_on_repeated_error`를 Core repair 루프에 반영 |
| 전역 step 제한 | `max_total_steps`를 Core repair 경계에서 적용 |

## Config 대응

`agent_config_from_scaffold(AGENT_CONFIG)`가 다음 키를 변환한다.

| 유채린 config | Core config |
|---|---|
| `use_sql_repair` | `enable_repair` |
| `max_sql_retries` | `max_retries` |
| `stop_on_repeated_error` | 같은 이름으로 적용 |
| `use_reasoning_verifier` | `enable_verifier` |
| `max_reflections` | 같은 이름으로 적용 |
| `max_total_steps` | 같은 이름으로 적용 |

`max_total_tokens`, `max_total_latency_ms`는 현재 Core에 안전한 강제 중단 경계가 없으므로 값이 `None`이 아닐 때 조용히 무시하지 않고 명시적 오류를 낸다.

`TrialResult.scaffold_config["verifier"]`에는 Verifier가 활성화된 경우 `max_reflections` 값이 기록된다. 따라서 Reflection 1회와 2회 실험이 같은 config로 저장되지 않는다.

## Verifier 단일 호출 계약

Core가 직접 받는 표준 출력은 다음과 같다.

```python
{
    "verifier_status": "PASS",  # 또는 "FAIL"
    "verifier_issues": [],       # FAIL이면 수정할 문제 목록
}
```

호환을 위해 `status`/`issues`, 기존 bool, `VerifierDecision`, `ProviderResult`도 정규화한다. 유채린의 `verify_once`가 전체 dict state를 반환해도 위 두 필드를 읽는다.

Reflection은 다음 순서로 기록된다.

```text
DECIDE(iteration=None)
VERIFY_REASONING(iteration=0)
DECIDE(iteration=1)                 # 첫 FAIL 이후
CHECK_EVIDENCE(iteration=1)
VERIFY_REASONING(iteration=1)
...
```

한도까지 모두 FAIL이면 `stop_reason=MAX_REFLECTION`, `error_type=VERIFIER_REJECTED`로 끝난다.

## 검증 결과

2026-08-18 기준 다음 검사를 통과했다.

- Core 전체 기능 테스트: **27개 통과**
- Ruff 정적 검사: **통과**
- `git diff --check`: **통과**
- 유채린 실제 `repair_once` (`13d3928`) + 새 `SQLRepairAdapter` 스모크 테스트: **통과**
- Verifier PASS: 통과
- Verifier FAIL → Reflection 1회 → PASS: 통과
- Reflection 한도 소진 → `MAX_REFLECTION`: 통과
- Verifier 반복별 토큰·호출 수·Trace iteration: 통과
- 동일 SQL 오류 조기 중단: 통과
- 서로 다른 SQL 오류에서는 남은 retry 계속 사용: 통과
- 전역 step 제한 중단: 통과
- Scaffold config 키 변환: 통과

## 실제 연결 예시

유채린의 `reasoning_verifier.py`에 `verify_once`가 추가된 뒤 다음 형태로 연결한다.

```python
from agents.policy_agent.nodes import (
    ReasoningVerifierAdapter,
    SQLRepairAdapter,
    agent_config_from_scaffold,
)
from agents.policy_agent.scaffolds.config import AGENT_CONFIG
from agents.policy_agent.scaffolds.reasoning_verifier import verify_once
from agents.policy_agent.scaffolds.sql_repair import repair_once

config = agent_config_from_scaffold(AGENT_CONFIG)
sql_repair = SQLRepairAdapter(repair_once, repair_llm)
reasoning_verifier = ReasoningVerifierAdapter(verify_once, verifier_llm)
```

이 객체들을 `PolicyAgentGraph`의 `config`, `sql_repair`, `reasoning_verifier`에 주입하면 된다.

## 아직 남은 작업

1. 유채린이 `agents/policy_agent/scaffolds/reasoning_verifier.py`와 `verify_once`를 실제로 추가해야 한다.
2. 실제 `verify_once`의 status 문자열이 `PASS`/`FAIL`인지 최종 확인한다. 다른 문자열이어도 어댑터 정규화 표에 추가하면 된다.
3. 두 feature 브랜치를 함께 둔 상태에서 SQL Repair + Verifier 전체 통합 테스트를 실행해야 한다.
4. `tester` 최신 코드, 실제 DB·정책·모델 API를 연결한 환경 통합 테스트가 남아 있다.
5. 연동 코드는 커밋 `f6652c7`로 `feat/core-graph`에 push했다. PR은 만들지 않았다.

## 최종 판정

- **현재 유채린 SQL Repair 코드와 Core의 연동: 완료**
- **예정된 유채린 Verifier 인터페이스에 대한 Core 준비: 완료**
- **유채린 실제 Verifier 코드까지 포함한 최종 통합: 파일 미구현으로 대기**
