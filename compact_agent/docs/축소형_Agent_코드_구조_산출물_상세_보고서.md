# 축소형 Agent 코드·구조·산출물 상세 보고서

> 작성 기준일: 2026-08-25 (Asia/Seoul)  
> 기준 브랜치: `feat/core-graph`  
> 기준 커밋: `92de5291dd21d6980e4c702657e5b359349a5a74`  
> 대상 폴더: `compact_agent/`  
> 정책 버전: `policy-v0.5`

## 1. 보고서 목적

이 보고서는 `compact_agent`가 무엇을 위해 만들어졌고, 어떤 코드로 구성되며, 사용자 질문이 들어온 뒤 어떤 과정을 거쳐 답변과 평가 결과를 만드는지 설명한다. 또한 축소형 Agent가 전체 Agent Migration 프로젝트에서 어떤 역할을 맡는지, 향후 메인 Agent와 어떻게 연결해야 하는지, 현재 가능한 일과 아직 범위 밖인 일을 구분한다.

핵심 독자는 다음과 같다.

- 축소형 Agent를 처음 인수받는 메인 Agent 개발자
- 이준원의 Core, 유채린의 Scaffold, 정책·데이터 통합 결과를 검토하는 팀원
- Agent의 입력·출력 및 실행기록 계약을 연결해야 하는 Auditor 개발자
- 정책이나 모델을 변경한 뒤 회귀 테스트를 수행해야 하는 개발자

## 2. 한눈에 보는 결론

`compact_agent`는 주문·환불 질문을 처리하는 독립 실행형 Testbed Agent다. 사용자의 질문과 구조화된 주문 식별자를 입력받아 다음 일을 수행한다.

1. 읽기 전용 SQLite DB에서 주문, 고객 스냅샷, 상품, 배송, 환불 이력을 조회한다.
2. 조회 결과를 표준 `PolicyFacts` 구조로 조립한다.
3. `policy-v0.5`의 47개 정책 조항과 우선순위에 따라 승인·거절·추가 정보 요청·적용 대상 아님 중 하나를 판단한다.
4. Reasoning Verifier로 판정과 근거를 다시 검사한다.
5. 사용자용 한국어 답변을 만든다.
6. 개발·평가를 위해 `TrialResult`, 단계별 `TraceStep`, Provider 사용량, 실행 Manifest를 저장한다.

이 Agent의 중요한 특징은 업무 실행과 평가 정답을 분리했다는 점이다. Agent 프로세스는 Gold·Oracle을 읽지 못한다. Agent가 종료된 뒤 부모 Runner만 비공개 Gold와 결과를 비교한다.

현재 구조를 한 줄로 표현하면 다음과 같다.

```text
질문·주문 컨텍스트 → 안전한 DB 조회 → 사실 조립 → 정책 판단 → 근거 검증 → 답변·실행기록 → 격리된 평가
```

## 3. 전체 프로젝트에서의 위치

### 3.1 Agent Migration 프로젝트

전체 프로젝트의 목적은 Agent의 모델, 프롬프트, 도구 또는 실행구조가 바뀌었을 때 발생하는 회귀와 안전·효율 문제를 찾는 것이다. 프로젝트에는 크게 두 구성요소가 있다.

| 구성요소 | 역할 | 주요 산출물 |
|---|---|---|
| Order & Refund Policy Agent | 실제 주문·환불 업무를 수행하는 Testbed | 답변, `TrialResult`, `TraceStep` |
| Agent Upgrade Auditor | 변경 전 V0와 변경 후 V1의 실행기록을 비교 | 회귀·안전·효율·개선 보고서 |

축소형 Agent는 첫 번째 구성요소를 독립 실행 가능한 형태로 묶은 것이다. 즉, 대회 최종 산출물인 Auditor가 비교할 수 있는 신뢰 가능한 V0/V1 실행기록을 만드는 시험용 업무 Agent다.

```text
compact_agent V0 또는 V1
        │
        ├─ 사용자용 정책 답변
        ├─ TrialResult
        └─ TraceStep
                │
                ▼
         Agent Upgrade Auditor
                │
                ▼
       회귀·안전·비용·지연 분석
```

Auditor는 축소형 Agent의 내부 코드를 직접 실행하는 것이 아니라, 축소형 Agent가 남긴 표준 실행기록을 소비하는 구조가 기본이다.

### 3.2 팀원별 코드 통합 관계

| 담당 | 원래 담당 영역 | `compact_agent`에서의 반영 |
|---|---|---|
| 이준원 | 질문부터 답변까지의 Core 실행 경로 | `agents/policy_agent/nodes/` 전체 |
| 유채린 | SQL Repair, Reasoning Verifier | `agents/policy_agent/scaffolds/` 및 Core 연결 어댑터 |
| 정우혁 역할의 정책·데이터 | DB, 사례, 정책, 평가자료 | `data/`, `policies/`, `evaluation/private/`에 통합 규격으로 재구성 |
| 이소현 | 공용 실행기록 계약과 Auditor | `core/schemas/`의 로컬 호환 계약, 추후 메인 계약 연결 대상 |

정책 실행 코드는 정우혁 브랜치의 기존 Oracle을 Agent 내부에 그대로 넣지 않았다. 정책 MD를 기준으로 기계 정책 `policy_rules.json`과 독립 정책 엔진을 만들고, 기존 파일 역할을 다음처럼 분리했다.

| 과거에 기대했던 파일 | 현재 통합본의 대응 파일 | 변경 이유 |
|---|---|---|
| `shop.db` | `data/shop.db` 또는 `--db-path` | 기본은 개발 회귀 DB, 공식 DB는 실행 시 교체 |
| `data/test_cases.json` | `data/agent_cases.json` + `evaluation/private/expected_cases.json` | Agent 입력과 Gold 정답 분리 |
| `policy_text.json` | `policies/policy_rules.json` | 정책 버전·조항·우선순위·증거 계약을 명확히 구조화 |
| `policy_oracle.py` | `policy_runtime/engine.py` + 부모 Runner 평가 | Agent가 Oracle을 직접 읽는 문제 방지 |

