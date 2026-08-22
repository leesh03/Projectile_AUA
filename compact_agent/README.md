# 축소형 환불 정책 Agent — 메인 Agent 인수인계본

이 폴더 하나로 축소형 Agent의 구조, 실행 코드, 정책, 테스트 데이터, 입출력 계약과 평가 방법을 확인할 수 있다. 이준원의 Core 노드, 유채린의 SQL Repair·Reasoning Verifier, 정책 MD를 기반으로 정리한 정책 엔진을 통합한 로컬 실행본이다.

실제 API 키와 과거 실행 결과는 포함하지 않았다. Python 3.11 이상만 있으면 결정론 모드는 별도 패키지 설치 없이 실행할 수 있다.

## 1. 빠른 확인

PowerShell에서 이 폴더로 이동한 뒤 실행한다.

```powershell
python -B -m unittest discover -s tests -v
python -B run_agent.py run-one --case E-001 --mode deterministic
python -B run_agent.py run-suite --mode deterministic
```

API 모드는 `.env.example`을 `.env`로 복사해 키를 입력한 다음 실행한다. `.env`는 공유하거나 Git에 올리지 않는다.

```powershell
python -B run_agent.py run-suite --mode api --provider gemini --limit 1
python -B run_agent.py run-suite --mode api --provider groq --limit 1
python -B run_agent.py run-suite --mode api --provider openai --limit 1
```

## 2. 전체 구조

```text
사용자 질문 + 구조화된 주문 식별자
        │
        ▼
ContextProvider ── DB 스키마·공개 정책 로드
        │
        ▼
SQLGenerator ───── 내부 SQLPlan으로 정형 쿼리 5개 생성
        │             별도 Planner는 사용하지 않음
        ▼
SQLExecutor ─────── SELECT 전용 검사 후 shop.db 조회
        │
        ▼
EvidenceChecker ─── 조회값을 PolicyFacts로 정규화
        │
        ▼
PolicyReasoner ───── policy_rules.json과 비교해 판정·조항 생성
        │
        ▼
ReasoningVerifier ── 판정과 근거가 정책에 맞는지 재검증
        │
        ▼
ResponseWriter ───── 사용자 응답 생성
        │
        ▼
AgentOutput + Trace + TrialResult
```

테스트 실행에서는 `SuiteRunner`가 부모 평가 프로세스로 동작하고, 실제 Agent는 `isolated_worker` 자식 프로세스에서 실행된다. Agent는 `evaluation/private`의 Gold를 읽을 수 없고 실행이 끝난 뒤 Runner만 결과를 비교한다.

## 3. 폴더 설명

```text
compact_agent/
├─ run_agent.py                    실행 CLI
├─ agents/policy_agent/
│  ├─ nodes/                       Core 상태·그래프·SQL·정책판단·응답
│  └─ scaffolds/                   SQL Repair·Reasoning Verifier·설정
├─ core/schemas/                   TraceStep 공용 출력 계약
├─ policy_runtime/
│  ├─ factory.py                   전체 Agent 조립 지점
│  ├─ runner.py                    사례 실행·TrialResult 저장·평가
│  ├─ isolated_worker.py           Gold와 분리된 Agent 프로세스
│  ├─ access_guard.py              Gold/Oracle 접근 차단
│  ├─ engine.py                    정책 규칙 실행
│  └─ *_provider.py                OpenAI·Gemini·Groq 어댑터
├─ policies/
│  ├─ source/*.md                  사람이 읽는 정책 원문
│  └─ policy_rules.json            Agent가 읽는 기계 정책
├─ data/
│  ├─ shop.db                      주문·상품·배송·환불 테스트 DB
│  ├─ agent_cases.json             Agent에 전달되는 60개 입력
│  └─ adapter_fixtures.json        특수 입력 정규화용 fixture
├─ evaluation/private/             Runner 전용 Gold — Agent 접근 금지
├─ tests/                          단위·통합·격리 테스트
├─ examples/                       한 건의 입출력 예시
├─ docs/                           상세 구조·검증·인수인계 문서
└─ PACKAGE_MANIFEST.json           포함 파일 SHA-256 목록
```

## 4. 입출력 핵심

입력은 `AgentRequest`이며 다음 여섯 필드만 받는다.

- `testcase_id`, `difficulty`, `question`
- `request`: 요청액, 통화, `order_item_id`, 환불 요청 ID
- `target_ids`: 고객·주문·상품·배송 식별자
- `trusted_context`: 기준일과 `Asia/Seoul` 시간대

Gold나 예상 정답 필드는 입력에 넣을 수 없다. 실제 예시는 `examples/agent_request.json`에 있다.

최종 산출물은 다음 세 묶음이다.

- `agent_output`: `decision`, `clauses`, `rationale`, `response`, Verifier 결과
- `trial_result`: 성공 여부, 정책 일치, 오류·재시도·토큰·지연·Scaffold 설정
- `traces`: 각 노드의 역할, 실행 유형, 성공 여부와 비용

정확한 필드 예시는 `examples/agent_output.json`, `examples/trial_artifact.json`과 `docs/ARCHITECTURE_AND_IO.md`를 참고한다.

## 5. 메인 Agent에 연결하는 방법

1. 메인 Agent의 로그인 세션이나 주문 선택 UI에서 `order_item_id`를 확정한다.
2. 사용자 자연어와 주문 컨텍스트를 `AgentRequest` 형식으로 변환한다.
3. `policy_runtime.factory.build_agent()`로 그래프를 조립해 정책 Agent를 하위 기능으로 호출한다.
4. `agent_output.response`는 사용자 답변으로, 판정·조항·trace는 메인 Agent 상태 및 감사 로그로 전달한다.
5. 개발 중에는 기존 60개 사례를 `SuiteRunner`로 실행하고 Gold와 비교한다. 메인 Agent 코드에서 Gold 파일을 import하거나 읽지 않는다.

현재 축소형 Agent는 환불 정책 판단 부분을 담당한다. 주문 ID가 없는 자연어에서 실제 주문을 찾는 인증·세션·주문 선택 기능과 환불 실행 API는 메인 Agent가 연결해야 한다.

## 6. 현재 기준

- Planner: `False` — `SQLGenerator` 내부의 `SQLPlan` 사용
- SQL Repair: API 모드에서 최대 2회
- Reasoning Verifier: 활성화, 최대 재추론 2회
- 정책: `policy-v0.5`, 47개 조항
- 평가: 60개 사례
- Provider: OpenAI, Gemini, Groq
- 격리: `subprocess-audit-v1`

통합 결과는 `docs/INTEGRATION_REPORT.md`, 원래 프로젝트 설명은 `docs/ORIGINAL_PROJECT_README.md`에 보존했다.
