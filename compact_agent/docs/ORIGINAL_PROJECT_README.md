# AI_Agent 로컬 통합본

이 폴더는 최신 이준원 Core, 유채린 SQL Repair/Reasoning Verifier, 정책 원문 `refund_policy_spec_v0.5.md`를 로컬에서 통합한 환불 정책 Agent다. 팀 브랜치나 원본 워크트리는 수정하지 않는다.

## 현재 실행 구조

1. `ContextProvider`가 읽기 전용 SQLite 스키마와 기계 정책을 로드한다.
2. `SQLGenerator`가 검증된 5개 정형 조회 계획을 만든다. 별도 Planner는 사용하지 않는다(`planner=false`).
3. `SQLExecutor`가 SELECT 전용 가드와 SQLite authorizer를 거쳐 조회한다.
4. `EvidenceChecker`가 조회 결과를 정규 `PolicyFacts`로 조립한다.
5. `PolicyReasoner`가 47개 정책 조항과 전역 우선순위를 적용한다.
6. 유채린의 `verify_once`가 판정·조항·근거를 재검증한다.
7. `ResponseWriter`가 사용자 답변을 만들고 Runner가 `TrialResult`, trace, provider 사용량을 저장한다.

`_state_stub.py`는 사용하지 않는다. 유채린 Scaffold는 이준원의 실제 `PolicyAgentState`와 어댑터로 연결되어 있다.

## 로컬 실행

이 폴더에서 실행한다.

```powershell
python run_agent.py run-one --case E-001 --mode deterministic
python run_agent.py run-suite --mode deterministic
python -m unittest discover -s tests -v
```

산출물은 `reports/runs/<run_id>/` 아래에 저장된다. `suite_summary.json`, 실행 manifest, 사례별 `trial_1.json`이 생성된다.

공유본은 `python scripts/build_submission.py`로 만든다. 이 ZIP에는 `evaluation/private/`, `reports/`, `.env`가 들어가지 않는다.

## Gold·Oracle 격리

`SuiteRunner`는 평가 자료를 읽는 부모 프로세스와 Agent를 실행하는 자식 프로세스를 분리한다. Agent 자식 프로세스에는 Python audit 기반 deny policy가 적용된다.

- 허용: `data/shop.db`, `data/agent_cases.json`, `policies/policy_rules.json`
- 차단: `evaluation/private/`, `expected_cases.json`, `answer_key.db`, `test_cases.json`, `policy_oracle.py`, 정책 비교 원본 폴더
- 우회 차단: Agent 실행 중 `subprocess`·`os.system` 등 하위 프로세스 실행

Agent가 실행을 끝낸 뒤 부모 Runner만 반환된 facts를 정책 엔진·Gold와 비교한다. `engine_consistency`는 Agent-엔진, `gold_agreement`는 Agent-Gold, `oracle_agreement`는 엔진-Gold 일치다. Manifest와 summary에는 `isolation=subprocess-audit-v1`이 남는다. 네이티브 플러그인처럼 신뢰하지 않는 임의 실행 코드를 추가할 경우에는 이 경계에 더해 별도 OS 계정이나 컨테이너 ACL을 사용해야 한다.

## API 키를 받은 뒤

`.env.example`을 `.env`로 복사하고 사용할 Provider 키를 넣는다. 키는 Git에 올리거나 결과 파일에 기록하지 않는다. `--provider`는 `openai`, `gemini`, `groq` 중 하나다.

```text
OPENAI_API_KEY=...
GEMINI_API_KEY=...
GROQ_API_KEY=...
```

먼저 1건을 확인하고 전체 60건을 실행한다.

```powershell
python run_agent.py run-suite --mode api --provider gemini --limit 1
python run_agent.py run-suite --mode api --provider groq --limit 1
python run_agent.py run-suite --mode api --provider gemini
```

기본 모델은 OpenAI `gpt-5.2`, Gemini `gemini-3.6-flash`, Groq `openai/gpt-oss-120b`이며 각 Provider의 `*_MODEL` 환경변수 또는 `--model`로 바꿀 수 있다. 고정 DB 스키마의 SQLPlan은 API 모드에서도 정형 쿼리를 사용하고, API 모델은 정책 판정과 Verifier를 담당한다. SQL Repair 최대 2회, Reasoning Verifier 재추론 최대 2회가 활성화된다. HTTP 요청·구조화 JSON·응답/토큰 파싱은 Provider별 단위 테스트로 검증한다.

## 범위

현재 프로젝트 테스트 입력처럼 `order_item_id`, 요청액, 통화, 평가일이 구조화되어 들어오면 주문·배송·환불 이력과 정책을 비교해 승인, 거절, 추가 정보 요청, 취소 흐름, 기존 환불 대기, 수동 검토 경로를 판단한다. 실제 서비스에서 사용자가 주문 식별자 없이 자연어만 말하는 경우에는 로그인 세션/주문 선택 UI에서 `order_item_id`를 연결하는 별도 입력 어댑터가 필요하다.

자세한 검증 결과와 GitHub 기준 commit은 `INTEGRATION_REPORT.md`에 기록했다.