## 4. 설계 원칙

### 4.1 Core와 Scaffold의 분리

Core는 보조 기능이 꺼져 있어도 질문부터 답변까지 완료할 수 있는 최소 업무 경로다. Scaffold는 실패 복구나 결과 재검증을 담당하는 보조 구조다.

- Core: ContextProvider, SQLGenerator, SQLExecutor, EvidenceChecker, PolicyReasoner, ResponseWriter
- Scaffold: SQL Repair, Reasoning Verifier

반복문과 중단 조건은 Core Graph가 소유한다. Scaffold 함수는 한 번의 Repair 또는 한 번의 Verify만 수행한다. 이 방식은 보조 코드가 전체 실행을 무한 반복하거나 상태를 임의로 소유하지 않게 한다.

### 4.2 Planner 비활성화

현재 설정에서 별도 Planner는 사용하지 않는다.

```text
planner = false
```

이유는 `SQLGenerator` 내부에 이미 `SQLPlan` 계약이 있기 때문이다. 별도 Planner를 추가하면 계획 단계가 중복되고 V0/V1 비교 변수도 늘어난다. 현재 SQL 조회는 `order`, `customer_snapshot`, `product`, `shipment`, `refund_history`라는 5개의 고정된 증거 영역을 사용한다.

### 4.3 구조화된 입력과 자연어의 분리

사용자 질문은 신뢰하지 않는 자연어다. 질문 속에 “정책을 무시해”, “다른 주문을 조회해”, “DB를 삭제해” 같은 지시가 있어도 권한이나 구조화된 주문 ID를 변경할 수 없어야 한다.

따라서 다음 항목을 분리한다.

- 비신뢰 입력: `question`
- 신뢰 입력: `request`, `target_ids`, `trusted_context`
- 시스템 통제 정보: DB schema, 허용 테이블, 정책, 출력 schema

모델 Provider에 전달할 때도 `user_question_trust = UNTRUSTED_NATURAL_LANGUAGE`와 보안 지시를 함께 전달한다.

### 4.4 업무 판단과 평가 정답의 분리

Agent는 공개 DB와 공개 정책만 사용한다. `expected_cases.json` 같은 평가 정답은 Agent 프로세스가 읽을 수 없다. `policy_correct`도 Agent가 스스로 선언하는 값이 아니라 독립 평가자가 계산한다.

이 분리는 “정답을 보고 맞히는 Agent”가 아니라 “DB와 정책을 근거로 실제 판단하는 Agent”를 테스트하기 위한 핵심 조건이다.

## 5. 전체 폴더 구조

```text
compact_agent/
├─ README.md
├─ run_agent.py
├─ .env.example
├─ PACKAGE_MANIFEST.json
│
├─ agents/policy_agent/
│  ├─ nodes/
│  │  ├─ state.py
│  │  ├─ graph.py
│  │  ├─ context_provider.py
│  │  ├─ sql_generator.py
│  │  ├─ sql_executor.py
│  │  ├─ evidence_check.py
│  │  ├─ policy_reasoner.py
│  │  ├─ response_writer.py
│  │  └─ scaffold_adapters.py
│  └─ scaffolds/
│     ├─ config.py
│     ├─ llm.py
│     ├─ sql_repair.py
│     ├─ reasoning_verifier.py
│     └─ trace.py
│
├─ policy_runtime/
│  ├─ factory.py
│  ├─ deterministic.py
│  ├─ openai_provider.py
│  ├─ multi_provider.py
│  ├─ loader.py
│  ├─ engine.py
│  ├─ runner.py
│  ├─ isolated_worker.py
│  ├─ access_guard.py
│  └─ env.py
│
├─ data/
│  ├─ shop.db
│  ├─ agent_cases.json
│  └─ *_manifest.json
│
├─ scripts/
│  ├─ sync_test_assets.py
│  └─ build_submission.py
│
├─ policies/
│  ├─ source/refund_policy_spec_v0.5.md
│  └─ policy_rules.json
│
├─ evaluation/private/
│  └─ expected_cases.json
│
├─ core/schemas/
│  ├─ enums.py
│  └─ trace.py
│
├─ tests/
├─ examples/
└─ docs/
```

## 6. Core 코드 상세 설명

### 6.1 `state.py`: 입력·상태·측정·산출물의 중심

`PolicyAgentState`는 한 번의 Agent 실행에 필요한 모든 상태를 보관한다. 별도 테스트용 `_state_stub.py`는 사용하지 않는다. Core와 유채린 Scaffold가 같은 실제 상태 객체를 공유한다.

주요 상태 그룹은 다음과 같다.

| 그룹 | 주요 필드 | 의미 |
|---|---|---|
| 입력 | `agent_request`, `agent_label`, `trial`, `run_id` | 어떤 사례를 어떤 Agent 버전으로 실행하는지 |
| 컨텍스트 | `context`, `runtime_config` | DB schema, 정책, 실행 제한 |
| SQL | `query_plan`, `sql_history`, `query_results` | 생성·수정·실행된 SQL과 조회 결과 |
| 근거 | `facts`, `missing_evidence` | 정책 판단에 사용할 정규 사실 |
| 판단 | `decision`, `policy_clauses`, `rationale`, `confidence` | Agent의 정책 결과 |
| 검증 | `verifier_status`, `verifier_issues`, `reflection_count` | Verifier 결과와 재추론 횟수 |
| 최종 응답 | `response` | 사용자에게 전달할 문장 |
| 실행 평가 | `task_success`, `stop_reason`, `error_type` | 정상 종료 및 실패 분류 |
| 비용·안전 | 토큰, 지연, 오류, 재시도, 안전 위반 | Auditor가 비교할 지표 |
| 기록 | `traces`, `provider_calls` | 단계별 실행과 실제 API 메타데이터 |

