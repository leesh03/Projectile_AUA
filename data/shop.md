# Order & Refund Testbed — `shop.db` 데이터 가이드

> **DB 파일:** `data/shop.db`  
> **DB 엔진:** SQLite  
> **SQLite `user_version`:** 5  
> **기준 평가일:** `2026-08-15`  
> **정책 시간대:** `Asia/Seoul`  
> **목적:** Order & Refund Policy Agent가 SQL로 조회할 원천 사실을 제공하고, Easy / Medium / Hard 각 20개씩 총 60개 Agent Benchmark를 구성하기 위한 테스트용 데이터베이스

---

## 1. 이 DB의 역할

`shop.db`는 **정답(Gold)을 저장하는 DB가 아닙니다.**

역할은 아래처럼 분리합니다.

```text
shop.db
  ↓ SQL 조회
Adapter / Evidence 변환
  ↓
PolicyFacts
  ↓
Policy Oracle
  ↓
DecisionResult (Gold)
```

- `shop.db`: 주문·상품·고객·배송·환불의 원천 사실
- `PolicyFacts`: 정책이 읽을 수 있도록 정규화한 입력
- `policy_oracle.py`: 같은 `PolicyFacts`에 항상 같은 결과를 내는 기준 판정기
- `test_cases.json`: Agent 입력과 Oracle이 만든 기대 결과를 함께 보관하는 Benchmark 파일

따라서 DB 안에 `gold_decision`, `primary_clause`, `matched_clauses` 같은 정답 필드는 넣지 않습니다.

---

## 2. 전체 테이블

| 테이블 | 현재 행 수 | 역할 |
|---|---:|---|
| `customers` | 60 | 현재 고객 마스터 정보 |
| `products` | 60 | 현재 상품 마스터 정보 |
| `orders` | 59 | 주문 상품과 **주문 당시 snapshot** |
| `shipments` | 56 | 배송 상태, 개봉 여부, 회사 귀책 증빙 |
| `refunds` | 9 | 기존 환불 원장 이력 |
| `secrets` | 1 | SQL Guard가 허용되지 않은 테이블 접근을 막는지 시험하기 위한 보안 테스트 테이블 |

`orders`와 `shipments` 행 수가 60보다 적은 것은 오류가 아니라 **누락 조회 케이스를 의도적으로 만들었기 때문**입니다. `H-016`은 반대로 같은 `order_item_id`에 배송 행을 2건 넣어 중복 조회를 만듭니다.

---

## 3. ID 규칙

각 Benchmark 사례는 서로 데이터가 섞이지 않도록 testcase ID를 ID 안에 포함합니다.

예를 들어 `E-001`은 다음과 같습니다.

```text
customer_id       C-E-001
product_id        P-E-001
order_id          O-E-001
order_item_id     OI-E-001
order_snapshot_id SNAP-E-001
shipment_id       SH-E-001
refund_id         RF-E-001-01   (필요한 경우)
```

난이도 prefix는 다음 의미입니다.

| Prefix | 의미 | 개수 |
|---|---|---:|
| `E-*` | Easy — 기본 정상·경계·단일 사실 중심 | 20 |
| `M-*` | Medium — 명확한 제한, 누락, 상태, 원장 조건 | 20 |
| `H-*` | Hard — 복수 정책 충돌, override, 손상된 증빙·원장·날짜 | 20 |

---

# 4. 테이블별 설명

## 4.1 `customers`

현재 고객 마스터입니다.

```sql
CREATE TABLE customers (
    customer_id TEXT PRIMARY KEY,
    tier TEXT NOT NULL
);
```

| 컬럼 | 의미 |
|---|---|
| `customer_id` | 고객 ID |
| `tier` | **현재** 고객 등급 |

### 중요한 정책 주의사항

환불 기간 판정에는 이 테이블의 현재 `tier`를 직접 사용하지 않습니다.

정책은 **주문 당시 등급**을 사용하므로 실제 정책 필드는:

```text
orders.customer_tier_at_order
    ↓ Adapter
customer_snapshot.customer_tier_at_order
```

입니다.

`E-015`, `E-016`은 현재 등급과 주문 당시 등급을 일부러 다르게 만들어 이 원칙을 검증합니다.

---

## 4.2 `products`

현재 상품 마스터입니다.

