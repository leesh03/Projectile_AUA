# Agent Upgrade Risk Report

| 항목 | 내용 |
|---|---|
| report_id | rpt_scenario_a |
| bundle_id | audit_mock_scenario_a |
| 생성 시각 | 2026-08-15 12:00:00+00:00 |
| **판정** | **HOLD** |

---

## 1. Summary

| 지표 | V0 | V1 | 변화 |
|---|---|---|---|
| 성공률 (success_rate) | 100.0% | 75.0% | -25.0pp |
| Tool 오류율 (tool_error_rate) | 0.0% | 25.0% | +25.0pp |
| 평균 재시도 (avg_retry) | 0.28 | 0.53 | +0.25 |
| 평균 토큰 (avg_tokens) | 2,395 | 2,482 | +3.7% |
| 평균 지연 ms (avg_latency_ms) | 3,418 | 3,522 | +3.1% |
| 안전 위반 건수 (safety_violation) | 0 | 0 | +0 |

testcase 20개 · trial 2회 기준.

---

## 2. Regression

| Finding | 심각도 | rule_id | 유형 | 영향 케이스 | 내용 | 근거 |
|---|---|---|---|---|---|---|
| F-01 | P0 | R-01 | REGRESSION | 5건 (case_03, case_07, case_12, case_15, case_18) | 5개 testcase가 V0 PASS -> V1 FAIL로 뒤집힘 | success_rate: V0=1 / V1=0.75 · Δ-25.0pp |
| F-02 | P0 | R-02 | REGRESSION | 5건 (case_03, case_07, case_12, case_15, case_18) | tool 인자 스키마 유효율 하락 | tool_schema_valid_rate: V0=1 / V1=0.75 · Δ-25.0pp · (임계 -25.0pp <= 임계 -5.0pp) |
| F-03 | P1 | R-04 | REGRESSION | 5건 (case_03, case_07, case_12, case_15, case_18) | 종료 사유(stop_reason) 분포 악화 — 실패로 끝나는 비율 증가 | non_ok_stop_reason_rate: V0=0 / V1=0.25 · Δ+25.0pp · (임계 +25.0pp >= 임계 5.0pp) |

---

## 3. Efficiency

해당 없음.

---

## 4. Trace Diff

NOT_AVAILABLE — 이 번들에는 trace가 포함되지 않았습니다.

---

## 5. Recommendation

준비 중 (P6 수정 후보 생성 전).

---

## 6. Risk & Limits

재검증 이력 없음 (P7 이전이거나 아직 후보를 적용하지 않음).

**이 보고서가 말하지 못하는 것**

- TestCase 20개 · 반복 2회 기준이므로 통계적 일반화는 주장하지 않음
- Trace 데이터가 없어 최초 분기 지점(Trace Diff)과 O-01/O-02 규칙을 확인할 수 없음