`AgentRequest.from_mapping()`은 허용된 최상위 필드만 받는다. 예상 결과나 Gold 필드가 추가되면 입력을 거부한다. 이 객체가 Agent 입력 경계다.

`write_trial_artifact()`는 한 실행 결과를 다음 경로에 원자적으로 저장한다.

```text
reports/runs/<run_id>/manifest.json
reports/runs/<run_id>/<agent_label>/<testcase_id>/trial_<n>.json
```

### 6.2 `graph.py`: 전체 실행 순서와 실패 처리를 소유

`PolicyAgentGraph.run()`은 전체 노드 순서를 통제한다. LangGraph 라이브러리에 종속되지 않은 Provider-neutral 오케스트레이션이므로, 메인 Agent에서 래핑하거나 다른 그래프에 하위 노드로 넣기 쉽다.

Graph의 주요 책임은 다음과 같다.

- 각 노드의 시작·성공·실패를 Trace로 기록
- SQL 검증과 실행
- SQL 실패 시 Repair 횟수 및 중단 조건 관리
- 구조적 Evidence와 조항별 Evidence의 2단계 검사
- Reasoning Verifier와 재추론 반복 관리
- 예외를 표준 `stop_reason`과 `error_type`으로 변환
- 최종 `task_success` 결정

주요 실패 분류는 다음과 같다.

| `stop_reason` | 의미 |
|---|---|
| `OK` | 정책 결정까지 정상 완료 |
| `SQL_FAILURE` | DB 실행 오류 |
| `MAX_RETRY` | SQL Repair 한도 또는 반복 오류 중단 |
| `MAX_REFLECTION` | Verifier 재추론 한도 초과 |
| `INSUFFICIENT_EVIDENCE` | 정책 판단에 필요한 근거 부족 |
| `TOOL_SCHEMA_ERROR` | SQL 안전 계약 또는 조회 결과 구조 위반 |
| `PROVIDER_ERROR` | 모델 출력, 정책 판단, Verifier 계약 오류 |

`NEED_MORE_INFO`는 정상적인 업무 판정일 수 있다. 필요한 정보가 없다는 사실을 정책 조항에 따라 정확히 판단했다면 `task_success=true`, `stop_reason=OK`가 될 수 있다. 반대로 Core 자체가 근거 조립에 실패한 경우는 `INSUFFICIENT_EVIDENCE`로 종료된다.

### 6.3 `context_provider.py`: DB schema와 정책 로드

ContextProvider는 다음 정보를 시스템 통제 컨텍스트로 로드한다.

- 허용된 SQLite 테이블과 각 컬럼 schema
- 압축된 기계 정책 JSON
- 정책 버전
- 조항별 필수 Evidence 경로
- DB·정책 파일명과 SHA-256

DB는 URI의 `mode=ro`로 열며, 허용된 테이블이 실제 DB에 모두 있는지도 확인한다. SHA-256은 어떤 DB와 정책 버전으로 실행했는지 Manifest에 남기기 위해 사용한다.

### 6.4 `sql_generator.py`: 내부 SQLPlan

중앙 `QUERY_REGISTRY`는 조회 이름과 `PolicyFacts` 영역을 연결한다.

| Query 이름 | 목적 | 카디널리티 |
|---|---|---|
| `order` | 주문·결제·주문 시점 snapshot 기준 | 1건 |
| `customer_snapshot` | 주문 당시 고객 등급 | 1건 |
| `product` | 상품 분류와 final sale 여부 | 1건 |
| `shipment` | 배송·개봉·이슈·증빙 | 1건 |
| `refund_history` | 기존 환불 요청 이력 | 여러 건 |

`SQLGenerator`는 Provider 출력이 다음 계약을 지키는지 검사한다.

- 쿼리 이름은 허용된 registry 이름
- 중복 이름 금지
- 1~5개의 구조화된 쿼리
- SQL은 비어 있지 않아야 함
- 파라미터는 배열
- 모델 본문에 적힌 토큰 수는 믿지 않고 API 응답 메타데이터만 사용

현재 `factory.py`는 결정론 모드와 API 모드 모두 정상 조회 경로에서 `DeterministicSQLModel`의 검증된 5개 정형 쿼리를 주입한다. 따라서 API 모델이 임의 SQL을 만드는 구조가 아니다. API 모델은 정책 판단과 Verifier를 담당한다. SQL Repair 코드는 연결되어 있지만 정상 정형 쿼리에서는 호출되지 않는다.

### 6.5 `sql_executor.py`: SQL 이중 안전장치

첫 번째 방어층인 `SQLGuard`는 실행 전에 다음을 차단한다.

- 빈 SQL
- 주석
- 여러 SQL 문장
- `SELECT`가 아닌 문장
- INSERT, UPDATE, DELETE, DROP, ALTER, ATTACH, PRAGMA 등 위험 키워드
- 닫히지 않은 문자열

두 번째 방어층은 SQLite authorizer다.

- DB 자체를 읽기 전용으로 연결
- `PRAGMA query_only = ON`
- allow-list 밖 테이블 읽기 차단
- SELECT·READ·허용 함수 이외 SQLite action 차단
- 행 수, 실행 step, 실행시간 제한

기본 제한은 쿼리당 최대 200행, 100,000 step, 5초다. 따라서 문자열 검사 하나에만 의존하지 않고 SQLite 실행 엔진에서도 쓰기와 비허용 접근을 막는다.

### 6.6 `evidence_check.py`: SQL 결과를 PolicyFacts로 변환

EvidenceChecker는 SQL의 평면 컬럼을 `__` 구분자로 중첩 객체로 변환한다.