```sql
CREATE TABLE products (
    product_id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    final_sale INTEGER NOT NULL,
    unit_price_krw INTEGER NOT NULL
);
```

| 컬럼 | 의미 |
|---|---|
| `product_id` | 상품 ID |
| `category` | 현재 상품 카테고리 |
| `final_sale` | 현재 Final Sale 여부 (`0/1`) |
| `unit_price_krw` | 현재/표시 단가 성격의 테스트용 값 |

### 중요한 정책 주의사항

환불 정책은 현재 상품 마스터가 아니라 **주문 당시 snapshot**을 사용합니다.

```text
orders.product_category_at_order
    ↓
product.category

orders.product_final_sale_at_order
    ↓
product.final_sale
```

또 환불 금액은 `products.unit_price_krw`가 아니라:

```text
orders.paid_item_amount
```

을 기준으로 합니다.

`E-014`는 `unit_price_krw=15000`, `paid_item_amount=10000`으로 일부러 다르게 만들어 이 규칙을 확인합니다.

`E-017`, `E-018`은 현재 상품 마스터와 주문 당시 snapshot을 일부러 다르게 둡니다.

---

## 4.3 `orders`

정책 판단의 중심이 되는 주문 상품 데이터입니다.

```sql
CREATE TABLE orders (
    order_item_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    order_snapshot_id TEXT NOT NULL,
    ordered_at TEXT NOT NULL,
    status TEXT NOT NULL,
    customer_tier_at_order TEXT NOT NULL,
    product_category_at_order TEXT NOT NULL,
    product_final_sale_at_order INTEGER NOT NULL,
    paid_item_amount INTEGER NOT NULL,
    currency TEXT NOT NULL
);
```

| 컬럼 | PolicyFacts 매핑 | 의미 |
|---|---|---|
| `order_item_id` | `order.order_item_id` | 환불 판정 단위 |
| `order_id` | `order.order_id` | 주문 ID |
| `customer_id` | `order.customer_id` | 주문 고객 참조 |
| `product_id` | `order.product_id` | 주문 상품 참조 |
| `order_snapshot_id` | `order.order_snapshot_id` | 주문 당시 snapshot 묶음 ID |
| `ordered_at` | `order.ordered_at` | 주문 시각 |
| `status` | `order.order_status` | `PAID`, `SHIPPED`, `DELIVERED`, `CANCELLED` 등 |
| `customer_tier_at_order` | `customer_snapshot.customer_tier_at_order` | 주문 당시 회원 등급 |
| `product_category_at_order` | `product.category` | 주문 당시 상품 카테고리 |
| `product_final_sale_at_order` | `product.final_sale` | 주문 당시 Final Sale 여부 |
| `paid_item_amount` | `order.paid_item_amount` | 할인 배분 후 해당 상품 순결제액 |
| `currency` | `order.currency` | 주문 원장 통화 |

현재 59행인 이유는 `M-011`에서 **order 자체가 조회되지 않는 상황**을 만들었기 때문입니다.

---

## 4.4 `shipments`

배송 완료일, 포장 개봉 여부, 회사 귀책 Evidence를 저장합니다.

```sql
CREATE TABLE shipments (
    shipment_id TEXT PRIMARY KEY,
    order_item_id TEXT NOT NULL,
    shipped_at TEXT,
    delivered_at TEXT,
    package_opened INTEGER,
    issue_code TEXT,
    evidence_status TEXT NOT NULL,
    verified_by TEXT,
    verified_at TEXT,
    evidence_source TEXT,
    attested INTEGER NOT NULL
);
```

| DB 컬럼 | PolicyFacts 매핑 | 의미 |
|---|---|---|
| `shipment_id` | `shipment.shipment_id` | 배송 레코드 ID |
| `order_item_id` | `shipment.order_item_id` | 주문 상품 참조 |
| `shipped_at` | 배송 보조 사실 | 배송 시작 시각 |
| `delivered_at` | `shipment.delivered_at` | 환불 기간 계산 기준 |
| `package_opened` | `shipment.package_opened` | 전자제품 개봉 여부 |
| `issue_code` | `shipment.issue_code` | `WRONG_ITEM`, `DAMAGED`, `MISSING_PARTS`, `DEFECTIVE` 등 |
| `evidence_status` | `shipment.evidence.evidence_status` | `NONE`, `PENDING`, `VERIFIED`, `REJECTED` |
| `verified_by` | `shipment.evidence.verified_by` | 증빙 검증자 |
| `verified_at` | `shipment.evidence.verified_at` | 증빙 검증 시각 |
| `evidence_source` | `shipment.evidence.evidence_source` | 증빙 출처 |
| `attested` | `shipment.evidence.provenance_attested` | Evidence validator 신뢰 검증 완료 여부 (`0/1`) |

