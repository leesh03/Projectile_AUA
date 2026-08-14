# nodes — 준원 담당

질문 → SQL → 정책 → 응답으로 이어지는 Core 질의 처리 경로.
Scaffold를 전부 꺼도 여기만으로 업무가 끝까지 실행되어야 합니다.

## 만들 파일
state.py · graph.py · context_provider.py · sql_generator.py
sql_executor.py · evidence_check.py · policy_reasoner.py · response_writer.py

## 브랜치
git checkout -b feat/core-graph tester

## 출력 계약
실행 결과는 `docs/CONTRACT.md`의 TrialResult 형식으로 저장합니다.
필수: testcase_id, agent_label, task_success, policy_correct,
      tool_error_count, retry_count, total_tokens, latency_ms,
      safety_violation, stop_reason

## 주의
- SQL Guard(SELECT-only, 금지 명령, 허용 테이블 검사)는 반드시 코드로 구현합니다. LLM에 맡기지 않습니다.
- 이 폴더 밖은 건드리지 마세요. `core/schemas/` 수정이 필요하면 소현에게 요청하세요.
