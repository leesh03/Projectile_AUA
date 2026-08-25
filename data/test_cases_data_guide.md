# Order & Refund Testbed — `test_cases.json` 전체 커버리지 데이터 가이드

> **정책 버전:** `policy-v0.5`  
> **DB 버전:** `shop-v0.5-full-coverage`  
> **TestCase 버전:** `testcases-v0.5-full-coverage`

## 1. 데이터셋 기준

- 총 60개: Easy 20 / Medium 20 / Hard 20
- 47개 등록 정책 조항이 모두 `matched_clauses`에 최소 1회 등장
- 최종 결과를 만들 수 있는 terminal clause 43개가 모두 `primary_clause`로 최소 1회 등장
- Gold는 `PolicyFacts → policy_oracle.decide()`로만 생성
- 실제 Agent 입력에는 Gold 필드를 전달하지 않음

## 2. 발행 완료 조건

```text
TestCase 60개
Easy / Medium / Hard = 20 / 20 / 20
matched clause coverage = 47 / 47
terminal primary coverage = 43 / 43
primary_clause ∈ matched_clauses
overridden_clauses ⊆ matched_clauses
Gold 수동 작성 금지
같은 PolicyFacts 재실행 결과 동일
```

## 3. Agent 실행 파일과 평가 파일

- `test_cases.json`: Agent 입력 + PolicyFacts + Oracle Gold 전체
- `agent_cases.json`: Agent에게 줄 입력만 포함
- `version_manifest.json`: 분포, 버전, 핵심 산출물 SHA-256
- `answer_key.db`: 보호된 60개 Gold 원장
- `shop.db`: 60개 PolicyFacts를 SQL만으로 재현하는 regression DB

Agent에는 `policy_facts`, `expected_result`, `gold_decision`, `gold_clauses`, `required_fields`를 전달하지 않습니다.
표의 `SHOP_DB_PLUS_ADAPTER_FIXTURE`는 최초 설계 당시의 출처 분류를 보존한 값입니다.
현재 런타임에는 testcase-aware Adapter fixture가 없으며, 해당 9개 사례도
`lookup_order_item_id`와 `record_present`를 사용하는 `shop.db` 행으로 표현됩니다.

## 4. 난이도별 60개 목록

### EASY 20