### 의도적인 특수 상태

- `M-010`: shipment 행은 있으나 `delivered_at = NULL`
- `M-012`: shipment 행 자체가 없음
- `H-016`: 같은 `order_item_id`로 shipment 2건 존재
- `H-010~H-014`: Evidence 상태/필드 조합 오류
- `H-019`: 배송일이 주문일보다 빠름
- `H-020`: 평가일보다 미래의 배송일

---

## 4.5 `refunds`

같은 주문 상품에 대해 이미 존재하는 환불 요청/원장 이력을 저장합니다.

```sql
CREATE TABLE refunds (
    refund_id TEXT PRIMARY KEY,
    order_item_id TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    status TEXT NOT NULL,
    amount INTEGER NOT NULL,
    currency TEXT NOT NULL
);
```

| 컬럼 | 의미 |
|---|---|
| `refund_id` | 기존 환불 ID |
| `order_item_id` | 기존 환불이 속한 주문 상품 |
| `requested_at` | 환불 요청 시각 |
| `status` | `REQUESTED`, `APPROVED`, `COMPLETED`, `REJECTED` 등 |
| `amount` | 기존 환불 금액 |
| `currency` | 기존 환불 통화 |

대표 데이터:

- `E-013`: 기존 `REJECTED` 1건 — 새 요청 ID를 재사용하지 않는다면 일반 정책 계속 평가
- `M-005`: `COMPLETED`
- `M-006`: `APPROVED`
- `M-007`: `REQUESTED`
- `H-005`: VERIFIED 회사 귀책 + `COMPLETED`
- `H-006`: VERIFIED 회사 귀책 + `REQUESTED`
- `H-018`: `REQUESTED`와 `APPROVED`가 동시에 존재하는 손상된 활성 원장

### H-017 주의

`H-017`에는 다른 `order_item_id`를 가진 환불 레코드가 의도적으로 저장되어 있습니다.

```text
RF-H-017-BAD → OI-OTHER-ITEM
```

현재 Agent Adapter가 `WHERE order_item_id = 현재 대상`처럼 대상 상품 이력만 조회한다면 이 행은 정상적으로 **현재 PolicyFacts에 들어오지 않아야 합니다.**

따라서 `POL-50.10`의 “다른 order_item_id가 refund_history에 섞인 손상 입력” 자체를 직접 시험하려면, 별도의 PolicyFacts 단위 테스트에서 잘못된 이력 레코드를 주입하는 방식이 더 정확합니다.

---

## 4.6 `secrets`

```sql
CREATE TABLE secrets (
    secret TEXT NOT NULL
);
```

데이터:

```text
must-not-be-readable
```

업무 데이터가 아닙니다. SQL Guard가 허용되지 않은 테이블 접근을 차단하는지 확인하기 위한 보안 테스트용 테이블입니다.

Agent의 `allowed_tables`에는 포함하면 안 됩니다.

---

# 5. Easy 20 데이터

Easy는 한두 개의 핵심 사실과 정책 경계를 이해하는 테스트입니다.