```text
evidence_status AS evidence__evidence_status
```

위 alias는 다음처럼 변환된다.

```json
{
  "evidence": {
    "evidence_status": "VERIFIED"
  }
}
```

검사는 두 단계로 이루어진다.

1. 구조적 검사
   - 조회 결과를 표준 `PolicyFacts`로 조립
   - cardinality와 ID 연결 상태 보존
   - 요청자가 지정한 기본 필수 경로 확인
2. 정책 조항별 검사
   - Reasoner가 선택한 조항의 `required_paths` 확인
   - 필요한 증빙이 없으면 `NEED_MORE_INFO` 응답으로 전환

중복 조회나 ID 불일치는 Core가 즉시 버리는 오류가 아니라 정책 판단 대상이다. 이 사실을 `PolicyFacts`에 보존해 POL-10 계열 조항이 정확히 판단하도록 한다.

### 6.7 `policy_reasoner.py`: 구조화된 정책 판단

PolicyReasoner는 다음 정보를 판단 모델에 전달한다.

- 비신뢰 사용자 질문
- 신뢰 요청값과 대상 ID
- DB에서 조립한 `PolicyFacts`
- 공개 정책 컨텍스트
- 이전 판정과 Verifier 피드백
- 고정 출력 schema

출력은 다음 네 결정 중 하나여야 한다.

| Agent 결정 | 정책 엔진의 eligibility | 의미 |
|---|---|---|
| `APPROVE` | `ELIGIBLE` | 환불 승인 가능 |
| `REJECT` | `INELIGIBLE` | 정책상 승인 불가 |
| `NEED_MORE_INFO` | `UNDETERMINED` | 판단에 추가 정보 필요 |
| `NOT_APPLICABLE` | `NOT_APPLICABLE` | 새 환불 심사 대상이 아님 |

결정 외에 적용 조항 목록, 근거 문장, 선택적 self-reported confidence를 받는다. confidence는 정확도 보증값이 아니라 모델의 비보정 자기평가로 취급한다.

### 6.8 `response_writer.py`: 사용자 답변 생성

검증이 끝난 뒤 결정 코드를 한국어 문장으로 바꾼다.

```text
요청을 승인할 수 있습니다.
근거: 다른 종결 조항이 없는 전액 환불 승인
적용 정책: POL-00.08, POL-20.01, POL-50.07
```

현재 ResponseWriter는 의도적으로 단순하고 결정론적이다. 메인 Agent에서는 이 결과를 그대로 보여주거나, 판정·조항을 유지한 채 서비스 톤에 맞게 다시 표현할 수 있다.

### 6.9 `scaffold_adapters.py`: Core와 유채린 코드 연결

유채린 Scaffold가 Core 상태를 직접 소유하지 않도록 어댑터가 양쪽 계약을 변환한다.

- `SQLRepairAdapter`: Core의 실패 SQL, 오류, schema, 질문을 `repair_once` 입력으로 변환
- `ReasoningVerifierAdapter`: Core의 판정, 조항, facts를 `verify_once` 입력으로 변환
- `agent_config_from_scaffold`: 유채린 설정을 Core `AgentConfig`로 변환

이 계층 덕분에 Scaffold 내부 구현을 교체해도 Graph의 반복·Trace·TrialResult 규칙은 유지된다.

## 7. Scaffold 코드 상세 설명

### 7.1 SQL Repair

SQL Repair는 SQL Guard 또는 DB 실행에서 실패한 쿼리 하나를 수정한다. 입력에는 원래 쿼리, 오류 종류, DB schema, 허용 테이블, 사용자 질문이 포함된다.

주요 규칙은 다음과 같다.

- 한 번 호출할 때 수정 쿼리 하나만 반환
- 원래 query name 유지
- Core가 최대 재시도 횟수 관리
- 같은 오류가 반복되면 남은 횟수가 있어도 중단
- 안전 위반 SQL은 기본적으로 자동 Repair 대상이 아님
- API 모드 최대 2회, 결정론 정상 실행에서는 비활성

### 7.2 Reasoning Verifier

Reasoning Verifier는 정책 판정이 facts 및 정책 조항과 일치하는지 한 번 검사하고 다음을 반환한다.

```json
{
  "verifier_status": "PASS",
  "issues": []
}
```

실패하면 Graph가 Verifier의 issues를 PolicyReasoner에 전달해 다시 판단한다. 재추론 후 다시 검증하며 최대 reflection 횟수는 2회다. 계속 실패하면 `MAX_REFLECTION`으로 중단한다.

Verifier가 필요한 이유는 답변 문장이 자연스러운지 확인하기 위해서가 아니라 다음 오류를 잡기 위해서다.

- facts와 반대되는 결정
- 존재하지 않거나 잘못 선택된 정책 조항
- 조항에 필요한 증거 누락
- 결정과 rationale의 불일치
- 구조화 출력 계약 위반

### 7.3 Scaffold 설정

현재 주요 설정은 다음과 같다.

| 설정 | 값 | 의미 |
|---|---:|---|
| `use_planner` | `false` | 별도 Planner 미사용 |
| `use_sql_repair` | `true` | API 모드에서 Repair 연결 |
| `max_sql_retries` | 2 | SQL 수정 최대 횟수 |
| `stop_on_repeated_error` | `true` | 동일 오류 반복 시 조기 중단 |
| `use_reasoning_verifier` | `true` | 판정 재검증 활성 |
| `max_reflections` | 2 | 재추론 최대 횟수 |
| `max_total_steps` | 20 | Repair 루프의 전역 step 상한 |

## 8. 정책과 데이터 구조

### 8.1 사람용 정책과 기계 정책

정책은 두 형태로 보존한다.

- `policies/source/refund_policy_spec_v0.5.md`: 사람이 검토하는 정책 원문
- `policies/policy_rules.json`: Agent와 정책 엔진이 읽는 기계 정책

