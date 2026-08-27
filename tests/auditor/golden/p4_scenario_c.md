# Agent Upgrade Risk Report

| 항목 | 내용 |
|---|---|
| report_id | rpt_scenario_c |
| bundle_id | audit_mock_scenario_c |
| 생성 시각 | 2026-08-15 12:00:00+00:00 |
| **판정** | **HOLD** |

---

## 1. Summary

| 지표 | V0 | V1 | 변화 |
|---|---|---|---|
| 성공률 (success_rate) | 100.0% | 70.0% | -30.0pp |
| Tool 오류율 (tool_error_rate) | 0.0% | 30.0% | +30.0pp |
| 평균 재시도 (avg_retry) | 0.25 | 1.75 | +1.50 |
| 평균 토큰 (avg_tokens) | 2,416 | 3,250 | +34.6% |
| 평균 지연 ms (avg_latency_ms) | 3,404 | 4,737 | +39.2% |
| 안전 위반 건수 (safety_violation) | 0 | 0 | +0 |

testcase 20개 · trial 2회 기준.

---

## 2. Regression

| Finding | 심각도 | rule_id | 유형 | 영향 케이스 | 내용 | 근거 |
|---|---|---|---|---|---|---|
| F-01 | P0 | R-01 | REGRESSION | 6건 (case_02, case_06, case_09, case_13, case_17 외 1건) | 6개 testcase가 V0 PASS -> V1 FAIL로 뒤집힘 | success_rate: V0=1 / V1=0.7 · Δ-30.0pp |
| F-03 | P1 | O-02 | OPTIMIZATION_OPPORTUNITY | 6건 (case_02, case_06, case_09, case_13, case_17 외 1건) | 같은 오류로 재시도해도 거의 회복하지 못함 — 재시도 상한을 낮출 여지 | retry_recovery_rate: V0=0 / V1=0 · (임계 recovery_rate 0.00 <= 임계 0.05 (표본 12건)) |
| F-04 | P1 | R-04 | REGRESSION | 6건 (case_02, case_06, case_09, case_13, case_17 외 1건) | 종료 사유(stop_reason) 분포 악화 — 실패로 끝나는 비율 증가 | non_ok_stop_reason_rate: V0=0 / V1=0.3 · Δ+30.0pp · (임계 +30.0pp >= 임계 5.0pp) |

---

## 3. Efficiency

| Finding | 심각도 | rule_id | 영향 케이스 | 내용 | 근거 (임계값 포함) |
|---|---|---|---|---|---|
| F-02 | P1 | E-01 | 6건 | 평균 재시도 횟수 증가 | avg_retry: V0=0.25 / V1=1.75 · Δ+1.50 · (임계 +1.50회 >= 임계 0.50회) |
| F-05 | P2 | E-02 | 20건 | 평균 토큰 사용량 증가 | avg_tokens: V0=2.42e+03 / V1=3.25e+03 · Δ+34.6% · (임계 +34.6% >= 임계 15.0%) |
| F-06 | P2 | E-03 | 20건 | 평균 응답 지연 증가 | avg_latency_ms: V0=3.4e+03 / V1=4.74e+03 · Δ+39.2% · (임계 +39.2% >= 임계 20.0%) |
| F-07 | P2 | E-04 | 20건 | 평균 Trace 단계 수 증가 | avg_step_count: V0=5 / V1=8.3 · Δ+66.0% · (임계 +66.0% >= 임계 20.0%) |

---

## 4. Trace Diff

Trace는 있지만 첫 분기 지점을 계산한 Finding이 없음 (regression 없음).

---

## 5. Recommendation

준비 중 (P6 수정 후보 생성 전).

---

## 6. Risk & Limits

재검증 이력 없음 (P7 이전이거나 아직 후보를 적용하지 않음).

**이 보고서가 말하지 못하는 것**

- TestCase 20개 · 반복 2회 기준이므로 통계적 일반화는 주장하지 않음