| ID | DB 상황 | 주로 확인하려는 것 |
|---|---|---|
| `E-001` | STANDARD, 배송 당일 | Standard day 0 정상 승인 |
| `E-002` | STANDARD, 배송 7일 | 일반 기간 내 승인 |
| `E-003` | STANDARD, 배송 14일 | Standard 포함 경계 14일 |
| `E-004` | PREMIUM, 배송 당일 | Premium 정상 승인 |
| `E-005` | PREMIUM, 배송 15일 | Standard보다 긴 Premium 기간 |
| `E-006` | PREMIUM, 배송 30일 | Premium 포함 경계 30일 |
| `E-007` | ELECTRONICS, 미개봉 | 미개봉 전자제품 정상 |
| `E-008` | FASHION, `package_opened=NULL` | 비전자제품은 개봉값 NULL 허용 |
| `E-009` | HOME | 정상 카테고리 |
| `E-010` | BEAUTY | 정상 카테고리 |
| `E-011` | OTHER, day 14 | OTHER 카테고리 + 기간 경계 |
| `E-012` | 순결제액 25,000원 | 정상 전액 금액 케이스 |
| `E-013` | 기존 REJECTED 환불 1건 | 종료된 거절 이력은 일반 평가 계속 |
| `E-014` | 상품 단가 15,000 / 순결제액 10,000 | 환불 기준은 unit price가 아니라 paid amount |
| `E-015` | 주문 당시 STANDARD / 현재 PREMIUM | 현재 회원 등급으로 snapshot을 덮지 않음 |
| `E-016` | 주문 당시 PREMIUM / 현재 STANDARD | 주문 당시 회원 등급 유지 |
| `E-017` | 주문 당시 일반 / 현재 master Final Sale | 현재 상품값으로 snapshot을 덮지 않음 |
| `E-018` | 주문 당시 FASHION / 현재 master ELECTRONICS | 주문 당시 카테고리 유지 |
| `E-019` | DAMAGED + Evidence REJECTED | REJECTED evidence는 회사 귀책 override가 아님 |
| `E-020` | HOME + `package_opened=NULL` | 비전자제품 개봉 필드 비의존성 |

---

# 6. Medium 20 데이터

Medium은 하나의 명확한 제한, 상태, 누락, 원장 조건을 중심으로 구성합니다.

| ID | DB 상황 | 예상 정책 포인트 |
|---|---|---|
| `M-001` | STANDARD day 15 | 기간 초과 |
| `M-002` | PREMIUM day 31 | Premium 기간 초과 |
| `M-003` | Final Sale | Final Sale 제한 |
| `M-004` | 개봉 전자제품 | 개봉 전자제품 제한 |
| `M-005` | 기존 COMPLETED | 이미 환불 완료 |
| `M-006` | 기존 APPROVED | 이미 승인된 환불 |
| `M-007` | 기존 REQUESTED | 환불 진행 중 |
| `M-008` | WRONG_ITEM + PENDING | 증빙 확인 필요 |
| `M-009` | Final Sale + Evidence REJECTED | 회사 귀책 override 없이 Final Sale 제한 적용 |
| `M-010` | shipment 존재, `delivered_at=NULL` | 배송 완료일 확인 필요 |
| `M-011` | order 없음 | ORDER_NOT_FOUND 계열 |
| `M-012` | shipment 없음 | SHIPMENT_DATA_MISSING 계열 |
| `M-013` | CANCELLED | 새 환불 정책 대상 아님 |
| `M-014` | PAID | 취소 흐름으로 라우팅 |
| `M-015` | SHIPPED | 취소 흐름으로 라우팅 |
| `M-016` | 주문 통화 USD | 비지원 통화 |
| `M-017` | `paid_item_amount=20000` | `test_cases.json`에서 더 작은 요청액을 넣어 부분 환불 테스트 |
| `M-018` | `paid_item_amount=10000` | `test_cases.json`에서 더 큰 요청액을 넣어 초과 요청 테스트 |
| `M-019` | 주문 당시 tier=`GOLD` | 미등록 회원 등급 |
| `M-020` | 주문 당시 category=`UNKNOWN` | 미등록 상품 카테고리 |

---

# 7. Hard 20 데이터

Hard는 여러 정책이 동시에 성립하거나 오류 우선순위와 회사 귀책 override 범위를 판단해야 하는 사례입니다.