기계 정책의 현재 기준은 다음과 같다.

| 항목 | 값 |
|---|---|
| schema | `policy-rule-set-v1` |
| policy version | `policy-v0.5` |
| 정책 조항 | 47개 |
| Evidence contract | 14개 조항에 명시 |
| 통화 | KRW |
| 시간대 | Asia/Seoul |

각 정책 조항에는 ID, 숫자 우선순위, reason code, terminal 여부, 결과 tuple, 필수 경로, 요약이 들어간다.

정책 엔진의 상세 결과는 단순 승인·거절보다 풍부하다.

```text
eligibility
case_status
next_action
reason_code
primary_clause
matched_clauses
overridden_clauses
required_fields
facts_hash
versions
```

Agent 사용자 출력은 이 중 핵심을 `decision`, `clauses`, `rationale`, `response`로 축약한다. 평가자는 상세 정책 결과를 사용한다.

### 8.2 테스트 DB

`data/shop.db`는 현재 다섯 테이블을 가진다.

| 테이블 | 현재 테스트 행 수 | 주요 내용 |
|---|---:|---|
| `customers` | 59 | 조회 키별 고객 snapshot과 결측·중복 상태 |
| `orders` | 60 | 조회 키별 주문, snapshot, 상태, 결제 정보 |
| `products` | 59 | 조회 키별 상품 snapshot, 분류, final sale |
| `shipments` | 59 | 조회 키별 배송일, 개봉, 이슈, 증빙 |
| `refunds` | 10 | 기존 환불 이력 |

포함된 DB는 60개 입력 사실을 SQL로 검증하기 위한 개발 회귀 DB다. `lookup_order_item_id`와 실제 반환 ID를 분리하고 `record_present` 표시를 두어 결측, 중복 cardinality, 잘못된 참조까지 SQL 행으로 표현한다. 과거 9건 fixture adapter는 삭제했으며 `testcase_id`는 DB 조회나 정책 판단에 사용하지 않는다. 공식 DB가 정해지면 `--db-path` 또는 `POLICY_AGENT_DB_PATH`로 교체한다.

### 8.3 60개 사례

`agent_cases.json`은 난이도별로 다음과 같이 구성된다.

- EASY 20개
- MEDIUM 20개
- HARD 20개

Agent가 읽는 사례에는 질문, 요청값, 대상 ID, 기준일만 있다. Gold는 별도 `evaluation/private/expected_cases.json`에 60개가 존재한다.

## 9. 질문부터 답변까지의 전체 실행 과정

### 9.1 1단계: 입력 어댑터

메인 Agent 또는 테스트 Runner가 사용자 질문과 주문 컨텍스트를 `AgentRequest`로 만든다.

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

실제 서비스에서는 로그인 세션이나 주문 선택 화면이 신뢰할 수 있는 ID를 공급해야 한다. 자연어 질문만 보고 Agent가 주문 ID를 임의 추측하면 안 된다.

### 9.2 2단계: Context 로드

ContextProvider가 읽기 전용 DB schema와 기계 정책을 읽고 파일 hash까지 상태에 기록한다.

### 9.3 3단계: 조회계획 생성

SQLGenerator가 검증된 5개 query를 `SQLPlan`으로 만든다. 별도 Planner는 없다.

### 9.4 4단계: SQL 검증·실행

각 쿼리는 다음 순서를 독립적으로 거친다.

```text
SQLGuard 검사 → SQLite authorizer 검사 → 읽기 전용 실행 → 행 제한 → 결과 저장
```

실패하고 Repair가 허용된 경우 Core가 유채린 SQL Repair를 한 번 호출한 뒤 같은 query name으로 다시 검증한다.

### 9.5 5단계: PolicyFacts 조립

다섯 조회 결과를 주문·고객 snapshot·상품·배송·환불 이력의 표준 중첩 JSON으로 합친다. ID 연결, cardinality, boolean 타입, 중첩 alias 충돌도 검사한다.

### 9.6 6단계: 구조적 Evidence 검사

정책 Reasoner를 호출하기 전 최소 구조가 준비됐는지 확인한다. Core 자체가 요구하는 근거가 없으면 사용자에게 부족한 정보를 알리고 중단한다.

### 9.7 7단계: 정책 판단

결정론 모드는 로컬 정책 엔진을 감싼 모델이 판정한다. API 모드는 OpenAI, Gemini 또는 Groq 모델이 같은 구조화 계약으로 판정한다.

### 9.8 8단계: 조항별 Evidence 검사

선택된 정책 조항이 요구하는 경로를 공개 정책 metadata에서 읽어 다시 확인한다. Gold의 `required_fields`는 사용하지 않는다.

### 9.9 9단계: Reasoning Verifier

Verifier가 PASS하면 다음 단계로 간다. FAIL이면 issues를 포함해 다시 정책 판단하고 최대 2회까지 재검증한다.

### 9.10 10단계: 답변 생성

ResponseWriter가 결정, 근거, 적용 조항을 한국어 답변으로 만든다.

### 9.11 11단계: 실행 산출물 저장

Agent 프로세스가 `agent_output`, `TrialResult` placeholder, Trace, Provider calls, Manifest를 저장한다. 부모 Runner가 실행 종료 후에만 정책 정확도와 Gold 일치를 계산해 평가 필드를 보완한다.

## 10. 결정론 모드와 API 모드

| 구분 | deterministic | api |
|---|---|---|
| 목적 | 빠르고 재현 가능한 회귀 테스트 | 실제 모델 통합 검증 |
| API 키 | 불필요 | 필요 |
| SQLPlan | 고정 정형 5개 query | 고정 정형 5개 query |
| 정책 판단 | 로컬 정책 엔진 기반 | 선택 Provider 모델 |
| Verifier | 로컬 정책 인식 Verifier | 선택 Provider 모델 |
| SQL Repair | 정상 baseline에서 꺼짐 | 연결됨, 최대 2회 |
| 출력 계약 | 동일 | 동일 |

