# Policy Agent Core (`nodes`) — 이준원 담당

주문·환불 질문을 읽고 SQLite에서 필요한 사실을 조회한 뒤, 정책에 따라 판정하고 사용자 응답과 감사용 실행 기록을 만드는 Core입니다. Repair·Verifier 같은 Scaffold를 끈 상태에서도 처음부터 끝까지 실행됩니다.

## 실행 순서

```text
AgentRequest
  → context_provider
  → sql_generator
  → sql_executor (SQL Guard 포함)
  → evidence_check
  → policy_reasoner
  → response_writer
  → AgentRun / TrialResult / TraceStep
```

전체 순서는 `graph.py`가 제어합니다. 기본 설정은 Repair 비활성화, Verifier 비활성화, 재시도 0회입니다.

## 파일 설명

| 파일 | 역할 |
|---|---|
| `__init__.py` | 외부에서 사용할 Core 객체를 한곳에 공개합니다. |
| `graph.py` | 각 단계를 순서대로 실행하고 오류·중단 사유·Trace를 기록합니다. |
| `state.py` | 입력, 실행 설정, 상태, 모델 사용량, `TrialResult`·`TraceStep` 변환과 결과 파일 저장을 담당합니다. |
| `context_provider.py` | SQLite 스키마와 정책 파일을 읽기 전용으로 불러오고 파일 해시·정책 버전을 기록합니다. |
| `sql_generator.py` | 모델의 구조화 출력을 검증해 이름이 지정된 SELECT 조회 계획으로 변환합니다. |
| `sql_executor.py` | SELECT-only, 단일 문장, 금지 명령, 허용 테이블을 검사한 뒤 SQLite를 읽기 전용으로 실행합니다. |
| `evidence_check.py` | SQL 결과를 정책 판정용 사실 구조로 조립하고 필수 근거가 있는지 확인합니다. |
| `policy_reasoner.py` | DB 사실과 정책을 모델에 전달하고 `APPROVE`, `REJECT`, `NEED_MORE_INFO`, `NOT_APPLICABLE` 중 하나의 구조화 판정을 검증합니다. |
| `response_writer.py` | 최종 판정·근거 또는 실패 사유를 사용자에게 보여 줄 문장으로 작성합니다. |

## 주요 입출력

- 입력: `AgentRequest(testcase_id, difficulty, question, request, target_ids, trusted_context)`
- 실행: `PolicyAgentGraph.run(request, agent_label="V0" 또는 "V1", trial=1~3)`
- 반환: `AgentRun`이며 실제 결과는 `run.state`에서 확인합니다.
- 사용자 답변: `run.state.response`
- 감사용 결과: `run.state.trial_result_dict(policy_correct=...)`
- 단계별 기록: `run.traces`
- 파일 저장: `run.state.write_trial_artifact(...)`

저장되는 `TrialResult`와 `TraceStep`은 `docs/CONTRACT.md`의 schema v1 필드에 맞춥니다. `policy_correct`는 Agent가 스스로 정하지 않고 독립 평가 결과를 호출자가 전달해야 합니다.

## 실행에 필요한 연결

- SQLite DB 경로와 읽기를 허용할 테이블 목록
- 비어 있지 않은 정책 파일 경로
- SQL 생성 모델 어댑터와 정책 판정 모델 어댑터
- 선택 사항: 채린님의 SQL Repair 및 Reasoning Verifier 어댑터

특정 API SDK나 모델 ID는 Core에 고정하지 않았습니다. 실제 API 어댑터는 모델의 구조화 결과와 함께 응답 메타데이터에서 얻은 토큰 사용량을 `ProviderResult`로 전달해야 합니다.

## 안전 장치

- 사용자 질문과 신뢰 가능한 구조화 입력을 분리합니다.
- SQL은 코드로 검사하며 쓰기 명령, 여러 문장, 주석, 미허용 테이블 접근을 차단합니다.
- SQLite를 읽기 전용으로 열고 행 수·실행 단계·실행 시간 제한을 적용합니다.
- 정책 조항이 요구하는 근거가 없으면 임의 판정하지 않고 `INSUFFICIENT_EVIDENCE`로 중단합니다.
- `.env`, API 키, DB 원본, 정책 원본은 이 폴더에 저장하지 않습니다.

## 테스트

저장소 최상위에서 실행합니다.

```bash
uv run python -m unittest tests.testbed.test_core_graph -v
```

정상 실행뿐 아니라 위험 SQL 차단, 허용되지 않은 테이블 접근, 근거 부족, 잘못된 모델 출력, 토큰 집계, Repair 설정과 실행 기록 저장을 검증합니다.

## 팀 규칙

- 담당 구현 범위는 `agents/policy_agent/nodes/`입니다.
- 공용 스키마인 `core/schemas/`는 직접 수정하지 않습니다.
- 실제 정책·DB 형식 또는 Repair·Verifier 인터페이스가 바뀌면 담당자와 합의한 뒤 어댑터 경계에서 반영합니다.
- `main`에는 직접 push하지 않고 이 브랜치에서 검증한 뒤 PR로 `tester`에 합칩니다.