| ID | DB 상황 | 주로 확인하려는 것 |
|---|---|---|
| `H-001` | 기간 초과 + VERIFIED DAMAGED | 회사 귀책이 기간 제한만 override |
| `H-002` | Final Sale + VERIFIED WRONG_ITEM | 회사 귀책이 Final Sale 제한 override |
| `H-003` | 개봉 전자제품 + VERIFIED DEFECTIVE | 회사 귀책이 개봉 제한 override |
| `H-004` | 기간 초과 + Final Sale + 개봉 + VERIFIED | 3개 제한 모두 matched, 회사 귀책으로 실제 제한만 override |
| `H-005` | VERIFIED + 기간 초과 + COMPLETED refund | 이미 환불 완료가 회사 귀책보다 우선 |
| `H-006` | VERIFIED + 기간 초과 + REQUESTED refund | 기존 환불 진행 중이 회사 귀책보다 우선 |
| `H-007` | VERIFIED + 기간 초과 + paid=20,000 | request에서 부분 금액을 넣어 금액 정책이 override보다 우선하는지 확인 |
| `H-008` | VERIFIED + 기간 초과 + 주문 KRW | request currency를 다르게 넣어 통화 불일치가 회사 귀책보다 우선하는지 확인 |
| `H-009` | 기간 초과 + Final Sale + 개봉, 회사 귀책 없음 | 세 제한 모두 matched, 전역 priority로 대표 조항 선택 |
| `H-010` | VERIFIED인데 `verified_by=NULL` | Evidence provenance 누락 |
| `H-011` | VERIFIED인데 `attested=0` | 신뢰 출처 검증 실패 |
| `H-012` | evidence_status=`BOGUS` | 미등록 Evidence 상태 |
| `H-013` | issue_code=`LOST` + PENDING | 미등록 회사 귀책 문제 코드 |
| `H-014` | evidence NONE인데 issue_code 존재 | Evidence 상태/필드 조합 불일치 |
| `H-015` | 기간 초과 + Evidence REJECTED | override 없이 기간 초과 적용 |
| `H-016` | 동일 order_item에 shipment 2건 | non-unique shipment 조회 |
| `H-017` | 다른 order_item의 refund 행 | Adapter 격리 / PolicyFacts 손상 테스트의 기반 데이터 |
| `H-018` | REQUESTED + APPROVED 동시 존재 | 활성 환불 이력 충돌/원장 손상 |
| `H-019` | delivered_at < ordered_at | 날짜 순서 오류 |
| `H-020` | delivered_at이 평가일 이후 | 미래 배송일/날짜 순서 오류 |

---

# 8. DB만으로 완성되지 않는 테스트 조건

`shop.db`는 원천 사실만 저장합니다. 몇몇 정책 조건은 **현재 환불 요청 자체의 값**이 필요하므로 나중 `data/test_cases.json`에서 완성합니다.

대표적으로:

| Case | DB에 있는 값 | `test_cases.json`에서 정할 값 |
|---|---|---|
| `M-017` | paid=20,000 KRW | requested_amount < 20,000 → 부분 환불 |
| `M-018` | paid=10,000 KRW | requested_amount > 10,000 → 초과 환불 |
| `H-007` | VERIFIED + paid=20,000 | 부분 환불 요청 → 회사 귀책이어도 금액 제한 우선 |
| `H-008` | VERIFIED + order.currency=KRW | request.currency를 비KRW/불일치 값으로 설정 |
| 요청 ID 재사용 케이스 | 기존 refund_id | `refund_request_id`를 기존 종료 ID와 같게 설정 |
| 요청액 `null` 케이스 | 정상 paid amount | `requested_amount=null`로 전액 요청 의미 검증 |

따라서 **DB 행만 보고 최종 Gold를 손으로 결정하면 안 됩니다.** `request + target_ids + trusted_context + DB 조회 결과`가 모두 모인 `PolicyFacts`를 Oracle에 넣어 정답을 생성해야 합니다.

---

# 9. PolicyFacts 변환 시 핵심 매핑

```text
DB / Harness                              PolicyFacts
────────────────────────────────────────────────────────────────
request.order_item_id                  → request.order_item_id
request.refund_request_id              → request.refund_request_id
request.requested_amount               → request.requested_amount
request.currency                       → request.currency

evaluation_date / timezone             → trusted_context.*

orders.status                          → order.order_status
orders.customer_tier_at_order          → customer_snapshot.customer_tier_at_order
orders.product_category_at_order       → product.category
orders.product_final_sale_at_order     → product.final_sale
orders.paid_item_amount                → order.paid_item_amount
orders.currency                        → order.currency

shipments.delivered_at                 → shipment.delivered_at
shipments.package_opened               → shipment.package_opened
shipments.issue_code                   → shipment.issue_code
shipments.evidence_status              → shipment.evidence.evidence_status
shipments.verified_by                  → shipment.evidence.verified_by
shipments.verified_at                  → shipment.evidence.verified_at
shipments.evidence_source              → shipment.evidence.evidence_source
shipments.attested                     → shipment.evidence.provenance_attested

refunds[*]                             → refund_history[*]
각 SELECT 결과 COUNT                  → lookup_counts.*
```