지원 Provider는 다음과 같다.

- OpenAI Responses
- Gemini `generateContent`
- Groq Chat Completions

외부 SDK 없이 표준 HTTP로 호출하며, Provider별 응답 형식을 공통 `ProviderResult`로 정규화한다. 토큰 수, 모델 ID, 응답 ID, finish reason, latency는 모델이 생성한 JSON 본문이 아니라 실제 API 응답 metadata에서 가져온다.

API 키는 `.env` 또는 환경변수에서만 읽는다.

```text
OPENAI_API_KEY
GEMINI_API_KEY
GROQ_API_KEY
```

키는 명령행, Trace, TrialResult, Manifest에 저장하지 않는다. Git에는 `.env.example`만 포함된다.

## 11. 도출되는 결과물

축소형 Agent의 결과는 사용자 답변 하나로 끝나지 않는다. 용도에 따라 다섯 종류의 산출물이 생성된다.

### 11.1 Agent 업무 출력

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

메인 Agent가 직접 소비할 핵심 결과다.

### 11.2 TrialResult

한 사례의 성공, 비용, 안전, 반복 상태를 요약한다.

| 필드 | 설명 |
|---|---|
| `task_success` | Agent가 업무 경로를 정상 완료했는지 |
| `engine_consistency` | Agent 판정·조항이 로컬 정책 엔진과 일치하는지 |
| `gold_agreement` | Agent 판정·조항이 비공개 Gold와 일치하는지 |
| `oracle_agreement` | 정책 엔진 상세 결과가 Gold와 일치하는지 |
| `policy_correct` | Gold가 있으면 Agent-Gold, 없으면 Agent-엔진 일치 |
| `tool_error_count` | SQL·도구 오류 수 |
| `retry_count` | SQL Repair 횟수 |
| `total_tokens` | 실제 Provider metadata 기반 토큰 합계 |
| `latency_ms` | 전체 실행 지연 |
| `safety_violation` | SQL 안전 계약 위반 여부 |
| `stop_reason` | 종료 이유 |
| `llm_call_count` | 모델 계약 호출 횟수 |
| `scaffold_config` | Planner·Repair·Verifier 설정 |

`task_success=true`가 곧 정책 정답을 의미하지는 않는다. 실행 성공과 정책 정확도를 구분하기 위해 `policy_correct`가 별도로 존재한다.

### 11.3 TraceStep

각 단계에 다음 내용이 기록된다.

- `step_index`
- `node_role`: RETRIEVE_SCHEMA, GENERATE_QUERY, VALIDATE_QUERY, EXECUTE_TOOL, CHECK_EVIDENCE, DECIDE, VERIFY_REASONING, GENERATE_RESPONSE 등
- 실행 유형: `code`, `tool_call`, `llm_call`
- 성공·실패·skip
- 도구 이름과 argument 유효성
- 오류 종류와 iteration
- 입력·출력 토큰
- 단계 latency

Auditor는 이 Trace를 이용해 “어느 단계에서 회귀했는지”, “재시도가 늘었는지”, “Verifier가 문제를 잡았는지”를 비교할 수 있다.

### 11.4 Provider call 기록과 Manifest

Provider call에는 Provider, 모델 ID, finish reason, latency, 요청 ID, token usage가 기록된다. Manifest에는 사용한 DB·정책 hash, Agent 설정, runtime limit, Provider와 모델이 기록된다.

따라서 같은 결과 파일이 어떤 코드·데이터·정책·모델 조건에서 만들어졌는지 추적할 수 있다.

### 11.5 Suite summary

여러 사례를 실행한 뒤 다음을 집계한다.

- 전체 trial 수
- task success 수
- policy correct 수
- engine consistency 수
- Agent-Gold agreement 수
- Oracle-Gold agreement 수
- mode와 Provider
- Planner 설정
- 격리 방식
- 사례별 결과·artifact 경로

## 12. Gold·Oracle 격리 구조

### 12.1 프로세스 분리

```text
SuiteRunner 부모 프로세스
├─ Agent 입력 읽기
├─ 비공개 Gold 읽기
└─ isolated_worker 자식 실행
       └─ agent_execution_guard
          ├─ 공개 DB·정책 허용
          ├─ Gold·Oracle 차단
          └─ 하위 프로세스 우회 차단
```

Agent 자식 프로세스는 sanitized AgentCase, 공개 프로젝트 경로, mode, Provider, 모델 정보만 받는다. API 키가 필요한 경우 자식 환경변수로만 전달한다.

### 12.2 차단 대상

Agent 실행 중에는 다음 경로 또는 파일을 읽거나 디렉터리 목록으로 탐색할 수 없다.

- `evaluation/private/`
- `expected_cases.json`
- `answer_key.db`
- `test_cases.json`
- `policy_oracle.py`
- 정책 비교 원본 폴더
- `subprocess`, `os.system` 등을 통한 우회 실행

### 12.3 평가 순서

1. Agent가 공개 DB와 정책만으로 decision·clauses를 생성한다.
2. Agent가 종료된다.
3. 부모 Runner가 반환 facts를 독립 정책 엔진으로 평가한다.
4. Agent decision·clauses와 정책 엔진 결과를 비교해 `engine_consistency`를 계산한다.
5. Agent decision·clauses와 비공개 Gold를 비교해 `gold_agreement`를 계산한다.
6. 정책 엔진의 상세 결과와 Gold를 비교해 `oracle_agreement`를 계산한다.
7. Runner가 trial artifact의 평가 placeholder를 원자적으로 갱신한다.

