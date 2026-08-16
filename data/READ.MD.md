# Order & Refund 정답 데이터 v0.5

이 디렉터리는 고정된 시험용 데이터베이스와 20개 Gold TestCase를 제공합니다.

## 핵심 파일

- `shop.db`: 평가 시 조회하는 SQLite 데이터베이스입니다. `customers`, `orders`, `products`, `shipments`, `refunds` 다섯 테이블만 포함합니다.
- `test_cases.json`: 질문, 필수 조회 필드, Gold 판정, Gold 조항, 난이도를 포함하는 내부 정답 원장입니다.
- `build_dataset.py`: 동일한 seed와 고정 평가일로 두 핵심 파일을 재생성합니다.
- `version_manifest.json`: 정책·DB·TestCase 버전과 핵심 파일의 SHA-256을 기록합니다.
- `DATA_CHANGELOG.md`: 데이터 변경의 영향 TestCase와 Gold 변경 사유를 기록합니다.

## 평가 격리

평가받는 Agent에는 `shop.db`만 읽기 전용으로 제공합니다. `test_cases.json`, `policy_oracle.py`, 생성 코드와 변경 기록은 Agent의 파일 권한·모듈 경로·네트워크에서 차단해야 합니다. `test_cases.json`에는 정답이 있으므로 Agent 입력으로 전달하면 데이터 누수가 발생합니다.

## 고정 조건

- 정책 버전: `policy-v0.5`
- DB 버전: `db-v0.5`
- TestCase 버전: `testcase-v0.5`
- 평가 기준일: `2026-08-15`
- 시간대: `Asia/Seoul`
- 난이도 분포: Easy 6 / Medium 8 / Hard 6
- 기준 통화: `KRW`

## 재생성과 검증

저장소 루트에서 실행합니다. `policies/policy_oracle.py`가 있으면 이를 사용하고, 단독 검증 환경에서는 루트의 `policy_oracle.py`를 사용합니다.

```bash
python data/build_dataset.py
python -m unittest tests/test_dataset.py -v
```

최종 baseline 승인 전에는 Oracle 구현과 독립적인 사람이 20개 사례를 별도로 검토해야 합니다. 현재 상태는 `CANDIDATE_PENDING_INDEPENDENT_HUMAN_REVIEW`입니다.

## 브랜치 생성

`tester` 브랜치를 기준으로 `feat/dataset`을 만들려면 다음 명령을 사용합니다.

```bash
git checkout -b feat/dataset tester
```

동일한 의미의 최신 명령은 다음과 같습니다.

```bash
git switch tester
git switch -c feat/dataset
```