| ID | fact source | Gold | primary | 설명 |
|---|---|---|---|---|
| `E-001` | `SHOP_DB` | `APPROVE` | `POL-00.08` | STANDARD 회원의 배송 완료 당일(day 0) 정상 승인 |
| `E-002` | `SHOP_DB_PLUS_ADAPTER_FIXTURE` | `NEED_MORE_INFO` | `POL-10.02` | 주문은 존재하지만 Adapter의 고객 스냅샷 조회가 0건인 사례 |
| `E-003` | `SHOP_DB` | `APPROVE` | `POL-00.08` | STANDARD 환불 가능 포함 경계인 day 14 |
| `E-004` | `SHOP_DB_PLUS_ADAPTER_FIXTURE` | `NEED_MORE_INFO` | `POL-10.03` | 주문은 존재하지만 Adapter의 상품 스냅샷 조회가 0건인 사례 |
| `E-005` | `SHOP_DB_PLUS_ADAPTER_FIXTURE` | `NEED_MORE_INFO` | `POL-10.09` | Adapter가 같은 주문 상품의 주문 결과를 2건으로 보고한 non-unique order 사례 |
| `E-006` | `SHOP_DB` | `APPROVE` | `POL-00.08` | PREMIUM 환불 가능 포함 경계인 day 30 |
| `E-007` | `SHOP_DB` | `APPROVE` | `POL-00.08` | 미개봉 전자제품 정상 승인 |
| `E-008` | `SHOP_DB_PLUS_ADAPTER_FIXTURE` | `NEED_MORE_INFO` | `POL-10.10` | Adapter가 고객 스냅샷을 2건으로 보고한 non-unique customer 사례 |
| `E-009` | `SHOP_DB_PLUS_ADAPTER_FIXTURE` | `NEED_MORE_INFO` | `POL-10.11` | Adapter가 상품 스냅샷을 2건으로 보고한 non-unique product 사례 |
| `E-010` | `SHOP_DB_PLUS_ADAPTER_FIXTURE` | `NEED_MORE_INFO` | `POL-10.14` | lookup count는 1인데 customer_snapshot 객체가 없는 Adapter count-object 불일치 |
| `E-011` | `SHOP_DB_PLUS_ADAPTER_FIXTURE` | `NEED_MORE_INFO` | `POL-10.15` | order.customer_id와 customer_snapshot.customer_id가 다른 참조키 불일치 |
| `E-012` | `SHOP_DB` | `APPROVE` | `POL-00.08` | requested_amount=NULL을 전액 요청으로 해석하고 순결제액 25,000원을 기준으로 판단 |
| `E-013` | `SHOP_DB` | `APPROVE` | `POL-00.08` | 기존 REJECTED 이력이 있어도 새 request id이면 일반 정책 계속 평가 |
| `E-014` | `SHOP_DB` | `NEED_MORE_INFO` | `POL-50.04` | 순결제액과 요청액이 0원인 잘못된 환불 금액 데이터 |
| `E-015` | `SHOP_DB` | `APPROVE` | `POL-00.08` | 현재 회원 등급이 아니라 주문 당시 STANDARD snapshot을 사용 |
| `E-016` | `SHOP_DB` | `APPROVE` | `POL-00.08` | 현재 STANDARD라도 주문 당시 PREMIUM snapshot을 유지 |
| `E-017` | `SHOP_DB` | `NEED_MORE_INFO` | `POL-50.03` | 환불 이력 status가 정책에 등록되지 않은 UNKNOWN 값 |
| `E-018` | `SHOP_DB_PLUS_ADAPTER_FIXTURE` | `NEED_MORE_INFO` | `POL-10.16` | order/customer/product의 snapshot ID가 서로 다른 참조 불일치 |
| `E-019` | `SHOP_DB` | `APPROVE` | `POL-00.08` | DAMAGED 증빙이 REJECTED이면 회사 귀책 override 없이 일반 정책을 적용 |
| `E-020` | `SHOP_DB_PLUS_ADAPTER_FIXTURE` | `NEED_MORE_INFO` | `POL-30.05` | 주문 당시 product.final_sale 값이 확인되지 않은 상태 |

### MEDIUM 20

