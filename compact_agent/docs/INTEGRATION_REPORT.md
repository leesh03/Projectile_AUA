# AI_Agent 로컬 통합 결과

작성일: 2026-08-19 (Asia/Seoul)

## 결론

API 키 없이 실행 가능한 결정론 모드에서 최신 60개 사례가 모두 최종 산출물까지 생성되었다.

- Core 실행 성공: 180/180 (60개 사례 × 3 trials)
- 로컬 정책 엔진과 Agent 판정 일치: 180/180
- 독립 평가 기대 결과 일치: 180/180
- Reasoning Verifier 통과: 180/180
- 정책 원문 기반 47개 조항 단위 검증: 60/60
- 단위·통합 테스트: 10/10
- Python 전체 컴파일: 통과

검증 산출물: `reports/runs/20260819T061249Z_3db2f2ec/suite_summary.json`

## 사용한 최신 GitHub 기준

| 담당 | 브랜치 | 확인한 commit | 로컬 반영 |
|---|---|---|---|
| 이준원 | `feat/core-graph` | `c958f8920e7c49c2d89c7e7de158d086d2957ae4` | Core nodes, 상태/trace/TrialResult, SQL 가드 |
| 유채린 | `feat/repair-loop` | `b018b2d3a1e778c5415622fcb33345755ba06d82` | 실제 `reasoning_verifier.py`, `sql_repair.py`, config/trace/LLM 경계 |
| 정우혁 데이터 기준 | `feat/dataset` | `07b81245038607f7db0621f080e226da7c4ed0f9` | 60개 Agent 입력과 평가용 PolicyFacts만 분리 반영 |

정우혁 브랜치의 정책 실행 코드는 복사하지 않았다. 정책 원문 `refund_policy_spec_v0.5.md`를 기준으로 `policies/policy_rules.json`, `policy_runtime/loader.py`, `policy_runtime/engine.py`를 새로 작성했다.

## 통합 시 적용한 결정

### Planner

별도 Planner는 비활성화했다. 이준원의 `SQLGenerator`가 이미 `SQLPlan`을 생성하므로 현재 설정은 `planner=false`다. 유채린 config도 같은 값으로 고정했다.

### Verifier와 State

유채린의 `verify_once`를 이준원의 실제 `PolicyAgentState`에 `ReasoningVerifierAdapter`로 연결했다. 테스트용 `_state_stub.py`는 복사하거나 import하지 않았다. 따라서 Verifier 결과, reflection 횟수, trace, 토큰 정보가 같은 실행 상태와 `TrialResult`에 기록된다.

### SQL Repair

유채린의 `repair_once`는 `SQLRepairAdapter`로 Core의 실패 SQL·오류·스키마·질문을 받도록 연결했다. 결정론 SQL은 처음부터 유효하므로 결정론 전체 실행에서는 호출하지 않는다. API 모드에서는 최대 2회 활성화된다. 별도 통합 테스트에서 잘못된 SQL 1건이 1회 호출로 SELECT 문으로 교체되고 파라미터가 보존되는 것을 확인했다.

### 정책과 데이터 경계

정책은 47개 조항, 숫자 우선순위, 종결 결과 tuple, 해제되는 제한 조항, `required_fields`를 기계 검증한다. Agent 런타임은 평가 정답을 읽지 않는다.

최신 upstream `shop.db`는 다수의 MEDIUM/HARD 사례에 기본 정상 행이 들어 있었고, CHECK/UNIQUE 제약 때문에 미등록 상태·잘못된 통화·중복 배송 같은 정책 오류 사례를 표현할 수 없었다. 그대로 실행하면 기대 결과 일치가 18/60이었다. 로컬에서는 다음처럼 분리했다.

- `data/shop.db`: 기대 판정 없이 `PolicyFacts` 입력만 사용해 5개 테이블을 재생성
- `data/adapter_fixtures.json`: compact DB로 표현할 수 없는 9건의 사실만 저장, 정답/Gold 없음
- `evaluation/private/expected_cases.json`: Runner가 Agent 실행을 끝낸 뒤에만 사용하는 독립 평가 자료
- `data/asset_manifest.json`: 소스 commit과 모든 로컬 자산 SHA-256 기록

이 분리 후 실제 SQL 조회 → 사실 조립 → 정책 판정 → Verifier → 응답 → TrialResult 저장 전 구간이 60/60 일치했다.

## API 및 평가 격리 검증

OpenAI Responses, Gemini `generateContent`, Groq Chat Completions를 외부 SDK 없이 지원한다. 키는 환경 변수 또는 Git에서 제외되는 `.env`에서만 읽으며 코드·산출물에 저장하지 않는다. 고정 DB의 SQLPlan은 정형 SELECT를 사용하고 API 모델은 정책 판정과 Verifier를 담당한다.

2026-08-22 검증 결과:

- 단위·통합 테스트 18/18 통과
- 격리된 결정론 전체 suite 60/60 task success, policy correct, Gold agreement
- Gemini `gemini-3.6-flash`: E-001 전체 흐름 성공, Gold 일치, Verifier PASS
- Groq `openai/gpt-oss-120b`: E-001 전체 흐름 성공, Gold 일치, Verifier PASS
- Gemini/Groq 응답 ID, 모델명, 토큰, latency, Verifier Provider 기록 확인
- 실제 API 키가 코드·설정·산출물에 저장되지 않음을 검색으로 확인

평가 Runner는 부모 프로세스에서 Gold를 읽고 Agent는 별도 자식 프로세스에서 실행한다. 자식의 audit deny policy는 `evaluation/private`, `expected_cases.json`, `answer_key.db`, `test_cases.json`, `policy_oracle.py`, 정책 비교 원본과 하위 프로세스 실행을 차단한다. Agent 공개 DB·정책 접근, 금지 파일 4종 차단, 우회 프로세스 차단, Guard 종료 뒤 평가자 Gold 접근을 자동 테스트했다. Manifest에는 `isolation=subprocess-audit-v1`이 기록된다.

## 남은 범위

- 정책 파일이 업데이트되면 `policy_rules.json`과 정책 회귀 테스트를 같은 version으로 갱신해야 한다.
- 실제 API 결과는 모델 출력의 변동과 호출 비용이 있으므로 Provider별 1건은 완료했고, 필요 시 60건 API suite를 추가 실행한다.
- 일반 사용자 대화에서 주문 식별자가 없으면 세션/주문 선택 화면이 `order_item_id`를 제공해야 한다. 현재 60개 프로젝트 사례는 이 구조화 입력을 이미 포함한다.

모든 변경은 `AI_Agent` 로컬 폴더에만 만들었고, 팀원의 GitHub 브랜치에는 commit/push하지 않았다.