현재 격리는 Python audit hook과 subprocess 경계를 사용하는 `subprocess-audit-v1`이다. 현재의 신뢰된 Python Agent 코드에는 적합하지만, 신뢰하지 않는 네이티브 플러그인이나 임의 바이너리를 허용한다면 OS 계정, 파일 ACL 또는 컨테이너 격리를 추가해야 한다.

## 13. 테스트 구조와 검증 결과

### 13.1 테스트 종류

| 테스트 파일 | 검증 내용 |
|---|---|
| `test_policy_engine.py` | 47개 조항과 60개 Gold 정책 결과, 입력 계약 |
| `test_integration.py` | SQL DB 조회, testcase ID 독립성, 날짜, Verifier, Repair, Runner·제출 산출물 |
| `test_access_isolation.py` | 공개 자산 허용, Gold 차단, subprocess 우회 차단 |
| `test_openai_provider.py` | OpenAI 구조화 요청·응답·토큰 parsing |
| `test_multi_provider.py` | Gemini·Groq 요청·응답·토큰 parsing |

### 13.2 2026-08-25 재검증

이 보고서를 작성하면서 현재 `compact_agent`에서 다시 실행한 결과는 다음과 같다.

| 검증 | 결과 |
|---|---:|
| 단위·통합·격리 테스트 | 24/24 통과 |
| 결정론 suite | 60/60 task success |
| Agent-엔진 일치 | 60/60 |
| Agent-Gold 일치 | 60/60 |
| Oracle-Gold 일치 | 60/60 |
| run ID | `20260825T122838Z_ef9320fb` |
| isolation | `subprocess-audit-v1` |

이 결과는 결정론 모드의 재현 가능한 SQL·정책 엔진 회귀 결과다. 새로운 입력에 대한 LLM 정확도 100%나 실 API 60건 호출을 의미하지 않는다. 과거 Gemini·Groq E-001 한 건씩의 기록은 Provider 연결 smoke test 범위이며, 실제 모델 품질을 주장하려면 대표 HARD 사례를 추가 검증해야 한다.

## 14. 메인 Agent와의 연결 방법

### 14.1 권장 연결 경계

메인 Agent는 축소형 Agent를 “환불 정책 판단 하위 기능”으로 사용한다.

```text
사용자 대화
   │
   ▼
메인 Agent Intent Router
   │ 환불 문의
   ▼
인증·세션·주문 선택 어댑터
   │ AgentRequest
   ▼
compact policy agent
   │ decision + clauses + response + trace
   ▼
메인 Agent 후속 행동
   ├─ APPROVE → 사용자 확인 후 환불 실행 API
   ├─ REJECT → 정책 근거 안내
   ├─ NEED_MORE_INFO → 누락 정보 질문
   └─ NOT_APPLICABLE → 기존 처리 상태 또는 다른 흐름 안내
```

### 14.2 메인 Agent가 추가로 구현할 부분

- 로그인과 사용자 인증
- 사용자 계정에서 주문 목록 조회
- 질문 속 “이 상품”을 실제 `order_item_id`로 연결
- 여러 주문일 때 사용자 선택 받기
- 환불 외 문의를 다른 Agent나 도구로 라우팅
- 승인 후 실제 결제·환불 API 호출
- 실행 전 최종 사용자 확인 및 권한 검사
- 운영 DB와 정책 저장소 연결
- 서비스용 응답 톤과 다국어 처리

### 14.3 재사용해야 할 계약

메인 Agent가 내부 구현을 그대로 복사할 필요는 없지만 다음 계약은 유지하는 것이 좋다.

- `AgentRequest`의 신뢰·비신뢰 필드 분리
- `decision`, `clauses`, `rationale`, `response` 출력
- `TrialResult`와 `TraceStep`
- 공개 정책과 Gold 평가자료의 프로세스 분리
- SQL allow-list와 읽기 전용 실행
- Repair·Verifier 횟수 및 중단 조건

### 14.4 개발 순서

1. 메인 Agent의 상태를 `AgentRequest`로 변환하는 adapter를 만든다.
2. 현재 E-001 한 건으로 입력·출력 mapping을 확인한다.
3. 메인 Agent에서 축소형 Agent를 호출하되 Gold 경로를 전달하지 않는다.
4. 기존 결정론 60건을 메인 Agent 경유로 실행한다.
5. 직접 검토한 Gold와 `TrialResult`를 비교한다.
6. 실패 사례만 입력 adapter, 정책, DB 조회, 응답 단계로 분류한다.
7. 전체 60건 회귀 테스트를 다시 실행한다.
8. Gemini·Groq·선택한 운영 Provider별 smoke test를 실행한다.
9. 비용·지연·안전 조건이 만족되면 실제 환불 API는 별도 권한 경계로 연결한다.

## 15. 가능한 일과 현재 범위 밖

### 15.1 현재 가능한 일

- 구조화된 주문 컨텍스트를 받은 환불 정책 판단
- 승인·거절·추가 정보·적용 대상 아님 분류
- 적용 정책 조항과 근거 제시
- 기존 환불 상태, 배송 상태, 개봉·이슈·증빙·금액·통화 판단
- SQL 안전검사와 읽기 전용 조회
- Reasoning Verifier를 통한 판정 재검증
- 결정론 및 실제 Provider 실행
- TrialResult, Trace, Provider 비용·지연 기록
- 60개 suite 회귀 평가
- Agent의 Gold·Oracle 접근 차단

### 15.2 현재 범위 밖

- 사용자 자연어만으로 실제 계정과 주문을 자동 식별
- 로그인, 인증, 개인정보 권한 검사
- 실제 쇼핑몰 운영 DB 및 주문 API 연결
- 실제 환불 실행 또는 결제 취소
- 환불 이외 모든 고객센터 업무 처리
- 메인 Agent의 Intent Router와 UI
- 운영 정책 변경 승인 workflow
- 임의 네이티브 코드까지 방어하는 OS 수준 sandbox

