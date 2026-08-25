# Order & Refund 정답 데이터 실행 가이드 v0.5

이 문서는 `shop.db`와 `test_cases.json`을 생성·검증·커밋하고, 실제 평가에서 사용하는 순서를 설명합니다.

## 1. 사전 준비

- 저장소 루트에서 명령을 실행합니다.
- Python 3.12 사용을 권장합니다.
- `policies/policy_oracle.py`가 먼저 준비되어 있어야 합니다.
- 원격 저장소에 기준 브랜치 `tester`가 존재해야 합니다.

## 2. 작업 브랜치 생성

원격 정보를 받은 후 `tester`를 최신 상태로 맞추고 `feat/dataset` 브랜치를 만듭니다.

```bash
git fetch origin
git checkout tester
git pull origin tester
git checkout -b feat/dataset
```

다음 한 줄도 같은 의미입니다.

```bash
git checkout -b feat/dataset tester
```

이 명령에서 `feat/dataset`은 새 브랜치 이름이고 `tester`는 새 브랜치의 기준이 되는 기존 브랜치입니다. `tester`가 없으면 명령이 실패합니다.

## 3. 파일 배치

저장소 구조를 다음과 같이 맞춥니다.

```text
policies/
└── policy_oracle.py

data/
├── shop.db
├── test_cases.json
├── build_dataset.py
├── version_manifest.json
├── DATA_CHANGELOG.md
└── README.md

tests/
└── test_dataset.py
```

핵심 산출물은 다음 두 파일입니다.

- `data/shop.db`: 고객·주문·상품·배송·환불의 시험용 원천 데이터
- `data/test_cases.json`: 20개 질문과 Gold 정답·적용 조항·난이도

## 4. 데이터 재생성

저장소 루트에서 다음 명령을 실행합니다.

```bash
python data/build_dataset.py
```

이 명령은 고정된 seed, 평가 기준일, 정책 버전을 사용하여 다음 파일을 다시 생성합니다.

- `data/shop.db`
- `data/test_cases.json`
- `data/version_manifest.json`

생성기는 현재 시각, 난수, 네트워크 또는 LLM 결과를 사용하지 않습니다. 같은 실행 환경과 같은 Oracle 버전에서는 같은 파일이 생성되어야 합니다.

## 5. 자동 검증

다음 명령으로 전체 데이터 검증을 실행합니다.

```bash
python -m unittest tests/test_dataset.py -v
```

정상이라면 8개 테스트가 모두 통과하고 마지막에 `OK`가 표시됩니다. 검증 항목은 다음과 같습니다.

- TestCase 정확히 20개
- Easy 6개, Medium 8개, Hard 6개
- 필수 출력 필드 존재
- SQLite 테이블과 외래키 무결성
- 보호 정답 DB의 20개 레코드와 접근 차단 메타데이터
- Agent 공개 케이스의 Gold 필드 누수 방지
- 명시된 조회 결과 없음 사례를 제외한 참조 ID 존재
- 최신 Oracle 결과와 모든 Gold 정답 일치
- 경계값·정책 예외·중복 환불·값 누락·충돌 우선순위 확인
- 같은 환경에서 재생성한 파일의 SHA-256 일치

## 6. DB 직접 점검

SQLite 명령행 도구가 설치되어 있다면 다음 명령으로 직접 확인합니다.

```bash
sqlite3 data/shop.db ".tables"
sqlite3 data/shop.db "PRAGMA integrity_check;"
sqlite3 data/shop.db "PRAGMA foreign_key_check;"
```

예상 결과는 다음과 같습니다.

- 테이블: `customers`, `orders`, `products`, `shipments`, `refunds`
- 무결성 검사: `ok`
- 외래키 검사: 출력 없음

## 7. TestCase 수와 난이도 확인

```bash
python -c "import json, collections; c=json.load(open('data/test_cases.json')); print(len(c), collections.Counter(x['difficulty'] for x in c))"
```

예상 결과:

```text
20 Counter({'MEDIUM': 8, 'EASY': 6, 'HARD': 6})
```

## 8. 변경 내용 확인

재생성 후 의도하지 않은 파일이 바뀌지 않았는지 확인합니다.

```bash
git status
git diff --stat
```

DB나 TestCase를 변경했다면 `data/DATA_CHANGELOG.md`에 다음 내용을 반드시 기록합니다.

- 변경 사유
- 영향받은 TestCase ID
- Gold 판정 또는 Gold 조항의 변경 내용
- Gold가 바뀐 정책적 근거
- DB 버전 또는 TestCase 버전 변경 여부

## 9. 커밋과 푸시

```bash
git add data tests/test_dataset.py
git commit -m "Add reproducible refund test dataset v0.5"
git push -u origin feat/dataset
```

푸시 후 `feat/dataset`에서 목표 브랜치로 Pull Request를 생성합니다.

## 10. 실제 평가 실행 순서

1. 평가 Harness가 보호된 `test_cases.json`에서 질문과 대상 ID를 읽습니다.
2. Harness는 평가받는 Agent에 질문과 읽기 전용 `shop.db` 접근만 제공합니다.
3. Agent는 `shop.db`를 조회하고 환불 판정과 적용 정책 조항을 제출합니다.
4. Harness는 Agent 결과를 비공개 `gold_decision`, `gold_clauses`와 비교합니다.
5. 전체 정확도와 Easy·Medium·Hard별 정확도를 집계합니다.
6. 동일한 정책·DB·TestCase 버전으로 다시 실행하여 결과 재현 여부를 확인합니다.

## 11. 정답 데이터 접근 제한

`test_cases.json`에는 Gold 정답이 포함되어 있으므로 평가받는 Agent가 직접 읽을 수 없어야 합니다. 다음 항목도 Agent 실행 환경에서 차단합니다.

- `data/test_cases.json`
- `policies/policy_oracle.py`
- 데이터 생성 및 검증 코드
- Git 저장소의 정답 이력

저장소에 파일을 커밋하는 것만으로는 실행 격리가 생기지 않습니다. 평가 Harness 또는 컨테이너 권한에서 접근 제한을 강제해야 합니다.

## 12. 최종 완료 기준

다음 조건을 모두 충족해야 데이터 작업을 완료한 것으로 봅니다.

- `shop.db`에 정확히 다섯 개 원천 테이블이 존재합니다.
- `test_cases.json`에 정확히 20개 사례가 존재합니다.
- 모든 사례에 `question`, `required_fields`, `gold_decision`, `gold_clauses`, `difficulty`가 있습니다.
- 난이도 분포가 Easy 6 / Medium 8 / Hard 6입니다.
- 자동 검증이 모두 통과합니다.
- Oracle 결과와 Gold 정답이 일치합니다.
- 데이터 변경 이력이 기록되어 있습니다.
- 독립된 사람이 정책 문장과 DB 사실만 보고 Gold를 별도로 검토합니다.

독립된 사람의 검토가 끝나기 전에는 baseline 상태를 `CANDIDATE_PENDING_INDEPENDENT_HUMAN_REVIEW`로 유지합니다.
