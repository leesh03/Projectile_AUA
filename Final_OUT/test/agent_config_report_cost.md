# 진단 보고서 — COST 목표

## 목표
이 진단은 **"비용을 줄이고 싶어"**라는 목표로 수행했다.

## 전제
- 입력: `agent_logs_full.json` (runs 1개, 60 testcase, 180 trial)
- 모델 요금표는 없으므로 금액으로 환산하지 않는다. 토큰·호출·지연으로만 말한다.
- 제약: 사용자가 별도로 밝힌 제약 없음.

## 0.5 무결성
- 호출 횟수 불일치는 제외 사유가 아니다(수정된 명세). **제외 기록 0건.**
- 실패한 모델 호출 수: **167건 / 167 trial** (failed_call_total=167).
- 토큰 합계 불일치: 없음.

## 1. 프로파일 요약

| 단계 | calls | tokens | token_share | latency_ms | latency_share | model | type | intervention_rate |
|------|-------|--------|-------------|------------|---------------|-------|------|-------------------|
| DECIDE | 13 | 74,719 | 0.6002 | 525,264 | 0.3418 | gemini-3.6-flash | llm_call | 0.928 |
| VERIFY_REASONING | 9 | 49,776 | 0.3998 | 292,527 | 0.1903 | gemini-3.6-flash | llm_call | 0.308 |
| GENERATE_QUERY | 180 | 0 | 0.0000 | 0 | 0.0000 | sql-plan-v1 | llm_call | 0.0 |

- 전체 토큰: **124,495**
- 전체 호출: **202**
- 전체 지연: **1,536,905ms**
- token_share 합: **1.0** ✅

## 2. 진단 (공통 규칙 + COST 규칙)

### 공통 규칙
| ID | 내용 | 심각도 |
|----|------|--------|
| D-02 | DECIDE 60.0%, VERIFY_REASONING 39.98% — 비용 집중 핫스팟 | 정보 |
| D-03 | PROVIDER_ERROR 27건(36건 중 75%) 집중. 실패한 모델 호출 167건. | P1 |
| D-04 | V1.repair_enabled 켜져 있으나 REPAIR_QUERY 미관측. | P1 |

### COST 규칙
| ID | 발화 여부 | 사유 |
|----|-----------|------|
| C-01 | ❌ | stability_rate 0.883 < 0.90 |
| C-02 | ❌ | 화이트리스트(VERIFY_REASONING·REPAIR_QUERY·PLAN)만 대상. DECIDE·GENERATE_QUERY는 대상 아님. VERIFY_REASONING은 intervention_rate=0.308 ≠ 0. GENERATE_QUERY는 토큰 0. |
| C-03 | ❌ | retry_runs=0 |
| C-04 | ❌ | stability_rate <0.90이며 llm_call 단계 구조 일정 조건 확인 필요 (이번엔 조건 미달) |
| C-05 | ✅ | DECIDE·VERIFY_REASONING이 같은 gemini-3.6-flash 공유 |

## 3. 전체 판정
**ACTION_NEEDED** — P1 Finding(D-03, D-04)이 있다.

## 4. 제안 (근거 수치 기반)

### 제안 1: DECIDE 분리 모델 검토 — SPLIT_MODEL
- **대상**: DECIDE (node_role)
- **연산자**: SPLIT_MODEL
- **근거 Finding**: C-05 + D-02
- **수치**: DECIDE 토큰 74,719 (전체 60.0%), calls 13, model gemini-3.6-flash. VERIFY_REASONING과 같은 모델 공유.
- **목표 적합성**: COST — 전체 토큰의 60%를 쓰는 무거운 단계를 분리하면 DECIDE에 맞는 모델 별도 선택 가능.
- **예상 효과**: 토큰 절감액은 요금표 없어 계산 불가. 분리 후 DECIDE 전용 모델로 변경 가능성.
- **확인법**: 분리 후 DECIDE token_share 및 실패율(D-03, failed_call) 추적.

### 제안 2: VERIFY_REASONING 분리 모델 검토 — SPLIT_MODEL
- **대상**: VERIFY_REASONING
- **연산자**: SPLIT_MODEL
- **근거 Finding**: C-05 + D-02
- **수치**: VERIFY_REASONING 토큰 49,776 (전체 39.98%), calls 9, model gemini-3.6-flash. DECIDE와 같은 모델 공유.
- **목표 적합성**: COST — 검증 단계도 분리하면 모델 별도 선택 가능. 전체 토큰 40%.
- **예상 효과**: 계산 불가 (요금표 없음).
- **확인법**: 분리 후 VERIFY intervention_rate(0.308)와 token_share 추적.

### 제안 3: repair_enabled 설정 정리 — REMOVE 또는 MAKE_CONDITIONAL
- **대상**: V1.repair_enabled 설정
- **연산자**: REMOVE (또는 MAKE_CONDITIONAL, 안전 고려)
- **근거 Finding**: D-04 (P1)
- **수치**: scaffold_config V1.repair_enabled=True, traces에 REPAIR_QUERY 0회.
- **목표 적합성**: COST — 안 쓰는 구조 제거로 설정 단순화.
- **위험**: repair_enabled 제거 시 실패 복구 수단 사라짐. 현재 retry_runs=0이라 복구 필요도 낮지만, 향후 실패 시 복구 불가. MAKE_CONDITIONAL로 조건부화하면 안전망 유지 가능.
- **확인법**: 설정 제거/조건부화 후 실패 처리 방식 및 REPAIR_QUERY 발생 여부 확인.

## 5. 잘하고 있는 것 (모범 사례)
- **GENERATE_QUERY**: provider=local-deterministic, 토큰 0, calls 180. 이미 코드로 처리되는 단계. 토큰 비용이 전혀 없고 180회 실행해도 비용 영향 없음. 이 패턴은 유지·확산 검토 가능.

## 참고 (제안하지는 않지만 맥락)
- **success_rate 0.05**, **policy_accuracy 0.044** — 현재 품질 매우 낮음. 비용 최적화 시 이 상태가 더 나빠지지 않도록 주의.
- **stability_rate 0.883** — 0.90에 근접. 반복 데이터 더 쌓이면 C-01 발동 가능 (그때 DECIDE·VERIFY_REASONING 모델 하향 검토).
- **failed_call_total 167** — 대부분 trial에서 모델 호출 실패 경험. D-03(PROVIDER_ERROR 집중)과 연결. 실패 처리 방식 검토 필요 (COST에선 재시도 제안(C-03)은 해당 없음).
