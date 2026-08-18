# Order & Refund Testbed 데이터 v0.5

이 디렉터리는 Order & Refund Policy Agent를 재현 가능하게 평가하기 위한
SQLite 데이터베이스와 20개 Gold TestCase를 관리합니다. Gold 판정은 Agent의
이전 답변이 아니라 `policies/policy_oracle.py`의 결정론적 결과를 사용합니다.

## 파일 구조

| 파일 | 용도 | 평가 Agent 접근 |
| --- | --- | --- |
| `shop.db` | customers, orders, products, shipments, refunds 5개 테이블 | 읽기 허용 |
| `agent_cases.json` | 질문, 대상 ID, 요청 및 신뢰된 실행 문맥 | 읽기 허용 |
| `test_cases.json` | PolicyFacts, Gold 판정·조항·필수 필드가 포함된 내부 원장 | 차단 |
| `answer_key.db` | `test_cases.json`의 보호된 SQLite 정답 원장 | 차단 |
| `version_manifest.json` | 핵심 Base 데이터의 버전과 SHA-256 | 차단 |
| `DATA_CHANGELOG.md` | 정책·DB·Gold 변경 내역과 영향 범위 | 차단 |
| `build_dataset.py` | Base 데이터 재생성기 | 차단 |
| `build_answer_data.py` | Agent/정답 분리 산출물 재생성기 | 차단 |

`answer_key.db`, `test_cases.json`, Oracle과 생성 코드는 평가 Agent의 파일 권한,
모듈 경로 및 네트워크에서 차단해야 합니다. 공개 저장소에 파일이 존재하는 것만으로
실행 격리가 보장되지는 않으므로 Testbed 실행기가 이 경계를 강제해야 합니다.

## 고정 조건

- 정책 버전: `policy-v0.5`
- DB 버전: `db-v0.5`
- TestCase 버전: `testcase-v0.5`
- 평가 기준일: `2026-08-15`
- 시간대: `Asia/Seoul`
- 난이도: Easy 6 / Medium 8 / Hard 6
- 통화: `KRW`

## 재생성과 검증

저장소 루트에서 실행합니다.

```bash
python data/build_answer_data.py
python -m unittest tests/test_dataset.py -v
```

Base 산출물만 재생성할 때는 `python data/build_dataset.py`를 사용합니다. 전체
배포용 SHA-256은 `artifacts/version_manifest.json`에 기록됩니다.

최종 baseline 승인 전에는 Oracle 구현과 독립적인 사람이 20개 사례를 검토해야
합니다. 현재 상태는 `CANDIDATE_PENDING_INDEPENDENT_HUMAN_REVIEW`입니다.