| ID | fact source | Gold | primary | 설명 |
|---|---|---|---|---|
| `M-001` | `SHOP_DB` | `REJECT` | `POL-20.06` | STANDARD day 15로 환불 기간 초과 |
| `M-002` | `SHOP_DB` | `REJECT` | `POL-20.06` | PREMIUM day 31로 환불 기간 초과 |
| `M-003` | `SHOP_DB` | `REJECT` | `POL-30.01` | Final Sale 상품 제한 |
| `M-004` | `SHOP_DB` | `REJECT` | `POL-30.02` | 개봉된 전자제품 일반 환불 제한 |
| `M-005` | `SHOP_DB` | `REJECT` | `POL-50.01` | 기존 COMPLETED 환불로 중복 환불 금지 |
| `M-006` | `SHOP_DB` | `NEED_MORE_INFO` | `POL-10.07` | order_status가 정책에 등록되지 않은 UNKNOWN 값 |
| `M-007` | `SHOP_DB` | `NOT_APPLICABLE` | `POL-50.02` | 기존 REQUESTED 환불이 진행 중이므로 기존 요청 대기 |
| `M-008` | `SHOP_DB` | `NEED_MORE_INFO` | `POL-40.02` | WRONG_ITEM 증빙이 PENDING이라 Evidence Service 확인 필요 |
| `M-009` | `SHOP_DB` | `NEED_MORE_INFO` | `POL-30.04` | 전자제품인데 package_opened가 NULL이라 개봉 상태 확인 필요 |
| `M-010` | `SHOP_DB` | `NEED_MORE_INFO` | `POL-10.13` | shipment 행은 있지만 delivered_at이 NULL이라 배송 완료일 확인 필요 |
| `M-011` | `SHOP_DB` | `NEED_MORE_INFO` | `POL-10.01` | 대상 order_item 주문 행 자체가 없음 |
| `M-012` | `SHOP_DB` | `NEED_MORE_INFO` | `POL-10.04` | 주문은 있으나 shipment 행이 없음 |
| `M-013` | `SHOP_DB` | `NOT_APPLICABLE` | `POL-10.06` | 이미 CANCELLED된 주문은 새 환불 정책 대상이 아님 |
| `M-014` | `SHOP_DB` | `NOT_APPLICABLE` | `POL-10.05` | PAID 상태는 환불 판단이 아니라 취소 흐름으로 라우팅 |
| `M-015` | `SHOP_DB` | `NEED_MORE_INFO` | `POL-10.08` | order_status=SHIPPED인데 delivered_at이 존재하는 주문-배송 상태 모순 |
| `M-016` | `SHOP_DB` | `NEED_MORE_INFO` | `POL-50.08` | 주문과 요청 통화가 모두 USD여서 비지원 통화 |
| `M-017` | `SHOP_DB` | `NOT_APPLICABLE` | `POL-50.06` | 순결제액 20,000원보다 작은 10,000원 요청은 부분 환불 범위 밖 |
| `M-018` | `SHOP_DB` | `REJECT` | `POL-50.05` | 순결제액 10,000원보다 큰 15,000원 요청은 초과 환불 |
| `M-019` | `SHOP_DB` | `NEED_MORE_INFO` | `POL-20.03` | 주문 당시 회원 등급 GOLD는 허용되지 않은 등급 |
| `M-020` | `SHOP_DB` | `NEED_MORE_INFO` | `POL-30.03` | 주문 당시 상품 category UNKNOWN은 미등록 카테고리 |

### HARD 20

