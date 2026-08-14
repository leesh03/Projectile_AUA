# data — 우혁 담당

시험용 DB와 TestCase. Agent 성능을 주관적 평가가 아니라 재현 가능한 정답으로 측정하기 위한 자료입니다.

## 만들 파일
shop.db  (customers, orders, products, shipments, refunds 5개 테이블)
test_cases.json  (20개: Easy 6 / Medium 8 / Hard 6)

## 브랜치
git checkout -b feat/dataset tester

## 출력 계약
TestCase에는 질문, required_fields, gold_decision, gold_clauses, difficulty를 포함합니다.
difficulty 필드가 있어야 Auditor가 난이도별 분석을 할 수 있습니다.

## 주의
- `shop.db`는 예외적으로 git에 커밋합니다. 같은 DB에서 같은 결과가 나와야 실험이 재현됩니다.
- 데이터를 바꾸면 영향받는 TestCase 목록과 변경 사유를 함께 남겨주세요.
