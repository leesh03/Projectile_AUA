# Order & Refund 60개 데이터셋 실행 가이드 v0.5

이 문서는 pull된 Policy Agent Core와 호환되는 SQL-only regression 데이터셋의
재생성·검증·평가 절차를 설명합니다.

## 1. 구성

```text
data/
├── shop.db                 Agent가 읽는 5-table regression DB
├── agent_cases.json        Agent 공개 입력 60개
├── test_cases.json         PolicyFacts + Gold evaluator 원장
├── answer_key.db           보호된 Gold SQLite 원장
├── build_shop_db.py        PolicyFacts → shop.db 생성기
├── build_dataset.py        전체 산출물 동기화·매니페스트 생성
└── version_manifest.json   버전·분포·SHA-256

policies/
├── refund_policy_spec_v0.5.md
├── policy_rules.json       Agent가 읽는 기계 판독 정책
└── policy_oracle.py        evaluator 전용 독립 Oracle
```

고정 조건:

- TestCase 60개
- Easy / Medium / Hard 각 20개
- 평가 기준일 `2026-08-15`, 시간대 `Asia/Seoul`
- 정책 버전 `policy-v0.5`
- DB 테이블: `customers`, `orders`, `products`, `shipments`, `refunds`

## 2. 재생성

저장소 루트에서 실행합니다.

```bash
python data/build_dataset.py
```

이 명령은 다음 순서로 동작합니다.

1. `answer_key.db`에서 60개 보호 정답과 PolicyFacts를 동기화합니다.
2. 같은 PolicyFacts를 사용해 `shop.db`를 새로 만듭니다.
3. Agent 입력에는 공개 필드 6개만 남깁니다.
4. `data/version_manifest.json`과 `artifacts/version_manifest.json`의 해시를 갱신합니다.

DB만 다시 만들려면 다음 명령을 사용합니다.

```bash
python data/build_shop_db.py
```

생성기는 현재 시각, 난수, 네트워크 또는 LLM을 사용하지 않습니다.

## 3. Regression 조회 계약

- `lookup_order_item_id`: Agent 요청의 `request.order_item_id`와 비교하는 조회 키
- `record_present`: 해당 lookup 행이 실제 PolicyFacts 객체로 materialize되는지 표시
- 동일 lookup 키의 행 수: `lookup_counts`로 변환
- 실제 반환 ID가 lookup 대상과 다르면 참조 불일치 정책 사실로 유지

이 계약으로 결측·중복·count/object 불일치 사례도 별도 testcase fixture 없이
SQL 조회만으로 재현합니다. DB에는 testcase ID나 Gold 판정이 저장되지 않습니다.

## 4. 자동 검증

```bash
python -m pytest tests -q
```

필수 검증 항목:

- 60개 고유 testcase와 20/20/20 난이도 분포
- Agent 입력에서 Gold 필드 제거
- SQLite 무결성과 정확히 5개 테이블
- DB 참조 ID 및 의도된 누락 사례
- `answer_key.db`와 JSON Gold 일치
- 재생성된 DB·JSON의 SHA-256 재현성
- 정책 Oracle의 판정·조항과 Gold 일치
- pull된 Core의 DB 사실·판정·조항·Verifier 60/60 일치

## 5. 평가 격리

Agent에 허용하는 자산:

- `data/shop.db` 읽기
- `data/agent_cases.json`의 개별 입력
- `policies/policy_rules.json`

Agent에서 차단하는 자산:

- `data/test_cases.json`
- `data/answer_key.db`
- `policies/policy_oracle.py`
- 생성기, 평가 결과, Git의 Gold 이력

저장소에 파일이 존재하는 것만으로 격리가 보장되지는 않습니다. 평가 Harness의
프로세스·파일 권한에서 접근 차단을 강제해야 합니다.

## 6. 변경 절차

데이터 또는 정책을 바꿀 때는 다음 순서를 유지합니다.

1. 정책 명세와 `policy_rules.json` 변경
2. 독립 Oracle 변경 및 조항 단위 검토
3. `answer_key.db`와 `test_cases.json` 동기화
4. `python data/build_dataset.py`
5. 전체 테스트와 60-case 통합 실행
6. `git diff --stat`과 매니페스트 해시 확인

독립 검토가 끝나기 전에는 baseline 상태를
`CANDIDATE_PENDING_INDEPENDENT_HUMAN_REVIEW`로 유지합니다.