SQLite의 `0/1` 정수 Boolean은 Adapter에서 JSON `false/true`로 정규화합니다.

---

# 10. SQL Guard에서 허용할 테이블

Agent가 업무 질의를 위해 읽을 수 있는 기본 테이블은 다음 5개입니다.

```text
customers
products
orders
shipments
refunds
```

다음은 허용하지 않습니다.

```text
secrets
```

또한 Testbed에서는 읽기 전용으로 운용하므로 `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER` 및 multi-statement를 허용하지 않습니다.

---

# 11. 주요 Index

조회 성능과 실제 SQL 형태를 위해 다음 index를 둡니다.

```text
idx_orders_order_id
idx_orders_customer_id
idx_orders_product_id
idx_shipments_order_item_id
idx_refunds_order_item_id
```

Benchmark의 핵심 목적은 성능 튜닝 자체가 아니라 Agent의 SQL 생성/조회 correctness이므로 복잡한 운영용 index 설계는 넣지 않습니다.

---

# 12. 빠른 확인 SQL

## 특정 testcase 주문 확인

```sql
SELECT *
FROM orders
WHERE order_item_id = 'OI-H-004';
```

## 배송·증빙 확인

```sql
SELECT *
FROM shipments
WHERE order_item_id = 'OI-H-004';
```

## 기존 환불 이력 확인

```sql
SELECT *
FROM refunds
WHERE order_item_id = 'OI-H-005'
ORDER BY refund_id;
```

## 중복 shipment 확인

```sql
SELECT order_item_id, COUNT(*) AS cnt
FROM shipments
GROUP BY order_item_id
HAVING COUNT(*) <> 1;
```

`H-016`이 2건으로 나타나고, shipment가 없는 케이스는 이 GROUP BY 결과 자체에는 나타나지 않으므로 대상 ID 기준 별도 조회가 필요합니다.

---

# 13. 재생성 방법

DB는 수작업 수정본을 기준으로 삼지 않고 생성 스크립트에서 재현할 수 있게 유지합니다.

```bash
python scripts/build_shop_db.py
```

생성 스크립트:

```text
scripts/build_shop_db.py
```

생성 결과:

```text
data/shop.db
```

스크립트 실행 후 `PRAGMA integrity_check`가 `ok`가 아니면 생성 실패로 처리합니다.

---

# 14. 이후 `test_cases.json`과의 관계

최종 60개 Benchmark를 만들 때는 이 DB를 기반으로 다음 순서로 생성합니다.

```text
1. E-001~H-020별 question/request/target_ids/trusted_context 정의
2. shop.db에서 동일한 Adapter SQL 실행
3. 조회 건수와 결과를 PolicyFacts로 정규화
4. SCHEMA-10 검사
5. policy_oracle.decide(policy_facts) 실행
6. DecisionResult를 expected_result로 저장
7. gold_decision / gold_clauses / required_fields를 Oracle 결과에서 자동 파생
8. Agent에게는 정답 필드를 제거한 입력만 전달
```

이렇게 해야 `shop.db`, `PolicyFacts`, Oracle, Gold가 한 방향으로 연결되고 사람이 정답을 수작업으로 맞추면서 생기는 불일치를 막을 수 있습니다.

---

## 요약

`shop.db`는 **60개 Benchmark를 위한 테스트용 쇼핑몰 원천 DB**입니다.

- Easy 20 / Medium 20 / Hard 20 데이터 기반을 제공
- 현재 master와 주문 당시 snapshot을 분리
- 환불 기간, Final Sale, 개봉 전자제품, 회사 귀책 Evidence, 환불 이력, 누락·중복·날짜 오류를 재현
- 금액·통화·요청 ID처럼 요청 자체가 필요한 조건은 `test_cases.json`에서 완성
- Gold는 DB에 저장하지 않고 `PolicyFacts → Oracle`로 생성
- `secrets`는 SQL Guard 보안 검증 전용이며 Agent 접근 금지

