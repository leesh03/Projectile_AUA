# Order & Refund Testbed — `shop.db` regression 스키마

> DB: `data/shop.db`
> SQLite `user_version`: 5
> 평가 기준일: `2026-08-15`
> 목적: 60개 PolicyFacts를 testcase 전용 Adapter 없이 SQL 조회만으로 재현

## 데이터 흐름

```text
agent_cases.json의 order_item_id
  → shop.db의 lookup_order_item_id 조회
  → record_present가 참인 행만 객체로 materialize
  → lookup 행 수 + materialize된 객체
  → PolicyFacts
  → policy_rules.json / policy_oracle.py
```

DB에는 Gold 판정, 조항, testcase ID가 없습니다. `lookup_order_item_id`는 실제
Agent 요청에 포함되는 주문 상품 키이며, `record_present`는 결측과
count/object 불일치를 SQL 행으로 표현하기 위한 regression 전용 필드입니다.

## 테이블

### `orders`

```sql
CREATE TABLE orders (
    lookup_order_item_id TEXT,
    record_present INTEGER,
    order_item_id TEXT,
    order_id TEXT,
    customer_id TEXT,
    product_id TEXT,
    order_snapshot_id TEXT,
    ordered_at TEXT,
    status TEXT,
    paid_item_amount INTEGER,
    currency TEXT
);
```

### `customers`

```sql
CREATE TABLE customers (
    lookup_order_item_id TEXT,
    record_present INTEGER,
    customer_id TEXT,
    order_snapshot_id TEXT,
    tier TEXT,
    snapshotted_at TEXT
);
```

`tier`는 현재 회원 등급이 아니라 주문 당시 `customer_tier_at_order`로
materialize됩니다.

### `products`

```sql
CREATE TABLE products (
    lookup_order_item_id TEXT,
    record_present INTEGER,
    product_id TEXT,
    order_snapshot_id TEXT,
    category TEXT,
    final_sale INTEGER,
    snapshotted_at TEXT
);
```

### `shipments`

```sql
CREATE TABLE shipments (
    lookup_order_item_id TEXT,
    record_present INTEGER,
    shipment_id TEXT,
    order_item_id TEXT,
    shipped_at TEXT,
    delivered_at TEXT,
    package_opened INTEGER,
    issue_code TEXT,
    evidence_status TEXT,
    verified_by TEXT,
    verified_at TEXT,
    evidence_source TEXT,
    attested INTEGER
);
```

Evidence 컬럼은 `shipment.evidence.*`로 materialize됩니다.

### `refunds`

```sql
CREATE TABLE refunds (
    refund_id TEXT,
    order_item_id TEXT,
    requested_at TEXT,
    status TEXT,
    amount INTEGER,
    currency TEXT
);
```

## 특수 사례 표현

- 누락: lookup 행이 없거나 `record_present = 0`
- 중복: 같은 `lookup_order_item_id`로 2개 이상의 lookup 행
- 참조 불일치: lookup 키와 반환 객체 ID를 서로 다르게 저장
- 잘못된 enum·날짜·금액: 해당 원천 컬럼에 그대로 저장

Core는 `_record_present`를 제거한 후 정규 PolicyFacts만 정책 엔진에 전달합니다.

## 재생성

```bash
python data/build_shop_db.py
python data/build_dataset.py
python -m pytest tests -q
```

`build_dataset.py`는 `answer_key.db`에서 60개 evaluator 사례를 동기화한 뒤,
같은 `policy_facts`로 `shop.db`를 다시 만듭니다. 따라서 DB와 Gold가 서로 다른
소스에서 독립적으로 변경되어 drift가 생기지 않습니다.
