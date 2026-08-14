# scaffolds — 채린 담당

SQL Repair Loop와 Reasoning Verifier. 언제 다시 시도하고 언제 멈추는지를 담당합니다.
설정값만 바꿔서 ON/OFF와 횟수를 조절할 수 있어야 합니다.

## 만들 파일
sql_repair.py · reasoning_verifier.py

## 브랜치
git checkout -b feat/repair-loop tester

## 출력 계약
반복마다 `docs/CONTRACT.md`의 TraceStep을 남깁니다.
필수: iteration, node_role, outcome, error_type, latency_ms
모든 종료는 명시적 stop_reason으로 끝나야 합니다 (MAX_RETRY, MAX_REFLECTION 등).

## 주의
- Verifier는 추론 오류만 검사합니다. DB 재조회 금지.
- 무한 루프가 없어야 합니다.
- 이 폴더 밖은 건드리지 마세요.
