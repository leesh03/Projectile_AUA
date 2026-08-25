# 축소형 Agent 구조·입출력 계약

## 실행 경계

축소형 Agent에는 두 개의 서로 다른 실행 경계가 있다.

```text
SuiteRunner(부모 평가 경계)
├─ data/agent_cases.json 읽기
├─ evaluation/private/expected_cases.json 읽기
└─ isolated_worker 실행
       └─ agent_execution_guard 적용
          ├─ 공개 DB·정책 읽기 허용
          ├─ Gold·Oracle 파일 읽기/목록 조회 차단
          └─ 하위 프로세스를 통한 우회 차단
```

Agent가 종료되면 Runner가 반환된 결과를 정책 엔진 및 Gold와 비교하고 `policy_correct`, `gold_agreement`를 기록한다. 따라서 평가 정답은 모델 프롬프트, Agent 상태, trace에 들어가지 않는다.

## 조립 지점

`policy_runtime/factory.py`의 `build_agent(root, mode, provider, model)`이 모든 구성 요소를 조립한다.

| 구성 요소 | 구현 파일 | 입력 | 출력 |
|---|---|---|---|
| ContextProvider | `nodes/context_provider.py` | DB·정책 경로 | 스키마, 공개 정책 |
| SQLGenerator | `nodes/sql_generator.py` | AgentRequest, 스키마 | SQLPlan과 5개 SQLQuery |
| SQLExecutor | `nodes/sql_executor.py` | 검증 대상 SQLQuery | 읽기 전용 조회 결과 |
| EvidenceChecker | `nodes/evidence_check.py` | 다섯 조회 결과 | 정규화된 PolicyFacts |
| PolicyReasoner | `nodes/policy_reasoner.py` | PolicyFacts, 정책 규칙 | decision, clauses, rationale |
| SQL Repair | `scaffolds/sql_repair.py` | 실패 SQL과 오류 | 수정 SQL 1개 |
| Reasoning Verifier | `scaffolds/reasoning_verifier.py` | 판정·조항·근거 | PASS/FAIL와 issues |
| ResponseWriter | `nodes/response_writer.py` | 검증된 판정 | 한국어 사용자 답변 |

그래프와 반복 횟수의 소유자는 Core다. Scaffold는 한 번의 Repair 또는 한 번의 Verify만 수행한다. 설정은 `scaffolds/config.py`에서 관리한다.

## 입력 계약: AgentRequest

`agents/policy_agent/nodes/state.py`의 `AgentRequest.from_mapping()`이 입력을 검증한다.

```json
{
  "testcase_id": "E-001",
  "difficulty": "EASY",
  "question": "OI-E-001 주문 상품은 지금 전액 환불할 수 있나요?",
  "request": {
    "refund_request_id": "RR-E-001",
    "order_item_id": "OI-E-001",
    "requested_amount": 10000,
    "currency": "KRW"
  },
  "target_ids": {
    "customer_id": "C-E-001",
    "order_id": "O-E-001",
    "order_item_id": "OI-E-001",
    "product_id": "P-E-001",
    "shipment_id": "SH-E-001"
  },
  "trusted_context": {
    "evaluation_date": "2026-08-15",
    "timezone": "Asia/Seoul"
  }
}
```

허용되지 않은 추가 최상위 필드가 있으면 입력을 거부한다. 특히 `expected_result`, 정답 판정, Oracle 결과는 AgentRequest에 포함할 수 없다.

## Agent 출력 계약

`agent_output`은 사용자 전달 및 메인 Agent 연동에 필요한 업무 결과다.

```json
{
  "decision": "APPROVE",
  "clauses": ["POL-00.08", "POL-20.01", "POL-50.07"],
  "rationale": "다른 종결 조항이 없는 전액 환불 승인",
  "response": "요청을 승인할 수 있습니다.\n근거: 다른 종결 조항이 없는 전액 환불 승인\n적용 정책: POL-00.08, POL-20.01, POL-50.07",
  "verifier_status": "PASS",
  "verifier_issues": []
}
```

`decision`은 `APPROVE`, `REJECT`, `NEED_MORE_INFO`, `NOT_APPLICABLE` 중 하나다. 메인 Agent는 `response`를 사용자에게 보여주고, 나머지 필드는 내부 상태·감사 로그·후속 분기에 사용한다.

## TrialResult와 Trace

테스트 Runner는 업무 결과 외에 평가용 실행 기록을 남긴다.

- `task_success`: Agent가 정상 종료했는지
- `policy_correct`: Agent 판정이 공개 정책 엔진의 판정과 같은지
- `gold_agreement`: 정책 엔진 결과가 비공개 Gold와 같은지; suite summary에 기록
- `tool_error_count`, `retry_count`, `llm_call_count`
- `total_tokens`, `latency_ms`
- `stop_reason`, `error_type`, `safety_violation`
- `scaffold_config`: Planner/Repair/Verifier 활성 상태

각 `TraceStep`에는 `node_role`, `type`, `outcome`, 도구명, iteration, 토큰, 지연 시간이 기록된다. 이 계약은 `core/schemas/`와 `PolicyAgentState.to_trial_result()`에서 확인할 수 있다.

## 결정론 모드와 API 모드

| 항목 | deterministic | api |
|---|---|---|
| 용도 | 빠른 회귀 테스트 | 실제 모델 통합 테스트 |
| SQLPlan | 고정된 안전한 5개 조회 | 동일한 안전한 5개 조회 |
| 정책 판단 | 로컬 결정론 모델 | 선택한 API 모델 |
| SQL Repair | 비활성 | 최대 2회 |
| Verifier | 로컬 정책 인식 Verifier | 선택한 API 모델 |
| API 키 | 불필요 | 환경변수로만 전달 |

지원 환경변수는 `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`다. 키는 자식 프로세스 환경에만 전달하며 명령행, 결과 JSON, manifest에 저장하지 않는다.

## 메인 Agent 어댑터 체크리스트

1. 메인 Agent 상태에서 `question`, `order_item_id`, 요청액, 통화, 기준일을 얻는다.
2. 사용자 입력에서 모르는 ID를 임의 생성하지 말고 인증된 주문 조회 기능으로 확정한다.
3. 위 값을 `AgentRequest`로 변환한다.
4. 정책 Agent 결과의 `decision`과 `clauses`를 메인 Agent의 후속 행동 분기에 매핑한다.
5. `NEED_MORE_INFO`이면 누락된 주문 또는 증빙 정보를 사용자에게 요청한다.
6. `APPROVE`라도 실제 환불 API 호출 전에는 메인 Agent의 권한·확인 절차를 거친다.
7. 메인 Agent 테스트도 Agent 프로세스와 평가 Runner를 분리하고 Gold를 프롬프트에 넣지 않는다.
8. 변경할 때마다 결정론 60건 전체와 API 1건 smoke test를 먼저 통과시킨다.

## 현재 범위 밖

- 로그인, 사용자 인증, 주문 목록 검색 및 선택 UI
- 실제 결제사 환불 실행 API
- 메인 Agent의 다른 업무 유형 라우팅
- 신뢰하지 않는 네이티브 플러그인을 위한 OS 계정/컨테이너 격리

이 항목들은 축소형 정책 Agent의 결함이 아니라 메인 Agent 또는 배포 환경에서 연결해야 하는 서비스 경계다.