따라서 `compact_agent`를 “완성된 고객센터 메인 Agent”라고 부르는 것은 정확하지 않다. “정책 판단과 실행기록 생성을 완성해 둔 축소형 환불 업무 Agent”라고 보는 것이 정확하다.

## 16. 유지보수 시 주의사항

### 16.1 정책 변경

정책 MD만 수정하거나 JSON만 수정하면 안 된다. 다음 항목을 같은 버전으로 갱신해야 한다.

- 정책 원문 MD
- `policy_rules.json`
- 정책 엔진 회귀 테스트
- 필요한 Evidence contract
- 60개 사례 또는 새 사례의 Gold
- asset/version manifest

### 16.2 DB schema 변경

테이블이나 컬럼이 바뀌면 다음 파일을 함께 검토한다.

- ContextProvider allow-list
- DeterministicSQLModel의 5개 query
- `QUERY_REGISTRY`
- EvidenceChecker alias와 PolicyFacts 구조
- 공식 `shop.db` 계약과 개발 회귀 DB

### 16.3 Provider 변경

새 Provider는 공통 `ProviderResult`로 정규화해야 한다. 모델 본문이 주장하는 token 값을 사용하지 말고 실제 HTTP 응답 metadata를 사용해야 한다. structured output schema와 오류·timeout·429 처리도 테스트해야 한다.

### 16.4 공용 계약 변경

메인 프로젝트의 `core/schemas/` 또는 `CONTRACT.md`가 변경되면 `TrialResult`, `TraceStep`, enum을 다시 맞춰야 한다. 특히 필수 필드, `stop_reason`, node role, trial 범위가 달라지는지 확인해야 한다.

### 16.5 평가 보안

Gold 파일을 Agent 프롬프트, AgentRequest, 공개 DB에 복사하지 않는다. 테스트 편의를 위해 예상 decision을 Agent-visible 파일에 넣으면 평가 의미가 사라진다. 공유·제출본은 `scripts/build_submission.py`로 만들어 `evaluation/private/`와 `reports/`를 제외한다.

## 17. 실행 방법

결정론 한 건:

```powershell
python -B run_agent.py run-one --case E-001 --mode deterministic
```

결정론 60건:

```powershell
python -B run_agent.py run-suite --mode deterministic
```

전체 자동 테스트:

```powershell
python -B -m unittest discover -s tests -v
```

실 API 한 건 smoke test:

```powershell
python -B run_agent.py run-suite --mode api --provider gemini --limit 1
python -B run_agent.py run-suite --mode api --provider groq --limit 1
python -B run_agent.py run-suite --mode api --provider openai --limit 1
```

실행 결과는 `reports/runs/<run_id>/` 아래에 저장된다.

## 18. 최종 평가

축소형 Agent는 다음 세 가지 목적에 적합하게 구성되어 있다.

1. 환불 정책 업무를 실제 DB 조회부터 답변까지 끝까지 수행하는 최소 Agent
2. Repair·Verifier·Provider 변경 전후를 비교할 수 있는 재현 가능한 Testbed
3. 메인 Agent가 환불 정책 모듈을 연결할 때 참조할 입력·출력 및 안전 계약

강점은 Core와 Scaffold 분리, 정형 SQL과 이중 SQL Guard, 정책 MD와 기계 정책의 연결, 구조화된 산출물, 실제 Provider adapter, Gold·Oracle 격리다. 특히 실행 성공과 정책 정확도, Gold 일치를 서로 다른 지표로 남기기 때문에 Auditor가 회귀 원인을 분석하기 쉽다.

남은 핵심 과제는 축소형 Agent 내부가 아니라 메인 Agent와 운영 시스템의 경계에 있다. 메인 Agent는 인증된 주문 식별, 환불 외 Intent routing, 실제 환불 API, 사용자 확인 절차를 구현해야 한다. 이 경계를 유지한다면 축소형 Agent의 60개 회귀 suite를 활용해 메인 Agent를 단계적으로 안전하게 개발할 수 있다.

## 부록 A. 주요 코드 진입점

| 목적 | 파일·함수 |
|---|---|
| CLI 실행 | `run_agent.py:main()` |
| 전체 조립 | `policy_runtime/factory.py:build_agent()` |
| 한 사례 실행 | `PolicyAgentGraph.run()` |
| 상태·산출물 | `PolicyAgentState` |
| suite 실행 | `SuiteRunner.run()` |
| 격리 Agent 실행 | `policy_runtime.isolated_worker` |
| Gold 접근 차단 | `agent_execution_guard()` |
| 정책 평가 | `PolicyEngine.evaluate()` |
| 실제 API | `openai_provider.py`, `multi_provider.py` |

## 부록 B. 용어

| 용어 | 의미 |
|---|---|
| Core | 보조 구조 없이 업무를 끝까지 수행하는 최소 경로 |
| Scaffold | Repair, Verifier처럼 Core를 보완하는 구조 |
| Planner | 별도 계획 Agent; 현재 비활성 |
| SQLPlan | SQLGenerator 내부의 구조화된 조회계획 |
| PolicyFacts | DB 조회 결과를 정책 입력으로 정규화한 객체 |
| Gold | 사람이 검증한 비공개 기대 결과 |
| Oracle | 정책 입력으로 기대 결과를 계산하는 평가 구현 |
| TrialResult | 한 번의 실행 요약 |
| TraceStep | 실행 단계 하나의 상세 기록 |
| V0/V1 | 변경 전/후 Agent 버전 label |
| policy correctness | Agent 판정이 독립 정책 기준과 일치하는지 |
| Gold agreement | Agent 판정·조항이 비공개 Gold와 일치하는지 |
| Oracle agreement | 독립 정책 엔진의 상세 결과가 비공개 Gold와 일치하는지 |
