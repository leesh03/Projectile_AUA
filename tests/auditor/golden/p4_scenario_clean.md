# Agent Upgrade Risk Report

| 항목 | 내용 |
|---|---|
| report_id | rpt_scenario_clean |
| bundle_id | audit_mock_scenario_clean |
| 생성 시각 | 2026-08-15 12:00:00+00:00 |
| **판정** | **PASS** |

---

## 1. Summary

| 지표 | V0 | V1 | 변화 |
|---|---|---|---|
| 성공률 (success_rate) | 100.0% | 100.0% | +0.0pp |
| Tool 오류율 (tool_error_rate) | 0.0% | 0.0% | +0.0pp |
| 평균 재시도 (avg_retry) | 0.25 | 0.25 | +0.00 |
| 평균 토큰 (avg_tokens) | 2,398 | 2,472 | +3.1% |
| 평균 지연 ms (avg_latency_ms) | 3,393 | 3,456 | +1.8% |
| 안전 위반 건수 (safety_violation) | 0 | 0 | +0 |

testcase 20개 · trial 2회 기준.

---

## 2. Regression

해당 없음.

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
