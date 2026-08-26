# Agent Upgrade Risk Report

| 항목 | 내용 |
|---|---|
| report_id | rpt_scenario_b |
| bundle_id | audit_mock_scenario_b |
| 생성 시각 | 2026-08-15 12:00:00+00:00 |
| **판정** | **PASS** |

---

## 1. Summary

| 지표 | V0 | V1 | 변화 |
|---|---|---|---|
| 성공률 (success_rate) | 100.0% | 100.0% | +0.0pp |
| Tool 오류율 (tool_error_rate) | 0.0% | 0.0% | +0.0pp |
| 평균 재시도 (avg_retry) | 0.00 | 0.00 | +0.00 |
| 평균 토큰 (avg_tokens) | 2,401 | 2,567 | +6.9% |
| 평균 지연 ms (avg_latency_ms) | 3,429 | 3,575 | +4.2% |
| 안전 위반 건수 (safety_violation) | 0 | 0 | +0 |

testcase 20개 · trial 2회 기준.

---

## 2. Regression

| Finding | 심각도 | rule_id | 유형 | 영향 케이스 | 내용 | 근거 |
|---|---|---|---|---|---|---|
| F-01 | P1 | O-01 | OPTIMIZATION_OPPORTUNITY | 20건 (case_01, case_02, case_03, case_04, case_05 외 15건) | Verifier가 20개 케이스 전체에서 판정을 한 번도 바꾸지 않음 (조건부로 끄면 케이스당 LLM 호출 약 1회, 현재 평균 4.0회 절감 추정) | verifier_intervention_rate: V0=0 / V1=0 · (임계 intervention_rate == 0.0 (표본 40건)) |

---

## 3. Efficiency

| Finding | 심각도 | rule_id | 영향 케이스 | 내용 | 근거 (임계값 포함) |
|---|---|---|---|---|---|
| F-02 | P2 | E-04 | 20건 | 평균 Trace 단계 수 증가 | avg_step_count: V0=3 / V1=4 · Δ+33.3% · (임계 +33.3% >= 임계 20.0%) |

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