| ID | fact source | Gold | primary | 설명 |
|---|---|---|---|---|
| `H-001` | `SHOP_DB` | `APPROVE` | `POL-40.01` | VERIFIED DAMAGED가 기간 초과 제한만 override |
| `H-002` | `SHOP_DB` | `APPROVE` | `POL-40.01` | VERIFIED WRONG_ITEM이 실제 Final Sale 제한을 override |
| `H-003` | `SHOP_DB` | `APPROVE` | `POL-40.01` | VERIFIED DEFECTIVE가 개봉 전자제품 제한을 override |
| `H-004` | `SHOP_DB` | `APPROVE` | `POL-40.01` | 기간 초과 + Final Sale + 개봉 전자제품이 모두 성립하고 VERIFIED 회사 귀책이 세 제한만 override |
| `H-005` | `SHOP_DB` | `REJECT` | `POL-50.01` | VERIFIED 회사 귀책과 기간 초과가 있어도 기존 COMPLETED 환불이 우선 |
| `H-006` | `SHOP_DB` | `NOT_APPLICABLE` | `POL-50.02` | VERIFIED 회사 귀책보다 기존 REQUESTED 환불 진행 상태가 우선 |
| `H-007` | `SHOP_DB` | `NOT_APPLICABLE` | `POL-50.06` | 회사 귀책이어도 부분 환불 범위 제한은 override하지 않음 |
| `H-008` | `SHOP_DB` | `NEED_MORE_INFO` | `POL-50.09` | 회사 귀책이어도 요청 USD와 주문 KRW 통화 불일치가 우선 |
| `H-009` | `SHOP_DB` | `REJECT` | `POL-30.01` | 회사 귀책 없이 기간 초과 + Final Sale + 개봉 전자제품이 모두 matched되고 REG-20으로 대표 조항 선택 |
| `H-010` | `SHOP_DB` | `NEED_MORE_INFO` | `POL-40.06` | VERIFIED 상태인데 verified_by가 없어 provenance 필수 정보 누락 |
| `H-011` | `SHOP_DB` | `NEED_MORE_INFO` | `POL-40.08` | VERIFIED 데이터가 존재하지만 provenance_attested=false로 신뢰 검증 실패 |
| `H-012` | `SHOP_DB` | `NEED_MORE_INFO` | `POL-40.07` | 미등록 evidence_status BOGUS |
| `H-013` | `SHOP_DB` | `NEED_MORE_INFO` | `POL-40.05` | PENDING이지만 issue_code LOST가 정책 미등록 문제 코드 |
| `H-014` | `SHOP_DB` | `NEED_MORE_INFO` | `POL-40.04` | evidence_status NONE인데 issue_code가 존재하여 상태/필드 조합 불일치 |
| `H-015` | `SHOP_DB` | `REJECT` | `POL-20.06` | Evidence REJECTED는 override가 아니므로 기간 초과 제한 적용 |
| `H-016` | `SHOP_DB` | `NEED_MORE_INFO` | `POL-10.12` | 같은 order_item_id에 shipment 2건이 존재하여 non-unique shipment |
| `H-017` | `SHOP_DB` | `NOT_APPLICABLE` | `POL-50.11` | 현재 상품의 REJECTED refund id 재사용은 금지하며 다른 order_item의 환불 행은 Adapter가 무시 |
| `H-018` | `SHOP_DB` | `NEED_MORE_INFO` | `POL-50.10` | REQUESTED와 APPROVED 활성 이력이 동시에 존재하는 손상된 환불 원장 |
| `H-019` | `SHOP_DB` | `NEED_MORE_INFO` | `POL-20.04` | delivered_at이 ordered_at보다 빠른 시간 순서 오류 |
| `H-020` | `SHOP_DB` | `NEED_MORE_INFO` | `POL-20.05` | delivered_at이 RFC3339로 파싱할 수 없는 잘못된 날짜 형식 |

## 5. Regression DB로 이전된 기존 Adapter fixture 사례

| ID | fixture | primary |
|---|---|---|
| `E-002` | `CUSTOMER_MISSING` | `POL-10.02` |
| `E-004` | `PRODUCT_MISSING` | `POL-10.03` |
| `E-005` | `ORDER_NON_UNIQUE` | `POL-10.09` |
| `E-008` | `CUSTOMER_NON_UNIQUE` | `POL-10.10` |
| `E-009` | `PRODUCT_NON_UNIQUE` | `POL-10.11` |
| `E-010` | `COUNT_OBJECT_MISMATCH` | `POL-10.14` |
| `E-011` | `ENTITY_REFERENCE_MISMATCH` | `POL-10.15` |
| `E-018` | `SNAPSHOT_REFERENCE_MISMATCH` | `POL-10.16` |
| `E-020` | `FINAL_SALE_UNKNOWN` | `POL-30.05` |

## 6. 정답 생성 순서

```text
시나리오 정의
  ↓
shop.db 조회
  ↓
SQL lookup count + record_present → PolicyFacts
  ↓
policy_oracle.decide(PolicyFacts)
  ↓
expected_result
  ↓
gold_decision / gold_clauses / required_fields 자동 파생
```

Oracle 결과가 예상과 다르면 Gold를 임의 수정하지 않고 regression DB 생성기,
정책 규칙 또는 Oracle 구현 중 잘못된 부분을 수정합니다.

## 7. 한 문장 요약

> 이 60개 정답 데이터는 단순 대표 샘플이 아니라 **47개 정책 조항 전체와 43개 terminal 대표 결과를 모두 실제 Gold에 포함하도록 재설계한 Agent Benchmark**입니다.
