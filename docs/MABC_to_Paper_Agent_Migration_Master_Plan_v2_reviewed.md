# MABC 대회 → AI 학회 논문 확장을 위한 Agent Migration 프로젝트 마스터 개발 계획 v2 (재검토본)

> **프로젝트 핵심 방향**  
> 대회에서는 “AI 업무자동화 Agent를 업데이트할 때 무엇이 망가졌고 무엇을 줄일 수 있는지 점검해 주는 실용 서비스”를 만들고,  
> 논문에서는 이를 “Foundation Model 교체 전후의 paired execution trace를 이용해 regression과 obsolete scaffold를 동시에 탐지하고, 제한된 구조 변경을 재검증하는 Model-Aware Agent Migration 방법”으로 확장한다.

- 작성 기준일: 2026-08-12
- 재검토 버전: **v2 — 대회/논문/실험설계 재검증 완료**
- 현재 단계: 기존 `AI 모델 발전에 맞춘 Agent Migration·Optimization 시스템` 기획을 대회/논문 이중 목적에 맞게 재설계
- 대회: MABC 2026 (Making AI Beneficial Challenge)
- 대회용 가칭: **Agent Upgrade Auditor — AI 업무자동화 업그레이드 점검 Agent**
- 논문용 가칭: **ModelShift: Differential Trace-Guided Migration and Scaffold Optimization for LLM Agents**
- 논문 제목 후보:
  - **When Better Models Break Agents: Differential Trace-Guided Migration and Scaffold Optimization for LLM Agents**
  - **ModelShift: Regression-Aware Migration of LLM Agents under Foundation Model Upgrades**
  - **Beyond Model Swapping: Model-Aware Agent Migration with Differential Traces and Scaffold Simplification**


## v2 재검토에서 확정한 핵심 수정사항

이 문서는 기존 계획을 다시 검토하면서 다음 사항을 보강한 버전이다.

1. **대회용과 논문용을 같은 코어에서 발전시키는 전략은 유지한다.** 방향을 갈아엎을 필요는 없다.
2. MABC 예선은 연구 프레임워크 전체가 아니라 **변경 전후 AI 업무자동화 결과를 점검하는 단일 Skill**에 집중한다.
3. 논문의 1차 비교는 반드시 **Locked-Harness Protocol**로 수행한다. 즉 `M_old → M_new` 외에는 처음에 아무것도 바꾸지 않는다.
4. 논문 novelty를 단순 `Agent optimization`이나 `trace debugging`에 두지 않는다. 2026년에는 HarnessFix, VeRO, Harness-Bench, HarnessOpt-Bench, Evo-Bench 등 인접 연구가 이미 빠르게 발전하고 있다.
5. 기존의 정적 `Counterfactual Replay`는 핵심 인과 증거로 사용하지 않는다. 모델 교체 후 trajectory가 달라질 수 있으므로 **환경 상태를 복원한 Branching Counterfactual Rollout**을 사용한다.
6. `Capability-Induced Scaffold Redundancy`는 새 모델에서만 component를 제거해 보는 것으로 주장하지 않는다. **Old/New Model × Scaffold On/Off의 2×2 실험**으로 모델 발전 때문에 불필요해졌는지를 분리한다.
7. stochastic Agent에서 단일 PASS→FAIL 한 번을 곧바로 regression으로 정의하지 않는다. testcase별 성공확률 차이와 불확실성을 함께 본다.
8. 논문 첫 버전의 핵심 contribution을 욕심내서 너무 넓히지 않는다. **Migration Risk + Differential Diagnosis + CISR + Live Re-validation**을 핵심으로 하고, 범용 자동 optimizer/대규모 benchmark는 확장 항목으로 둔다.

> **v2의 판단:** 프로젝트 주제는 유지할 가치가 충분하다. 다만 논문에서 강해지려면 “더 좋은 Agent를 자동으로 만든다”가 아니라, **모델 교체라는 특정 lifecycle event에서 무엇이 망가지고 무엇이 비로소 불필요해지는지를 통제된 실험으로 규명한다**는 축을 끝까지 유지해야 한다.

---

# 0. 이 문서의 결론부터

이 프로젝트는 **대회용과 논문용을 완전히 독립적으로 만들지 않는다.**

가장 좋은 전략은 다음과 같다.

```text
[MABC 대회]
AI Agent Upgrade Auditor
- 사용자가 이해하기 쉬운 업무 문제
- 단일 기능 중심
- 버전 A/B 비교
- 회귀(regression) 발견
- 낭비되는 단계 발견
- 안전한 개선안 추천
- 결과를 한 화면에 보여주는 서비스
          │
          │ 공통 Core를 유지
          ▼
[논문]
Model-Aware Agent Migration
- Old Model → New Model을 명시적 연구 사건으로 정의
- Paired Differential Trace
- Migration-induced Regression Localization
- Capability-induced Scaffold Redundancy Detection
- Scoped Intervention
- Candidate Search + Regression-aware Validation
- Multi-model / Multi-agent Benchmark
- Baseline / Ablation / 통계 검증
```

즉, **대회는 “쓸 수 있는 제품”을 만드는 단계**, **논문은 그 제품의 핵심 원리를 검증 가능한 연구 문제로 만드는 단계**다.

대회 때 만드는 코드를 나중에 버리지 않기 위해 처음부터 아래 모듈은 공통 코어로 설계한다.

1. TestCase
2. AgentVersion
3. Test Runner
4. Trace Collector
5. Evaluation
6. Version Comparison
7. Candidate Change
8. Validation
9. Report

반대로 다음은 대회와 논문에서 분리한다.

- 대회: 사용자 경험, 데모, Timely AI Skill, Dashboard, 설명 가능성
- 논문: 모델 migration pair, 연구 질문, benchmark, baseline, ablation, 통계, causal intervention

---

# 1. 원래 프로젝트에서 무엇을 유지하고 무엇을 바꿀 것인가

기존 프로젝트의 핵심 아이디어는 유지한다.

## 유지할 핵심

기존 방향의 좋은 부분은 다음과 같다.

- Agent를 단순히 “모델 하나”로 보지 않는다.
- 모델 교체 전후의 Agent 전체 행동을 비교한다.
- 최종 정답뿐 아니라 중간 실행 Trace를 저장한다.
- regression뿐 아니라 새 모델에서 불필요해진 검증·재시도·고비용 호출도 찾는다.
- Agent가 임의로 전체 코드를 재작성하게 하지 않고 수정 범위를 제한한다.
- 후보 변경은 반드시 동일 평가로 재시험한다.
- 품질, 안전성, 비용, 속도를 함께 평가한다.
- 작은 통제 Agent에서 시작한 뒤 실제 외부 Agent로 확장한다.

이 방향은 그대로 가져간다.

## 바꿀 부분

현재 기획은 대회 MVP로는 범위가 너무 크고, 논문 novelty로는 연구 질문이 넓다.

따라서 다음처럼 분리한다.

### 대회에서는

**“모델이 발전하면 Agent 구조도 최적화하자”라는 연구 주장 자체를 앞에 세우지 않는다.**

대회 심사에서는 사용자가 체감할 문제를 먼저 보여준다.

> “AI 업무자동화를 조금 수정했거나 업그레이드했는데, 기존에 되던 일이 망가지지 않았는지 사람이 일일이 확인하기 어렵다.”

이를 해결하는 **Agent 변경 영향 점검 서비스**로 제시한다.

### 논문에서는

“Agent Optimization”이라는 넓은 문제를 버리고 다음으로 좁힌다.

> **Foundation Model Migration이라는 특정 변화가 Agent에 만드는 behavioral regression과 redundant scaffolding을 어떻게 찾고 수정할 것인가?**

논문의 중심은 일반적인 workflow search가 아니라 **migration-conditioned adaptation**이다.

---

# 2. 왜 MABC용과 논문용을 같은 축으로 가져가야 하는가

완전히 독립적으로 만들면 다음 문제가 생긴다.

```text
대회 프로젝트 A 개발
+
논문 프로젝트 B 개발
=
Agent 실행기, 평가기, 로그, 테스트, UI, 데이터 등을 사실상 두 번 개발
```

반면 공통 코어를 공유하면 다음과 같이 누적된다.

```text
대회에서 만든 것
├─ Agent 실행
├─ TestCase
├─ 결과 저장
├─ A/B 비교
├─ Trace
├─ 비용/시간 집계
└─ 개선안 재시험
        ↓
논문에서 추가
├─ 여러 모델 pair
├─ 여러 Agent
├─ 자연 발생 regression 수집
├─ root-cause intervention
├─ benchmark
├─ baseline
├─ ablation
└─ 통계 검증
```

따라서 **개발 공부 → 대회 → 연구 → 포트폴리오**가 한 방향으로 쌓인다.

---

# PART I. MABC 2026 대회용 프로젝트

# 3. MABC 2026에서 반드시 고려해야 할 공식 조건

MABC 2026 공식 페이지 기준으로 대회는 다음 2단계다.

## 예선

- 기간: 2026-08-18 ~ 2026-08-31
- 환경: Timely AI + Upstage Solar
- 핵심 미션: **일상/업무의 사소한 불편을 해결하는 단일 기능 중심 AI Agent Skill**
- 결과물: AI Agent Skill
- 결선 진출: 50팀

## 결선

- 전체 결선 일정: 2026-09-09 ~ 2026-09-19
- 온라인 개발·제출: 2026-09-09 ~ 2026-09-18
- 최종 발표: 2026-09-19
- 핵심 미션: 예선 Agent를 확장하여 **누군가 실제로 사용할 수 있는 Agent 서비스 MVP** 완성

따라서 예선에서 “Agent 연구 프레임워크 전체”를 구현하려 하면 대회의 형식과 맞지 않는다.

대회 전략은:

> **예선 = 변경된 AI 업무자동화의 품질을 빠르게 점검하는 하나의 Skill**  
> **결선 = 테스트 실행·비교·개선·재검증을 묶은 Upgrade Auditor 서비스**

로 잡는 것이 좋다.

공식 근거:
- MABC 2026: https://www.upstage.ai/mabc-2026

---

# 4. 대회용 최종 주제

## 추천 주제명

### 한글

**AI 업무자동화 업그레이드 점검 Agent**

### 영어

**Agent Upgrade Auditor**

### 부제

> 기존 AI 업무자동화를 수정·업그레이드했을 때, 무엇이 망가졌고 무엇을 단순화할 수 있는지 자동 점검해 주는 AI Agent

---

# 5. 대회에서 해결할 “사용자의 불편”을 정확하게 정의

대회에서는 다음 사용자를 상정한다.

## 1차 사용자

- 사내 AI 자동화를 만드는 직장인
- 반복 업무를 Agent/노코드 자동화로 만든 사람
- Prompt/Skill/Tool 설정을 자주 수정하는 사람
- AI Agent를 만들었지만 전문적인 테스트 시스템은 없는 사람

## 사용자의 실제 불편

AI Agent를 만든 뒤 다음과 같은 변경이 생긴다.

- Prompt 수정
- Tool 설명 수정
- 업무 정책 수정
- Workflow 순서 수정
- Agent Skill 수정
- 사용하는 AI 모델 또는 모델 설정 변경
- 비용 절감을 위한 구조 단순화

그런데 변경 후에는 다음 문제가 생긴다.

```text
“이전에는 됐던 일이 지금도 되나?”
“10개 업무를 다시 손으로 테스트해야 하나?”
“답은 맞는데 왜 갑자기 느려졌지?”
“검증 단계를 줄여도 되나?”
“Prompt를 고쳤더니 다른 문제가 망가지지는 않았나?”
```

현재 이런 검증을 사람이 수동으로 하면 반복적이고 귀찮다.

따라서 대회에서는 다음 한 문장을 중심으로 한다.

> **AI Agent를 고친 뒤 사람이 일일이 재검사해야 하는 불편을 줄인다.**

---

# 6. 대회용 핵심 기능은 하나여야 한다

예선에서 보여줄 핵심 기능은 이것 하나다.

## “Before / After Agent Change Audit”

입력:

```text
기존 버전 V0 결과
변경 버전 V1 결과
동일한 TestCase
```

출력:

```text
1. 기존에 되던 것이 새로 실패한 사례
2. 새 버전에서 개선된 사례
3. 도구/재시도/단계 증가 등 비효율
4. 줄여도 될 가능성이 있는 중복 절차
5. 우선 수정할 항목
6. 최종 Upgrade Risk Report
```

예선에서는 이 기능이 확실하게 작동하면 된다.

---


## 6.1 대회에서 “AI가 왜 필요한가”를 분명히 한다

이 서비스가 단순한 숫자 diff 도구처럼 보이면 안 된다. 대회용 Skill에서 Solar가 맡을 핵심 역할은 다음과 같이 한정한다.

### AI가 맡는 부분

- 여러 TestCase의 변경 패턴을 읽고 **같은 유형의 regression을 묶는다.**
- 최종 실패뿐 아니라 tool error, retry 증가, 단계 증가 등의 로그를 보고 **우선 조사할 증상 후보를 순위화한다.**
- 사용자가 이해할 수 있는 언어로 **변경 위험과 영향 범위를 설명한다.**
- 허용된 수정 범위 안에서 **최소 수정안 1~3개를 제안한다.**
- 수정 후 결과가 들어오면 이전 결과와 비교해 **회복 여부를 설명한다.**

### 가능하면 코드/규칙으로 처리할 부분

- 성공/실패 개수 집계
- 토큰/latency/retry 합계 및 차이
- JSON schema validity
- 금지 tool/SQL 여부
- 명확한 PASS/FAIL 판정

즉 대회에서 AI의 가치는 **“숫자를 계산하는 것”이 아니라, 변경 전후의 여러 실행 기록에서 사람이 놓치기 쉬운 패턴을 찾아 우선순위를 정하고 다음 행동을 제안하는 것**이다.

이렇게 해야 단순 QA dashboard가 아니라 MABC의 **AI Agent Skill**로 설명하기 쉽다.

# 7. MABC 환경 제약을 고려한 3단계 구현 방식

Timely AI가 대회에서 정확히 어떤 외부 API 호출, 다른 Agent 호출, 실행 로그 접근 기능을 제공하는지는 공식 대회 페이지만으로 모두 확인되지 않는다.

따라서 플랫폼 기능에 따라 프로젝트가 무너지지 않도록 세 단계로 설계한다.

## Level 0 — 가장 안전한 예선 구현

사용자가 다음 정보를 Agent Upgrade Auditor에 넣는다.

- TestCase
- V0의 실행 결과
- V1의 실행 결과
- 선택적으로 단계별 로그

Auditor가 비교 보고서를 만든다.

장점:

- Timely AI의 복잡한 외부 연동에 의존하지 않는다.
- 예선 “단일 Skill”로 만들기 쉽다.
- 문제 정의와 핵심 가치를 보여줄 수 있다.

## Level 1 — Timely가 다른 실행을 호출/연동할 수 있는 경우

Auditor가 V0/V1 Agent를 직접 같은 TestCase로 실행한다.

```text
TestCase
  ├→ V0 실행
  └→ V1 실행
       ↓
자동 비교
```

## Level 2 — 결선 서비스

별도 Runner/Backend를 붙일 수 있다면 다음을 자동화한다.

```text
Test Suite
   ↓
Repeated Runner
   ↓
V0 / V1
   ↓
Trace + Metric
   ↓
Regression Audit
   ↓
Candidate
   ↓
Re-test
   ↓
Migration Report
```

**중요:** Level 2를 예선 필수조건으로 잡지 않는다.

---

# 8. 대회 데모에 사용할 예비 Agent

대회와 논문 모두를 고려하면 기존에 기획한 **질의·정책 검증 Agent**가 좋다.

## 업무 시나리오

전자상거래 회사 CS 직원이 다음 질문을 한다.

> “주문 A-10293이 아직 도착하지 않았는데 지금 환불할 수 있나요?”

Agent는:

1. 질문 유형 분류
2. 주문 정보 조회
3. SQL 생성
4. 읽기 전용 검사
5. DB 실행
6. 관련 정책 검색
7. 데이터와 정책 비교
8. 승인/거절/추가정보 필요 판정
9. 답변 생성

을 수행한다.

이 Agent가 좋은 이유:

- 정답 SQL을 만들 수 있음
- 정책 판정의 정답을 코드로 정의할 수 있음
- tool call이 있음
- 잘못된 argument가 명확함
- retry가 있음
- verifier가 있음
- latency/token/cost 비교가 가능함
- 여러 수준의 난이도를 만들 수 있음

---

# 9. 대회에서 반드시 보여줄 3개의 대표 시나리오

## 시나리오 A — 변경 후 regression 발생

### V0

정상적으로 다음 tool call을 보낸다.

```json
{
  "order_id": "A-10293"
}
```

### V1

Agent Prompt/Tool Description을 수정한 뒤 일부 요청에서:

```json
{
  "id": "A-10293"
}
```

처럼 schema에 없는 필드를 보낸다.

### Auditor가 발견

```text
Regression detected

Tool argument validity
V0: 100%
V1: 78%

최초 주요 차이:
ORDER_LOOKUP tool invocation

추천:
- tool schema example 추가
- 필수 field validator 추가
```

대회의 포인트는 **“V1이 이상하다”가 아니라 어디에서 무엇이 달라졌는지 보여주는 것**이다.

---

## 시나리오 B — 새 버전에서 불필요한 검증 발견

V0:

```text
SQL 생성
→ LLM SQL 검토
→ 코드 문법 검사
→ 실행
```

V1에서는 SQL 생성 정확도가 충분히 높고 코드 검사에서 오류를 확실히 잡는다고 하자.

Auditor는:

```text
LLM SQL Review 단계는 30/30 테스트에서
결과를 변경하지 않았음.

예상 제거 효과
- LLM call: -1 / request
- token: 감소
- latency: 감소
```

를 보여준다.

다만 대회에서는 “무조건 제거”라고 하지 않고:

> **제거 후보 → 재시험 통과 시 적용 가능**

이라고 한다.

---

## 시나리오 C — retry가 지나치게 많아짐

V0:

```text
평균 Retry 0.3회
```

V1:

```text
평균 Retry 1.8회
동일한 오류를 최대 5회 반복
```

추천:

```text
동일 오류 2회 발생 시
같은 prompt로 재시도하지 않고
fallback 또는 사용자 확인으로 전환
```

이를 재시험해서:

```text
성공률 유지
평균 Retry 감소
latency 감소
```

를 보여준다.

---

# 10. 대회용 제품의 화면 구조

결선까지 갔을 때 Dashboard는 복잡할 필요가 없다.

## 화면 1 — Agent Version 등록

```text
Agent Name
Version V0
Version V1
변경 내용
Test Suite
```

## 화면 2 — Test 실행

```text
30 / 30 complete

V0 Success 90%
V1 Success 83%
```

## 화면 3 — Change Summary

```text
REGRESSION
- 3 cases

IMPROVEMENT
- 2 cases

EFFICIENCY WARNING
- retry +43%
- token +21%

OPTIMIZATION OPPORTUNITY
- redundant verifier candidate
```

## 화면 4 — Trace Diff

```text
V0
N1 → N2 → N3 → Tool OK → N5

V1
N1 → N2 → N3 → Tool FAIL → Retry → Tool FAIL
                    ↑
              First major divergence
```

## 화면 5 — Recommendation

```text
Candidate C1
Tool schema example 추가

Candidate C2
Argument validator 추가

Candidate C3
Retry 5 → 2
```

## 화면 6 — Re-validation

```text
Candidate C2

Success: 83 → 92%
Tool Error: 22 → 0%
Token: -8%
Safety violation: 0

Recommendation: PASS
```

---

# 11. 대회에서 주장하면 좋은 것과 주장하면 안 되는 것

## 주장하면 좋은 것

> 기존 Agent 변경 전후를 동일 TestCase에서 자동 비교한다.

> 최종 답만이 아니라 tool/error/retry/step 정보를 함께 확인한다.

> 수정 전보다 품질이 나빠진 사례를 빠르게 찾는다.

> 불필요한 검증/재시도 후보를 발견한다.

> 추천한 변경은 반드시 다시 시험한다.

## 아직 주장하면 안 되는 것

> 모든 Agent를 자동으로 최적화한다.

> 어떤 Foundation Model이든 자동 migration한다.

> 진짜 causal root cause를 항상 정확히 찾는다.

> AI가 Agent 코드 전체를 안전하게 자동 수정한다.

> 모든 workflow에서 최적 구조를 찾는다.

> 사람보다 항상 더 좋은 Agent를 만든다.

대회에서 과장하면 오히려 신뢰도가 떨어진다.

---

# 12. 예선에서 반드시 구현할 것

## Must

- Timely AI에서 동작하는 Agent Upgrade Audit Skill
- V0/V1 비교 입력 형식
- 최소 10~20 TestCase
- Regression 분류
- Improvement 분류
- 비용/단계/재시도 같은 효율 비교
- 우선 확인할 문제 1~3개 제시
- 결과를 사람이 바로 이해할 수 있는 보고서 형식으로 출력
- 한 개의 대표 demo dataset

## Should

- Trace 형태의 단계 비교
- 최소 1개의 Optimization Opportunity
- Candidate 수정안
- 수정 후 결과 재입력 시 before/after 재평가

## Could

- 자동 Runner
- Dashboard
- API 연결
- 반복 실행
- 통계적 불확실성
- 자동 candidate 적용

예선에서 Could 때문에 Must가 미완성되는 것을 금지한다.

---

# 13. 결선 진출 시 추가할 기능

## 결선 Must

- Test Runner
- Agent Version 저장
- 실행 결과 자동 수집
- V0/V1 반복 평가
- Trace Diff
- 최소 3종류의 문제 유형
- 수정 Candidate 2~3종
- Re-validation
- 결과 Dashboard
- Demo Replay

## 결선 Nice-to-have

- 난이도 기반 routing
- 비용 최적화
- 조건부 verifier
- prompt caching 관련 실험
- 다른 Agent 1개 추가
- 자동 PDF/Markdown Migration Report

---

# 14. 대회 3분 발표 스토리

## 0:00~0:30 — 문제

> “회사에서 AI Agent를 운영하다가 Prompt나 Skill을 조금 수정하면, 기존 업무 30개를 사람이 다시 확인해야 합니다.”

## 0:30~1:00 — 기존/변경 Agent 실행

V0와 V1을 같은 TestCase로 실행.

## 1:00~1:40 — 문제 발견

Dashboard:

```text
Success -7%p
Tool Error +18%p
Retry +1.2
```

그리고 Trace에서 최초 차이를 표시.

## 1:40~2:10 — 개선 후보

```text
Tool example 추가
Argument validator 추가
Retry 조건 변경
```

## 2:10~2:40 — 재검증

```text
Success 회복
Cost 감소
Safety 유지
```

## 2:40~3:00 — 확장성

> “AI 자동화가 늘어날수록 만드는 것만큼 업데이트 후 검증도 중요해집니다. Agent Upgrade Auditor는 AI 업무자동화의 변경을 더 안전하고 빠르게 만드는 도구입니다.”

---

# PART II. 대회와 논문이 공유할 공통 기술 코어

# 15. 처음부터 공통 Core를 분리해서 개발해야 한다

추천 구조:

```text
project/
├─ apps/
│  ├─ mabc_skill/
│  └─ dashboard/
│
├─ core/
│  ├─ schemas/
│  ├─ runner/
│  ├─ trace/
│  ├─ evaluator/
│  ├─ diff/
│  ├─ detector/
│  ├─ candidate/
│  └─ validation/
│
├─ agents/
│  ├─ policy_query_agent/
│  └─ adapters/
│
├─ datasets/
│  ├─ dev/
│  ├─ validation/
│  └─ test/
│
├─ experiments/
│  ├─ mabc/
│  └─ research/
│
└─ reports/
```

핵심 원칙:

> **MABC UI가 없어도 core가 실행되어야 한다.**

그래야 대회 이후 UI를 버리고 연구 코드만 사용할 수 있다.

---

# 16. 공통 데이터 구조

## TestCase

```json
{
  "testcase_id": "refund_001",
  "input": "주문 A-10293이 아직 도착하지 않았습니다. 환불할 수 있나요?",
  "difficulty": "easy",
  "expected_tools": ["order_lookup"],
  "expected_policy": "refund_delayed_shipping",
  "gold_decision": "eligible",
  "safety_constraints": [
    "read_only_db"
  ]
}
```

## AgentVersion

```json
{
  "agent_id": "policy_agent",
  "version": "v0",
  "model_id": "MODEL_A",
  "prompt_version": "p1",
  "tool_schema_version": "t1",
  "workflow_version": "w1",
  "retry_policy": "r1",
  "verifier_policy": "v1",
  "commit": "..."
}
```

## TraceStep

```json
{
  "run_id": "...",
  "step_index": 4,
  "node": "sql_generation",
  "type": "llm_call",
  "model": "MODEL_A",
  "input_hash": "...",
  "output_summary": "...",
  "tool_name": null,
  "error_type": null,
  "input_tokens": 521,
  "output_tokens": 117,
  "latency_ms": 860,
  "observation_hash": "...",
  "environment_state_hash": "...",
  "checkpoint_id": "optional-checkpoint-id"
}
```

## EnvironmentCheckpoint — 논문용 intervention을 위해 추가

대회 MVP에서는 선택사항이지만 논문용 controlled Agent에서는 가능한 한 저장한다.

```json
{
  "checkpoint_id": "cp_refund_001_n2_trial3",
  "run_id": "...",
  "before_node": "sql_generation",
  "db_version": "db_v3",
  "workspace_snapshot": "...",
  "retrieved_context_hash": "...",
  "retry_state": 0,
  "tool_state_hash": "...",
  "restorable": true
}
```

이 구조가 있어야 논문에서 static log replay가 아니라 **checkpoint에서 실제 branch를 다시 실행하는 intervention**이 가능하다.

## ToolStep

```json
{
  "node": "order_lookup",
  "tool_name": "order_lookup",
  "arguments": {
    "order_id": "A-10293"
  },
  "schema_valid": true,
  "execution_success": true
}
```

## TrialResult

```json
{
  "testcase_id": "refund_001",
  "agent_version": "v1",
  "trial": 3,
  "task_success": true,
  "policy_correct": true,
  "tool_error_count": 0,
  "retry_count": 1,
  "total_tokens": 2401,
  "latency_ms": 3400,
  "safety_violation": false
}
```

---

# 17. Trace는 처음부터 “논문 가능한 형태”로 저장한다

단순 로그 문자열만 저장하면 나중에 논문에서 다시 구현해야 한다.

최소한 다음은 구조화해서 저장한다.

### Identity

- experiment_id
- run_id
- testcase_id
- agent_id
- agent_version
- model_id
- provider / exact API model ID
- API/client library version
- seed/temperature/top-p 가능하면 저장
- reasoning effort / max tokens / tool-choice mode 등 runtime config
- timestamp

### Execution

- node
- step_index
- action type
- tool
- arguments
- output status
- tool observation / observation hash
- environment state hash / checkpoint ID 가능하면
- error
- retry

### Resource

- input tokens
- output tokens
- LLM calls
- tool calls
- latency

### Outcome

- task success
- gold comparison
- safety violation
- policy correctness

### Version

- prompt hash
- tool schema hash
- workflow hash
- code commit

이 데이터가 논문의 핵심 자산이 된다.

---

# 18. 평가기는 LLM Judge에만 의존하지 않는다

가능한 항목은 deterministic evaluator를 쓴다.

## Deterministic

- SQL 결과
- DB row
- 정책 decision
- JSON schema
- 필수 argument
- 금지 SQL
- tool selection
- retry count
- execution step
- token/cost
- latency

## LLM Judge를 쓸 수 있는 항목

- 최종 답변 설명의 명확성
- 근거 설명 품질
- 사용자 친화성

논문 핵심 결과를 LLM Judge 하나에 의존하면 평가 신뢰성이 약해진다.

---

# PART III. 논문용으로 어떻게 확장할 것인가

# 19. 논문에서 문제 정의를 완전히 다시 쓴다

대회:

> Agent를 업데이트했을 때 문제를 점검해 주는 서비스

논문:

> **기존 Agent의 Foundation Model을 새로운 모델로 교체했을 때 발생하는 행동 회귀와 구조적 중복을 paired execution traces로 탐지하고, 최소 범위의 구조 수정으로 품질·안전성을 유지하면서 효율적인 migration configuration을 찾는 문제**

이 차이가 매우 중요하다.

---

# 20. 논문의 핵심 연구 객체

Agent를 다음과 같이 본다.

```text
A = (M, P, T, W, V, R, G)
```

- M: Foundation Model
- P: Prompt / Instruction
- T: Tool definitions
- W: Workflow / control flow
- V: Verification
- R: Retry / recovery
- G: Routing / gating

기존 Agent:

```text
A_old = (M_old, P0, T0, W0, V0, R0, G0)
```

단순 모델 교체:

```text
A_swap = (M_new, P0, T0, W0, V0, R0, G0)
```

우리 연구가 찾으려는 최종 구성:

```text
A_migrated = (M_new, P*, T*, W*, V*, R*, G*)
```

단, `*`는 무엇이든 자유롭게 바꾸는 것이 아니라 **허용된 수정 연산자의 제한된 공간**에서만 찾는다.

---

# 21. 논문의 최적화 목적 — Weighted Score보다 Constraint + Pareto로 정의

핵심은 “정확도 최대화”도 아니고, 임의의 가중치 `α, β, γ`를 정해 하나의 점수로 줄이는 것도 아니다.

논문 1차 버전에서는 **비열등성(non-inferiority) 제약을 먼저 통과시킨 뒤 효율을 비교**하는 방식이 더 설득력 있다.

## 21.1 품질 제약

각 migrated configuration `A`에 대해 사전에 정한 margin `ε_q`를 사용한다.

```text
Quality(A) >= Quality(A_old) - ε_q
```

`ε_q`는 결과를 본 뒤 편의적으로 고르지 않고 **실험 전에 고정**한다.

## 21.2 안전 제약

```text
SafetyViolation(A) <= allowed_threshold
```

중요한 안전 위반은 hard constraint로 두고, 허용하지 않는 항목은 0건을 요구한다.

## 21.3 품질·안전을 통과한 후보끼리 비교

그 다음 다음 지표를 최소화한다.

- API Cost
- Total Tokens
- Latency
- LLM Calls
- Retry Count
- Scaffold Complexity
- Change Size

즉 결과는 하나의 임의 weighted score보다 **Pareto frontier** 또는 lexicographic rule로 보고하는 것이 좋다.

예:

```text
1순위: Quality/Safety gate 통과
2순위: Regression 최소
3순위: Cost/Latency 감소
4순위: 변경 규모가 작은 후보 선호
```

이렇게 하면 “가중치를 바꾸면 결론도 바뀌는 것 아닌가?”라는 리뷰어 공격을 줄일 수 있다.

---

# 22. 논문의 가장 중요한 Research Questions

## RQ1 — Model Migration Risk

> 더 강하거나 최신인 Foundation Model로 교체하면 기존 Agent의 성능도 항상 향상되는가?

측정:

- task success
- tool correctness
- retry
- safety
- latency
- cost
- behavioral consistency

예상:

> 아니다. 일반 성능 향상과 특정 Agent workflow 성능은 단조 관계가 아닐 수 있다.

---

## RQ2 — Differential Trace Localization

> Old/New model의 paired execution trace를 비교하면 최종 outcome만 사용하는 방법보다 migration-induced regression의 발생 위치를 더 정확히 찾을 수 있는가?

비교:

```text
Output-only
vs
Single-trace diagnosis
vs
Paired differential trace
```

평가:

- root cause Top-1
- Top-3
- localization distance
- repair success

---

## RQ3 — Capability-Induced Scaffold Redundancy (CISR)

> **새 모델에서 어떤 scaffold가 제거 가능해졌다면, 그것이 정말 새 모델의 capability 향상 때문에 생긴 현상인가?**

이 질문은 단순히 `New Model + verifier OFF`가 잘 되는지만 보면 답할 수 없다.

왜냐하면 그 verifier가 **Old Model에서도 원래 필요 없었을 수 있기 때문**이다.

따라서 component `c`마다 최소한 다음 2×2 실험을 한다.

| | Scaffold ON | Scaffold OFF |
|---|---|---|
| **Old Model** | `Q_old,on` | `Q_old,off` |
| **New Model** | `Q_new,on` | `Q_new,off` |

정의:

```text
Δ_old(c) = Q_old,off - Q_old,on
Δ_new(c) = Q_new,off - Q_new,on
```

우리가 찾고 싶은 패턴은 다음과 같다.

```text
Old Model: component 제거 시 의미 있는 품질 하락
New Model: component 제거 후에도 non-inferior
New Model: token / latency / call 수는 감소
```

즉 단순 removal success가 아니라 **Model × Scaffold interaction**을 본다.

Difference-in-Differences 형태의 보조량:

```text
CISR_effect(c) = Δ_new(c) - Δ_old(c)
```

`CISR_effect`가 양수이고, New Model에서 품질·안전 non-inferiority를 만족하면서 효율이 개선되면 해당 component를 **migration-induced removal candidate**로 본다.

측정:

- old/new 각각의 quality drop
- interaction effect와 bootstrap CI
- 제거 가능한 LLM calls
- token/cost/latency 감소
- safety 유지 여부
- hidden test에서의 non-inferiority

이 설계가 들어가야 **“새 모델이 좋아졌기 때문에 예전 scaffold가 비로소 필요 없어졌다”**라는 주장을 훨씬 강하게 할 수 있다.

---

## RQ4 — Scoped Migration vs Free-form Optimization

> 원인 위치를 찾고 제한된 수정 연산자만 적용하는 방식이 자유로운 Agent 재작성이나 무작위 workflow search보다 적은 실험으로 안전한 migration configuration을 찾는가?

측정:

- candidate evaluations until success
- total optimization tokens
- total optimization cost
- regression introduced
- final performance

---

## 선택 RQ5 — Generalization

> 동일한 migration 방법이 다른 Agent와 다른 model pair에서도 효과가 있는가?

논문 수준을 높이려면 추가한다.

---

# 23. 논문 novelty를 어디에 잡아야 하는가

2026년 현재 “Agent 자동 최적화”, “Trace 기반 Agent debugging”, “workflow search” 자체는 이미 활발한 연구 분야다.

따라서 논문의 novelty를 아래처럼 잡는다.

## Novelty 1 — Migration-conditioned Problem Formulation

기존:

> Agent를 더 좋게 만들어라.

우리:

> **M_old → M_new라는 구체적 lifecycle event가 발생했을 때 Agent harness를 어떻게 다시 맞출 것인가?**

---

## Novelty 2 — Paired Differential Trace

기존 debugging:

```text
Failed Trace
→ 어디가 문제인가?
```

우리:

```text
같은 TestCase
Old Model Trace
vs
New Model Trace
→ 모델 교체로 새로 생긴 divergence는 어디인가?
```

즉 absolute failure 분석보다 **change attribution**에 초점을 둔다.

---

## Novelty 3 — Regression + Capability Dividend 동시 탐지

Migration 후 발생하는 두 현상을 동시에 본다.

### Negative

```text
새 모델에서 망가진 것
```

### Positive

```text
새 모델이 좋아져서 더 이상 필요하지 않은 것
```

기존 프로젝트에서 말했던 “Optimization Opportunity”를 논문에서는 명확한 연구 개념으로 올린다.

추천 명칭:

- **Capability Dividend**
- **Capability-Induced Scaffold Redundancy**
- **Post-Migration Scaffold Simplification**

개인적으로 논문에서는 **Capability-Induced Scaffold Redundancy (CISR)**가 가장 기술적으로 명확하다.

---

## Novelty 4 — Scoped Migration Operators

수정 범위를 미리 제한한다.

예:

```text
OP1 Prompt instruction edit
OP2 Tool schema clarification
OP3 Argument validator insertion
OP4 Verifier removal
OP5 Conditional verifier
OP6 Retry threshold
OP7 Error-specific fallback
OP8 Node-level model routing
```

왜 중요한가:

- search space 감소
- 수정 원인 추적 가능
- rollback 가능
- 실험 재현성 향상

---

## Novelty 5 — Intervention-based Validation

“처음 달라진 노드”를 root cause라고 단정하지 않는다.

진단:

```text
N3이 원인 후보 Top-1
```

그 다음 intervention:

```text
I1: N3의 old-model output을 new-model run에 주입
I2: N3만 다른 model로 실행
I3: N3 schema를 보정
```

후속 실패가 사라지는지 본다.

이를 통해 단순 correlation보다 강한 근거를 만든다.

---

# 24. 반드시 비교해야 할 선행연구

## 24.1 RETAIN — LLM Migration Regression Testing

**RETAIN: Interactive Tool for Regression Testing Guided LLM Migration (2024)**

핵심:

- LLM migration에서 regression testing
- 모델 output 차이 탐색
- error difference 설명
- prompt refinement 지원
- 사용자 실험

우리와 가장 직접적으로 관련된 선행연구 중 하나다.

### 차별화해야 할 점

RETAIN 수준에서 멈추면 논문 신규성이 약하다.

우리 연구는:

- 단일 LLM output이 아니라 multi-step Agent
- tool call / retry / control-flow trace
- paired step-level differential analysis
- prompt뿐 아니라 verifier/retry/routing/tool description 수정
- redundant scaffold 탐지
- 자동 re-validation

까지 가야 한다.

링크:
https://arxiv.org/abs/2409.03928

---

## 24.2 Measuring Agents in Production

**Measuring Agents in Production (2025)**

중요 관찰:

실제 production Agent에서 팀들이 model migration의 behavioral shift 때문에 legacy/new model을 동시에 유지하는 사례가 관찰되었다.

즉 네 문제 정의의 산업적 필요성을 뒷받침한다.

논문에서 Motivation에 매우 좋은 근거다.

링크:
https://arxiv.org/abs/2512.04123

---

## 24.3 AFlow

**AFlow: Automating Agentic Workflow Generation (2024)**

핵심:

- Agent workflow optimization을 search problem으로 정의
- MCTS 기반 workflow 탐색
- 비용/성능 개선

차이:

- AFlow: 최적 workflow 탐색
- 우리: model migration이라는 변화의 원인에 조건화된 최소 적응

링크:
https://arxiv.org/abs/2410.10762

---

## 24.4 AgentDevel

**AgentDevel: Reframing Self-Evolving LLM Agents as Release Engineering (2026)**

핵심:

- Agent 개선을 release engineering 문제로 봄
- failure signal
- release candidate
- regression-aware gate
- auditable artifacts

겹치는 부분:

- versioning
- regression
- validation
- release gate

따라서 논문에서는 정면으로 비교해야 한다.

우리 차별점:

- self-evolution 일반 문제가 아니라 model migration event
- old/new paired differential trace
- redundant scaffold 탐지
- migration operator
- old model을 counterfactual baseline으로 활용

링크:
https://arxiv.org/abs/2601.04620

---

## 24.5 VeRO

**VeRO: An Evaluation Harness for Agents to Optimize Agents (2026)**

핵심:

- versioned agent snapshot
- budget-controlled evaluation
- structured trace
- optimizer agent 평가 harness

겹치는 부분:

- version
- evaluation
- trace
- optimization

우리 차별점:

- optimizer 자체의 일반 성능보다 migration-specific diagnosis
- old/new same-task paired difference
- regression + scaffold redundancy
- migration-specific evaluation

링크:
https://arxiv.org/abs/2602.22480

---

## 24.6 HarnessFix

**From Failed Trajectories to Reliable LLM Agents: Diagnosing and Repairing Harness Flaws (HarnessFix, 2026)**

핵심:

- failed trace
- normalized trace representation
- failure attribution
- harness layer diagnosis
- scoped repair
- regression validation

현재 네 주제와 가장 많이 겹치는 연구 중 하나다.

따라서 단순히:

```text
Trace → Root Cause → Repair → Validation
```

만 만들면 신규성이 부족할 수 있다.

차별점은 반드시:

```text
Old/New Model Pair
+
Migration-induced Differential Trace
+
Capability-Induced Redundancy
+
Minimal Model-aware Adaptation
```

으로 가져가야 한다.

링크:
https://arxiv.org/abs/2606.06324

---

## 24.7 AgentDebug / AgentDebugX

Agent failure를 root cause로 attribution하고 recover/re-run하는 방향.

우리 논문에서는 general debugging과 migration debugging을 구분한다.

링크:
https://arxiv.org/abs/2509.25370
https://arxiv.org/abs/2607.18754

---

## 24.8 Model End-of-Life Migration

**When Your LLM Reaches End-of-Life: A Framework for Confident Model Migration in Production Systems (2026)**

핵심:

- production LLM model replacement
- automated evaluation과 human judgment calibration
- confident replacement decision

차이:

- 이 연구는 replacement 모델의 품질 비교/평가가 중심
- 우리는 multi-step agent의 내부 behavior와 harness adaptation이 중심

링크:
https://arxiv.org/abs/2604.27082

---

## 24.9 Harness-Bench — Model × Harness 상호작용의 직접 근거

**Harness-Bench: Measuring Harness Effects across Models in Realistic Agent Workflows (2026)**

핵심:

- 동일한 현실적 Agent task에서 여러 model backend와 harness configuration을 비교
- 5,000개 이상의 execution trajectory 분석
- model-harness pairing에 따라 성능, 효율, 실패 양상이 크게 달라질 수 있음을 보임

우리에게 중요한 이유:

> “Agent 성능은 모델 하나가 아니라 model-harness configuration의 결과”라는 문제의식을 강하게 지지한다.

하지만 Harness-Bench는 **migration event 이후 무엇을 어떻게 수정할지**를 주 연구 질문으로 삼지 않는다.

링크:
https://arxiv.org/abs/2605.27922

---

## 24.10 HarnessOpt-Bench / Evo-Bench — Harness Optimization 자체는 이미 독립 연구영역

2026년 8월 기준으로 HarnessOpt-Bench와 Evo-Bench는 **LLM이 Agent harness를 얼마나 잘 개선할 수 있는가**를 직접 benchmark화한다.

따라서 우리 논문이 단순히:

```text
Trace → Agent 수정 → 점수 향상
```

을 보여주는 것만으로는 novelty가 약하다.

우리의 차별점은 다음으로 고정한다.

```text
특정 lifecycle event: M_old → M_new
+
Locked-harness paired comparison
+
Migration-induced divergence attribution
+
Model × Scaffold interaction(CISR)
+
Live branching validation
```

링크:
- HarnessOpt-Bench: https://arxiv.org/abs/2608.06301
- Evo-Bench: https://arxiv.org/abs/2608.09096

---

## 24.11 The Replay Gap — 정적 replay를 causal evidence로 쓰면 안 되는 이유

**The Replay Gap: Static Evaluation of Model Switching in LLM Agents Scores the Wrong World (2026)**

이 연구는 multi-step Agent에서 중간 model을 바꾸면 이후 trajectory 자체가 크게 달라질 수 있으며, 과거 로그를 단순 이어붙이는 static replay가 실제 model switch outcome을 잘못 예측할 수 있음을 보여준다.

우리 연구에 주는 직접적인 수정사항:

- old output을 new trajectory에 단순 주입하고 나머지 로그를 그대로 replay하는 방식은 **주요 인과 증거로 사용하지 않는다.**
- 가능한 경우 해당 node 직전의 environment state를 복원한다.
- 그 상태에서 모델/설정을 실제로 바꾼 뒤 **새 trajectory를 끝까지 다시 rollout**한다.
- 같은 모델을 다시 실행하는 control fork도 만들어 stochastic/replay noise floor를 측정한다.

링크:
https://arxiv.org/abs/2608.08239

---

# 25. Related Work에서 사용할 포지셔닝 표

| 연구 축 | 기존 연구가 주로 묻는 질문 | 우리 연구 |
|---|---|---|
| LLM Migration | 새 모델이 기존 모델을 대체할 수 있는가? | Agent 내부 구조를 무엇을 바꿔야 하는가? |
| Agent Evaluation | Agent가 잘 작동하는가? | 모델 교체 때문에 무엇이 달라졌는가? |
| Agent Debugging | 실패 원인이 어디인가? | Old→New migration이 만든 divergence가 어디인가? |
| Workflow Optimization | 더 좋은 workflow는 무엇인가? | 새 모델에 필요한 최소 workflow 변화는 무엇인가? |
| Harness Repair | 실패 harness를 어떻게 고칠까? | migration regression + redundant scaffold를 어떻게 함께 처리할까? |
| Routing | 어떤 모델을 사용할까? | migration 후 어느 node만 old/new/cheap model로 분기할까? |

---

# 26. 논문용 실험 Agent 구성

최소 2종류가 좋다.

## Agent A — Controlled Business Agent

대회에서 만든 질의·정책 검증 Agent.

장점:

- ground truth 정확
- 원인을 통제
- intervention 가능
- scaffold 제거 실험 쉬움

논문에서는 이것을 “controlled environment”로 사용한다.

---

## Agent B — External Agent / Benchmark

우리가 만들지 않은 Agent를 최소 하나 선택한다.

선정 조건:

- model을 바꿀 수 있음
- trace를 얻을 수 있음
- 자동 평가 가능
- 반복 실행 비용 감당 가능
- 소스/버전 고정 가능
- prompt/tool/workflow 일부 수정 가능

후보를 정할 때 “유명함”보다 **평가 재현성**을 우선한다.

---

## 더 강한 논문

Agent C를 추가한다.

예:

- tool-use agent
- coding agent
- web/navigation agent

처럼 성격이 다른 것을 선택하면 generalization 근거가 강해진다.

---

# 27. Model Pair 설계

단순히 “모델 3개 점수 비교”를 하지 않는다.

연구 단위는 **Migration Pair**다.

```text
M1 → M2
M1 → M3
M2 → M3
```

각 pair에서 Agent scaffold는 먼저 완전히 동일하게 고정한다.

## 좋은 pair 유형

### Type A — Same-family successor

가장 이상적.

```text
구버전 → 후속버전
```

장점:

- 실제 upgrade scenario와 가까움
- 모델 family 차이 confound 감소

### Type B — Cross-provider replacement

실제 기업에서 공급자 변경을 할 때 유용.

단점:

- model change 외에 API/tool behavior 차이가 섞일 수 있음

따라서 논문에서는 Type A와 B를 구분해 보고한다.

---


## 27.1 Primary Protocol — Locked-Harness Migration

RQ1/RQ2의 핵심 실험에서는 처음부터 role-level로 서로 다른 harness를 비교하지 않는다.

```text
A_old  = (M_old, H0)
A_swap = (M_new, H0)
```

여기서 `H0`는 prompt, tool definition, workflow, retry, verifier, routing을 모두 포함한다.

**M만 바꾼다.**

이렇게 해야 관찰된 초기 차이를 model migration과 연결할 수 있다.

구조 수정은 regression을 확인한 **이후 단계**에서만 한다.

## 27.2 반드시 고정/기록할 confound

- exact model ID
- provider
- API/client library version
- temperature / top-p / seed 지원 여부
- max output tokens
- reasoning effort 또는 유사 설정
- tool choice mode
- response schema
- system/developer prompt hash
- tool schema hash
- timeout / retry at API layer
- experiment date

특히 cross-provider replacement는 provider API semantics까지 섞일 수 있으므로 **same-family successor를 primary evidence**, cross-provider는 secondary evidence로 두는 것이 안전하다.

# 28. 자연 발생 Regression을 반드시 포함한다

Controlled Agent에서 일부러 오류를 주입하는 것은 detector 검증에 유용하다.

하지만 논문의 핵심 결과를 synthetic error만으로 만들면 안 된다.

## Synthetic Regression

목적:

- localization accuracy 측정
- ground-truth cause 확보

예:

- tool schema mismatch
- verifier removal
- retry bug
- routing threshold change

## Natural Migration Regression

목적:

- 실제 연구 가치 증명

동일한 Agent scaffold에서 model만 바꾼다.

그 뒤 자연스럽게 발생하는:

- tool selection 변화
- argument 변화
- retry 증가
- plan 길이 변화
- safety behavior 변화
- cost 변화

를 수집한다.

최종 논문은 두 종류가 모두 있어야 좋다.

---

# 29. Paired Differential Trace 알고리즘

## 단계 1 — Role-level Alignment

Agent마다 node 이름이 다를 수 있으므로 role을 정의한다.

예:

```text
CLASSIFY
RETRIEVE_SCHEMA
GENERATE_QUERY
VALIDATE_QUERY
EXECUTE_TOOL
SELECT_POLICY
DECIDE
GENERATE_RESPONSE
FINAL_VERIFY
```

## 단계 2 — Feature Extraction

각 node에서:

- success/fail
- tool
- argument validity
- token
- latency
- output type
- retry
- confidence/score 가능하면
- downstream effect

를 저장한다.


### 관찰 가능한 Trace만 연구 대상으로 사용

논문 방법은 모델의 비공개 내부 chain-of-thought에 의존하지 않는다.

수집 대상은 외부에서 재현 가능한 정보다.

- 모델에 실제로 전달된 input/context의 hash 또는 저장본
- 공개된 model output
- tool call과 arguments
- tool observation
- environment/workspace state identifier
- error/retry
- token/latency/cost
- 최종 artifact/outcome

이렇게 해야 provider가 달라져도 연구 방법을 적용할 수 있고 재현성도 높다.

### Locked Harness에서는 alignment를 단순하게 시작

초기 migration 실험은 동일한 `H0`를 사용하므로 node role이 원칙적으로 동일하다.

따라서 논문 v1에서는 복잡한 cross-agent semantic alignment를 핵심 알고리즘으로 만들지 않는다.

- Controlled Agent / 동일 harness: **exact node alignment** 우선
- External Agent adapter: 필요할 때만 role-level normalization

이렇게 범위를 줄이는 것이 구현 난이도와 논문 해석 모두에 유리하다.

## 단계 3 — Difference Score

개념적 예:

```text
D_i =
w1 * ActionDifference
+ w2 * ErrorDifference
+ w3 * ToolArgumentDifference
+ w4 * RetryDifference
+ w5 * DownstreamImpact
```

## 단계 4 — Candidate Localization

단순 first difference만 쓰지 않는다.

다음을 함께 본다.

- 처음 등장한 큰 차이
- 실패와 data dependency가 있는 차이
- 여러 trial에서 반복되는 차이
- old는 성공/new는 실패하는 case에서 공통인 차이

## 단계 5 — Intervention

의심 node를 바꿔서 failure가 사라지는지 본다.

---

# 30. Root Cause를 더 강하게 만드는 Branching Counterfactual Rollout

기존 계획의 단순 `Counterfactual Replay`는 v2에서 수정한다.

## 왜 static replay가 위험한가

multi-step Agent는 한 node의 model/output이 바뀌면 이후 tool call, workspace state, observation, retry 경로가 달라질 수 있다.

따라서:

```text
N3의 old output만 끼워 넣고
기존 N4/N5 로그를 그대로 이어붙이는 것
```

은 실제 counterfactual world를 재현하지 못할 수 있다.

## 권장 방식 — Branching Rollout

의심 node `N3` 직전까지의 상태 `S2`를 저장한다.

```text
공통 prefix
N1 → N2 → [checkpoint S2]
```

그 뒤 branch를 만든다.

```text
Branch A: S2 → N3(new model) → 이후 실제 rollout
Branch B: S2 → N3(old model) → 이후 실제 rollout
```

중요한 점은 **N3 이후의 trajectory를 과거 로그로 고정하지 않고 실제로 다시 실행**하는 것이다.

## Same-model control도 둔다

Agent의 stochasticity 때문에 단순 A/B 차이가 model switch 때문인지 샘플링 노이즈인지 구분해야 한다.

가능하면:

```text
Control 1: S2 → new model → rollout #1
Control 2: S2 → new model → rollout #2
Switch:    S2 → old model → rollout
```

또는 old model 방향도 대칭 control을 둔다.

이를 통해 **model-switch divergence가 same-model noise floor보다 큰지** 확인한다.

## Controlled Agent 구현

질의·정책 검증 Agent는 environment state가 작으므로 checkpoint가 쉽다.

저장 후보:

- DB snapshot/version
- retrieved rows
- selected policy IDs
- node input context
- tool state
- retry state
- random/config seed 가능하면

## External Agent

환경 복원이 가능한 Agent를 우선 선택한다.

checkpoint/restore가 불가능하면 해당 Agent에서는 강한 causal claim을 낮추고:

- paired observational trace
- repair-and-rerun
- repeated control

수준의 근거로 제한한다.

## 논문에서의 주장 수준

Branching rollout이 recovery를 일으켰다고 해서 철학적 의미의 완전한 인과관계를 증명했다고 과장하지 않는다.

대신:

> **해당 node에서의 model-dependent behavior가 downstream outcome에 기여했다는 intervention-based evidence**

라고 표현한다.

---

# 31. Capability-Induced Scaffold Redundancy를 2×2 실험으로 검증

새 모델에서 verifier 하나를 제거해도 성능이 유지됐다는 사실만으로는 **“새 모델이 좋아져서 불필요해졌다”**고 말할 수 없다.

Old Model에서도 원래 불필요했을 수 있기 때문이다.

따라서 component `c`마다 다음 factorial design을 사용한다.

```text
                 Scaffold ON        Scaffold OFF
Old Model        old_on             old_off
New Model        new_on             new_off
```

## 31.1 1차 조건 — Old에서는 실제 역할이 있었는가

```text
Q(old_off) < Q(old_on) - meaningful_margin
```

즉 old model에서는 제거가 실제로 해로웠거나 최소한 verifier가 의미 있는 역할을 했다는 근거가 필요하다.

## 31.2 2차 조건 — New에서는 제거 가능해졌는가

```text
Q(new_off) >= Q(new_on) - ε_q
Safety(new_off) non-inferior
```

그리고:

```text
Cost(new_off) < Cost(new_on)
또는
Latency / Calls / Tokens 감소
```

가 있어야 한다.

## 31.3 Interaction으로 해석

```text
Δ_old = Q(old_off) - Q(old_on)
Δ_new = Q(new_off) - Q(new_on)
CISR_effect = Δ_new - Δ_old
```

이 interaction이 충분히 크고 bootstrap CI가 이를 뒷받침하면 **model capability change와 scaffold 필요성의 상호작용**을 주장할 수 있다.

## 31.4 우선 실험할 component

모든 것을 한 번에 하지 않는다.

1. LLM verifier
2. retry budget / reflection
3. long few-shot prompt
4. duplicate classifier
5. expensive node-level model

가장 해석이 쉬운 verifier와 retry부터 한다.

## 31.5 용어 사용 규칙

- 단순히 new model에서 제거 가능: **Scaffold Removal Opportunity**
- old에서는 필요했고 new에서만 비로소 불필요해졌다는 2×2 근거 있음: **Capability-Induced Scaffold Redundancy (CISR)**

이 구분을 지켜야 novelty를 과장하지 않는다.

---

# 32. Candidate Migration Operator

처음부터 자유 코드 수정 대신 다음 operator를 만든다.

## Prompt

- ADD_EXAMPLE
- REMOVE_REDUNDANT_INSTRUCTION
- REWRITE_TOOL_GUIDANCE
- SHORTEN_STATIC_CONTEXT

## Tool

- CLARIFY_TOOL_DESCRIPTION
- ADD_ARGUMENT_EXAMPLE
- ADD_SCHEMA_VALIDATOR
- FILTER_RELEVANT_SCHEMA

## Verification

- ADD_DETERMINISTIC_VALIDATOR
- REMOVE_LLM_VERIFIER
- CONDITIONAL_VERIFIER

## Retry

- REDUCE_MAX_RETRY
- ERROR_SPECIFIC_RETRY
- STOP_ON_REPEAT
- FALLBACK_ON_REPEAT

## Routing

- ROUTE_DIFFICULT_TASK
- NODE_MODEL_FALLBACK
- CHEAP_MODEL_FOR_EASY_TASK

## Workflow

- REMOVE_REDUNDANT_NODE
- CONDITIONAL_NODE
- PARALLELIZE_INDEPENDENT_NODE

대회에서는 이 중 2~4개만 구현한다.

논문에서는 operator pool로 확장한다.

---

# 33. Candidate Search 전략

논문 초반에는 복잡한 RL이나 MCTS부터 하지 않는다.

## 추천 순서

### Version 1 — Rule-guided

Diagnosis → 정해진 operator mapping.

예:

```text
argument missing
→ ADD_ARGUMENT_EXAMPLE
→ ADD_SCHEMA_VALIDATOR
```

### Version 2 — LLM Candidate Generator

Trace + diagnosis + allowed operators를 주고 상위 K개 후보 생성.

### Version 3 — Budget-aware Search

후보를 전부 full test하지 않고:

```text
small validation
→ top candidate
→ expanded validation
→ hidden test
```

순으로 평가한다.

이 구조가 학부/초기 연구에서 구현 가능하면서 논문 실험도 명확하다.

---

# 34. 논문 Baseline

최소 다음 baseline을 준비한다.

## B0 — No Adaptation

```text
model만 교체
```

가장 중요한 baseline.

## B1 — Output-only Regression

최종 성공률/최종 답변 차이만 보고 문제를 판단.

## B2 — Prompt-only Adaptation

문제가 생기면 system prompt만 수정.

RETAIN 계열과 비교하기 위한 단순화된 baseline.

## B3 — Free-form LLM Optimizer

Trace와 source/config를 주고:

> Agent를 개선하라

라고 자유롭게 수정.

## B4 — Search-based

허용 operator를 무작위 또는 grid로 적용.

## B5 — Trace-guided but Unpaired

실패한 new trace만 사용.

## Proposed

```text
Paired Old/New Trace
+ Migration Diagnosis
+ Scoped Operator
+ Re-validation
```

이렇게 해야 paired difference의 효과를 분리해서 보여줄 수 있다.

---

# 35. Ablation Study

논문을 강하게 만드는 핵심이다.

## A1 — Differential Trace 제거

```text
우리 전체 방법
vs
new trace only
```

## A2 — Root Cause Localization 제거

```text
diagnosis 후 candidate
vs
무작위 candidate
```

## A3 — Intervention 제거

```text
trace ranking만 사용
vs
intervention 확인
```

## A4 — Redundancy Detection 제거

regression repair만 하는 경우와 비교.

## A5 — Scoped Operator 제거

free-form edit과 비교.

## A6 — Re-validation 제거

추천만 하고 hidden test를 안 하는 경우 얼마나 regression이 발생하는지 확인.

---

# 36. 핵심 평가 지표

## Quality

- Task Success Rate
- SQL execution correctness
- Policy Decision Accuracy
- Tool Selection Accuracy
- Tool Argument Validity

## Safety

- prohibited tool call
- write/delete SQL attempt
- policy violation
- max step violation

## Efficiency

- LLM Calls / Task
- Input Tokens
- Output Tokens
- Total Tokens
- API Cost
- p50 latency
- p95 latency
- Retry Count

## Migration

- Old PASS → New FAIL rate
- Old FAIL → New PASS rate
- preserved PASS rate
- Migration Acceptance Rate

## Localization

- Root Cause Top-1
- Root Cause Top-3
- Mean Rank
- Node Distance

## Repair

- Regression Recovery Rate
- New Regression Rate
- Hidden-test Success
- Candidate Evaluations to Recovery

## Simplification

- Removed LLM Calls
- Removed Nodes
- Token Reduction
- Latency Reduction
- Quality Preservation Rate

---

# 37. Migration Regression 정의 — 대회용 Flip과 논문용 확률 정의를 분리

대회 Dashboard에서는 이해가 쉬운 4분면을 그대로 쓴다.

| Old | New | 의미 |
|---|---|---|
| PASS | PASS | preserved |
| PASS | FAIL | regression candidate |
| FAIL | PASS | improvement |
| FAIL | FAIL | persistent failure |

하지만 stochastic Agent 논문에서는 **한 번의 PASS→FAIL을 곧바로 regression으로 확정하지 않는다.**

각 testcase `x`에서 반복 실행하여:

```text
p_old(x) = old model success probability estimate
p_new(x) = new model success probability estimate
Δp(x)    = p_new(x) - p_old(x)
```

를 본다.

사전에 정한 regression margin `δ_r`를 사용해:

```text
Δp(x) < -δ_r
```

이고 불확실성 구간이 이를 지지하는 경우 **probabilistic regression**으로 분류한다.

실행 횟수가 적어 결론이 불안정하면 `INCONCLUSIVE`로 둔다.

따라서:

- 대회: flip matrix로 설명
- 논문: repeated-trial probability shift + CI

로 분리한다.

---

# 38. Stochastic Agent 반복 평가와 Control Floor

Agent는 같은 input과 temperature 0에서도 serving stack, tool timing, provider behavior 등에 따라 달라질 수 있다.

따라서 1회 실행으로 model migration effect를 판단하지 않는다.

## 대회

- 핵심 데모는 2~3회 반복으로 안정성 확인
- 숫자는 반복 평균/빈도임을 표시
- 비용이 크면 대표 scenario만 반복

## 논문 기본 설계

예:

```text
60 TestCases
× 5 trials
× 2 models
= 600 agent runs / migration pair
```

다만 **고정적으로 5회가 항상 충분하다고 주장하지 않는다.**

초기 pilot에서 variance를 보고 중요한 slice는 반복 수를 늘린다.

## Same-model control

특히 branching intervention에서는 반드시 가능한 범위에서 같은 model을 두 번 fork해 실행하여 **자연 변동 noise floor**를 추정한다.

```text
new → new control divergence
old → old control divergence
old ↔ new switch divergence
```

model switch effect는 control divergence보다 의미 있게 큰지를 함께 본다.

## Adaptive repetition 후보

비용을 줄이려면:

- 차이가 매우 큰 case는 조기 종료
- 경계선 case만 추가 trial
- `INCONCLUSIVE` case에 예산 집중

전략을 사용할 수 있다.

첫 논문에서는 adaptive sampling 자체를 새 알고리즘 contribution으로 만들 필요는 없다.

---

# 39. 통계 분석

논문에서는 평균 숫자만 쓰지 않는다.

## 추천

### Binary Success

- paired bootstrap confidence interval
- McNemar test 또는 paired proportion comparison

### Token / Latency / Retry

- paired difference distribution
- median
- bootstrap CI
- 필요 시 Wilcoxon signed-rank

### Localization

- Top-1 / Top-3 proportion CI
- Mean Reciprocal Rank 등을 선택적으로 사용

### Multiple models

pair별 결과를 따로 보여주고 전체 pooled 결과만으로 결론 내리지 않는다.

---

# 40. Dataset Split

최소:

```text
DEV
VALIDATION
HIDDEN TEST
```

## DEV

- Agent 개발
- evaluator 개발
- initial prompt

## VALIDATION

- candidate 선택
- threshold 선택

## HIDDEN TEST

- 최종 결과

절대 hidden test 실패를 보고 prompt/operator를 다시 손보지 않는다.

그렇게 하면 논문 결과가 오염된다.

---

# 41. Controlled Agent TestCase 구성

60개를 예로 들면:

## Easy — 20

- 단일 주문 조회
- 단일 정책
- 하나의 tool

## Medium — 20

- 2개 조건
- 여러 DB field
- 정책 예외

## Hard — 20

- 여러 table
- 정책 충돌
- 누락 정보
- 추가 확인
- 잘못된 사용자 가정

각 그룹에:

- 정상 성공
- invalid ID
- missing data
- safety
- ambiguous question

을 균형 있게 넣는다.

---

# 42. Behavioral Fingerprint

긴 trace를 비교하기 위한 요약 feature.

예:

```json
{
  "tool_sequence": [
    "schema_lookup",
    "sql_execute",
    "policy_lookup"
  ],
  "llm_calls": 4,
  "tool_calls": 3,
  "retries": 1,
  "invalid_arguments": 0,
  "verification_calls": 1,
  "total_tokens": 4210,
  "latency_ms": 5300
}
```

Old/New 비교:

```text
Δ llm_calls
Δ retries
Δ invalid_arguments
Δ tool sequence
Δ tokens
Δ latency
```

이것이 대회 Dashboard에도 유용하고 논문 feature에도 사용된다.

---

# 43. 논문에서 만들 수 있는 Dataset / Benchmark

가칭:

## AgentMigrationBench

구성:

```text
Agent
ModelOld
ModelNew
TestCase
Old Trials
New Trials
Trace
Outcome Flip
Regression Category
Root Cause
Applicable Operators
Validation Results
```

좋은 데이터셋이 되려면 단순 로그 dump가 아니라 annotation이 있어야 한다.

### 최소 annotation

- migration pair
- old/new result
- regression 여부
- first divergence
- confirmed cause 여부
- repair operator
- repair result

이 데이터셋이 공개 가능하면 논문 contribution이 크게 강해질 수 있다.

---

# 44. 논문 수준별 목표

## 국내 학술대회 / 학부 논문

충분한 범위:

- Controlled Agent 1개
- External Agent 1개
- Model migration pair 2~3개
- TestCase 60+
- Paired trace
- regression localization
- scaffold redundancy
- 3~5 operators
- 3~4 baselines
- ablation 2~3개

## 국제 Workshop

추가:

- Agent 3개
- 여러 model family
- 더 큰 benchmark
- intervention localization
- 공개 dataset/code
- 강한 통계

## Top-tier Full Paper

추가로 요구될 가능성이 높은 것:

- broad generalization
- 훨씬 큰 benchmark
- 강한 baseline
- robust causal evidence
- reproducible framework
- 상당한 empirical scale
- 명확한 새로운 algorithmic idea

처음부터 top-tier full paper 규모로 개발하지 않는다.

---


## 44.1 가장 추천하는 첫 논문 범위 — Minimum Publishable Unit

처음부터 모든 contribution을 동시에 최대치로 구현하지 않는다.

### 반드시 포함

- Controlled Agent 1개
- External Agent 1개
- Same-family migration pair 최소 2개
- locked-harness raw migration experiment
- paired observable trace
- regression localization baseline 비교
- branching intervention을 regression subset에서 수행
- CISR 2×2 실험: 최소 2개 scaffold component
- scoped operator 3~5개
- hidden test
- deterministic evaluator 중심
- bootstrap CI / paired statistics

### 가능하면 포함

- cross-provider pair 1개
- AgentMigrationBench 공개
- Agent C
- budget-aware search

### 첫 논문에서 과감히 보조로 내려도 되는 것

- 범용 semantic trace alignment
- 자유 코드 자동 수정
- RL/MCTS optimizer
- 완전 자동 deployment gate
- 대규모 GUI/SaaS

> **핵심 판단:** 첫 논문은 “범용 Agent optimizer”를 만드는 논문이 아니라, **model migration이 Agent harness에 만드는 변화와 이를 진단/적응하는 방법을 보여주는 논문**이어야 한다.

# PART IV. 구체적인 개발 순서

# 45. 전체 개발 단계

```text
PHASE 0  대회 Problem/Scope Freeze
PHASE 1  Controlled Agent
PHASE 2  TestCase + Evaluator
PHASE 3  Versioned Execution
PHASE 4  MABC Audit Skill
PHASE 5  Trace + Diff
PHASE 6  MABC Final Service
-----------------------------
PHASE 7  Research Refactor
PHASE 8  Natural Model Migration Experiments
PHASE 9  Differential Localization
PHASE 10 Intervention
PHASE 11 Scaffold Redundancy
PHASE 12 Baseline/Ablation
PHASE 13 External Agent
PHASE 14 Benchmark + Statistics
PHASE 15 Paper
```

---

# 46. 2026-08-12 ~ 08-17: 대회 시작 전

## 목표

“무엇을 만들지” 다시 흔들리지 않게 한다.

## 해야 할 일

### 1. 대회 주제 freeze

```text
Agent Upgrade Auditor
```

로 일단 고정.

### 2. 예비 Agent 최소 구현

노드:

```text
N1 Intent
N2 DB schema
N3 Query
N4 Validate
N5 Execute
N6 Policy
N7 Decision
N8 Answer
```

### 3. TestCase 10개

처음에는 60개 만들지 않는다.

### 4. evaluator

- SQL
- policy
- tool schema

먼저 구현.

### 5. V0/V1 sample

일부러 차이를 한 개 만든다.

### 6. Timely AI 기능 확인

반드시 직접 확인할 항목:

- Skill 입력 형식
- 구조화된 text/JSON 처리
- 외부 API 가능 여부
- 다른 Agent 호출 가능 여부
- 파일 입력
- 실행 history 접근
- 결선 builder 범위

확인 결과에 따라 Level 0/1/2 중 대회 구현을 고른다.

---

# 47. 08-18 ~ 08-21: MABC 예선 1차

목표:

> Auditor Skill이 실제로 하나의 업무를 끝까지 한다.

입력 예:

```text
V0 결과 10건
V1 결과 10건
```

출력:

```text
Regression 2
Improvement 1
Efficiency Warning 1
Top Recommendation 2
```

아직 자동 실행은 없어도 된다.

---

# 48. 08-22 ~ 08-25: 대회 품질 확보

## TestCase 20~30개

카테고리를 늘린다.

## 보고서 표준화

모든 출력 형식을 일정하게 한다.

```text
Summary
Regression
Efficiency
Trace Difference
Recommendation
Risk
```

## False Alarm 확인

정상 변경을 억지로 문제라고 말하지 않는지 확인한다.

---

# 49. 08-26 ~ 08-29: 예선 제출용 완성

해야 할 것:

- 대표 Demo 1개
- 실패 Demo 1개
- 개선 Demo 1개
- 소개 문장
- 사용자 문제
- 사용 방법
- 결과 예시
- 한계 명시

이 시점에 새로운 큰 기능을 추가하지 않는다.

---

# 50. 08-30 ~ 08-31: 제출 freeze

체크:

- 처음 보는 사람이 1분 안에 사용법 이해
- 같은 input에서 형식이 안정적
- 결과가 너무 연구용 용어에 치우치지 않음
- 사용자가 다음 행동을 알 수 있음

---

# 51. 결선 진출 시 09-09 ~ 09-18

## 우선순위 1 — 자동 Runner

TestSuite를 자동으로 V0/V1에 보낸다.

## 우선순위 2 — Dashboard

핵심 5개 숫자만 먼저.

```text
Success
Regression
Tool Error
Token
Latency
```

## 우선순위 3 — Trace Diff

## 우선순위 4 — Candidate

2~3개 operator.

## 우선순위 5 — Re-validation

이것까지 되면 프로젝트의 완결성이 크게 올라간다.

---

# 52. Demo Replay를 반드시 준비

Live API는 발표 때 실패할 수 있다.

따라서 모든 주요 demo는:

```text
live mode
+
saved trace replay mode
```

를 준비한다.

Replay에서도:

- V0
- V1
- regression
- candidate
- re-validation

전체 흐름이 재생되어야 한다.

---

# PART V. 대회 이후 논문 개발

# 53. 대회 종료 직후 가장 먼저 할 일

대회 코드를 freeze한다.

Git tag 예:

```text
mabc-2026-final
```

그 뒤 research branch를 만든다.

```text
research/modelshift-v0
```

대회 UI 기능을 계속 확장하지 않는다.

논문에서 필요한 core reliability에 집중한다.

---

# 54. Research Refactor

대회 코드에서 다음을 독립 모듈로 뽑는다.

- runner
- adapter
- trace
- evaluator
- experiment config
- result DB
- metrics
- candidate
- validator

실험 하나를 YAML/JSON 하나로 재현할 수 있어야 한다.

예:

```yaml
agent: policy_agent
old_model: MODEL_A
new_model: MODEL_B
dataset: test_v1
trials: 5
temperature: 0
trace: true
```

---

# 55. 최초 논문 실험은 “새 모델이 항상 좋은가?”부터

최적화 알고리즘을 먼저 만들지 않는다.

먼저 empirical question을 확인한다.

## Experiment 1

같은 Agent scaffold.

```text
Old Model
vs
New Model
```

외에는 아무 것도 바꾸지 않는다.

수집:

- PASS→FAIL
- FAIL→PASS
- tool shift
- retry shift
- token
- latency
- safety

이 결과만으로도 연구 방향이 검증된다.

### 중요한 Go/No-Go

선택한 model pair에서 regression이 거의 없다면:

- 억지로 오류를 만들지 않는다.
- 더 복잡한 task slice를 본다.
- 다른 migration pair를 고른다.

**자연 발생 model migration effect가 있어야 연구 스토리가 강하다.**

---

# 56. 다음으로 Differential Trace를 개발

Regression case만 가져온다.

각 case에서:

```text
T_old
T_new
```

를 align한다.

초기 알고리즘은 단순해도 된다.

### v1

- node role
- error
- tool
- retry
- output type

difference.

### v2

여러 trial을 aggregation.

### v3

downstream dependency.

---

# 57. Root Cause Ground Truth 만들기

자연 regression은 진짜 원인을 알기 어렵다.

따라서 두 데이터 유형을 병행한다.

## Controlled faults

정확한 원인을 알고 있는 regression.

이를 localization accuracy 평가에 사용.

## Natural faults

실제 migration에서 나온 regression.

사람 분석 + intervention으로 원인을 확인.

논문에서는 둘을 분리해서 보고한다.

---

# 58. Intervention 개발

우선 가장 쉬운 것부터.

## Node Model Swap

의심 node만 old model로 되돌린다.

```text
All New Model
except N3 = Old Model
```

성능이 회복되는지 본다.

이 방식은 구현이 비교적 쉽고 해석도 좋다.

그 다음:

- old output replay
- validator insertion
- prompt patch

로 확장한다.

---

# 59. Scaffold Redundancy 실험

새 모델에서:

```text
Verifier OFF
Retry 5→2
Long prompt → short prompt
```

같은 candidate를 평가한다.

하지만 전체 조합 search를 바로 하지 않는다.

한 번에 하나씩 ablation하여 효과를 이해한다.

그 뒤 조건부 조합을 만든다.

---

# 60. External Agent Adapter

Adapter interface 예:

```python
class AgentAdapter:
    def run(self, testcase, config):
        ...
    def set_model(self, model):
        ...
    def collect_trace(self):
        ...
    def apply_operator(self, operator):
        ...
```

외부 Agent의 내부 log를 공통 Trace로 변환한다.

중요:

> 외부 Agent 코드를 우리 연구 구조에 맞게 크게 뜯어고치지 않는다.

Adapter가 얇아야 일반성 주장이 가능하다.

---

# 61. 최종 논문 Experiment Matrix

예시:

```text
Agents: 2
Migration Pairs: 3
TestCases: 60~200 / Agent
Trials: 5
Baselines: 5
Ablations: 4
Operators: 6
```

단순 baseline migration:

```text
2 × 3 × 100 × 5 × 2 models
= 6,000 executions
```

여기에 repair가 추가된다.

따라서 API 비용을 줄이기 위해:

- development subset
- candidate shortlist
- caching 가능한 고정 데이터
- early stopping
- deterministic validators

를 사용한다.

---

# 62. 실험 비용을 줄이는 Candidate Validation

모든 후보를 full benchmark에서 실행하지 않는다.

```text
Stage A
Regression slice 10~20 cases
        ↓
Stage B
Validation 30~50 cases
        ↓
Stage C
Full hidden test
```

상위 후보만 다음 단계로 간다.

이 자체를 budget-aware optimization 방법으로 확장할 수도 있지만 첫 논문에서는 보조 전략으로 둔다.

---

# 63. 논문 결과 Table 설계

## Table 1 — Raw Model Migration

| Agent | Migration | Old Success | New Success | Regression | Cost Δ |
|---|---|---:|---:|---:|---:|

## Table 2 — Localization

| Method | Top-1 | Top-3 | MRR |
|---|---:|---:|---:|

## Table 3 — Repair

| Method | Recovery | New Regression | Evaluations | Cost |
|---|---:|---:|---:|---:|

## Table 4 — Scaffold Simplification

| Migration | Removed Calls | Token Δ | Latency Δ | Quality Δ |
|---|---:|---:|---:|---:|

## Table 5 — Ablation

| Variant | Recovery | Localization | Cost |
|---|---:|---:|---:|

---

# 64. 논문 Figure 설계

## Figure 1

전체 개념.

```text
Old Agent + Old Model
          ↓
        Trace
          │
          ├──── Diff ────┐
          │              │
New Agent + New Model    │
          ↓              │
        Trace ───────────┘
                         ↓
           Regression / Redundancy
                         ↓
              Scoped Migration
                         ↓
                 Re-validation
```

## Figure 2

Paired trace example.

## Figure 3

Regression/Improvement flip matrix.

## Figure 4

Cost-quality Pareto.

## Figure 5

Node-level localization performance.

---

# 65. 논문 작성 구조

## Abstract

1. 모델이 빠르게 바뀜
2. 더 좋은 model ≠ 더 좋은 Agent
3. 기존 연구는 output migration / debugging / workflow optimization을 다루지만 migration-specific harness adaptation은 충분히 분리되지 않음
4. ModelShift 제안
5. paired trace
6. regression + redundancy
7. experiments
8. 핵심 결과

## 1. Introduction

- model lifecycle
- production migration problem
- example
- limitations of simple swap
- research questions
- contribution

## 2. Related Work

- model migration
- agent evaluation
- agent debugging
- workflow optimization
- harness evolution

## 3. Problem Formulation

- Agent tuple
- migration pair
- regression
- scaffold redundancy
- constraints

## 4. Method

- trace
- alignment
- localization
- operator
- validation

## 5. Experimental Setup

- Agents
- Models
- Data
- Baselines
- Metrics

## 6. Results

RQ1~RQ4.

## 7. Ablation

## 8. Threats to Validity

## 9. Conclusion

---

# 66. 논문에서 예상되는 리뷰어 공격과 대응

## 공격 1

> “이건 그냥 Agent optimization 아닌가?”

대응:

- migration event formalization
- paired old/new traces
- migration-specific regression
- old model as behavioral control
- redundancy after capability improvement

---

## 공격 2

> “HarnessFix랑 뭐가 다른가?”

대응:

HarnessFix:

```text
failed agent → trace → harness diagnosis → repair
```

우리:

```text
same Agent
old model vs new model
→ model-induced difference
→ regression + obsolete scaffold
→ migration-specific minimal adaptation
```

그리고 paired trace ablation으로 실제 이점 증명.

---

## 공격 3

> “First divergence가 root cause라는 보장은?”

대응:

- first difference만으로 결론 내리지 않음
- recurring evidence
- dependency
- checkpoint-based branching intervention
- repair recovery

---

## 공격 4

> “Synthetic fault를 스스로 넣고 스스로 찾은 것 아닌가?”

대응:

- synthetic은 localization ground truth용
- 핵심 external validity는 natural model migration regression
- external Agent 추가

---

## 공격 5

> “비용 줄이려고 정확도를 희생한 것 아닌가?”

대응:

quality/safety constraint를 먼저 만족한 후보만 효율 비교.

---

## 공격 6

> “LLM Judge가 편향된 것 아닌가?”

대응:

가능한 핵심 지표는 deterministic oracle.

---


## 공격 7

> “Harness-Bench가 이미 model-harness interaction을 보여줬는데 무엇이 새로운가?”

대응:

- Harness-Bench는 interaction을 측정하는 diagnostic benchmark
- 우리는 **명시적인 old→new migration event**를 시작점으로 함
- regression localization + migration adaptation + CISR를 평가
- 동일 locked harness에서 변화 원인을 먼저 분리한 뒤 최소 변경을 수행

---

## 공격 8

> “HarnessOpt-Bench / Evo-Bench가 이미 harness optimization을 평가한다.”

대응:

우리 novelty를 optimizer의 일반적인 개선 능력에 두지 않는다.

```text
General harness optimization X
Migration-conditioned diagnosis/adaptation O
```

특히 paired old/new evidence와 2×2 CISR interaction을 핵심으로 둔다.

---

## 공격 9

> “old output을 replay한 counterfactual은 실제 world가 아닌 것 아닌가?”

대응:

- static log stitching을 causal evidence로 사용하지 않음
- environment checkpoint에서 **live branching rollout** 수행
- same-model control fork로 noise floor 측정
- checkpoint가 불가능한 Agent에서는 causal claim을 낮춤

---

## 공격 10

> “새 모델에서 verifier를 빼도 되었다고 해서 모델 발전 때문이라는 보장은?”

대응:

- Old/New × Scaffold ON/OFF 2×2 factorial experiment
- `Δ_new - Δ_old` interaction 분석
- old에서 필요했고 new에서 non-inferior가 된 경우에만 CISR 용어 사용

---

# PART VI. 프로젝트 관리

# 67. 4인 개발 체제 역할 분담

이 문서의 개발 계획은 **4인 체제**를 기준으로 유지한다. 대회 제출 인원 규정과 별개로 기술 개발·연구 역할은 4개 축으로 나누는 것이 가장 자연스럽다.

기존 구상을 조금 수정하면:

## A — Agent / Adapter

- Controlled Agent
- model API
- external Adapter
- workflow

## B — Dataset / Evaluator

- TestCase
- ground truth
- deterministic evaluation
- split

## C — Trace / Differential Analysis

- trace schema
- alignment
- fingerprint
- localization
- intervention

## D — Migration / Product

- operator
- validation runner
- dashboard
- MABC skill/service

단, 공통 schema를 먼저 정하고 매주 integration한다.

---

# 68. 혼자 개발한다면 순서

절대 동시에 4파트를 만들지 않는다.

```text
1. Agent
2. Test
3. Evaluator
4. Version
5. Trace
6. Compare
7. Report
8. Candidate
9. Validation
10. UI
```

UI는 마지막이다.

---

# 69. Git Branch 전략

```text
main
├─ mabc
├─ core
└─ research
```

권장 tag:

```text
mabc-prelim
mabc-final
paper-experiment-v1
paper-camera-ready
```

모든 논문 결과에는 commit을 기록한다.

---

# 70. Experiment Registry

각 실험을 CSV/DB로 관리한다.

```text
experiment_id
agent
dataset
old_model
new_model
prompt
tool
workflow
trials
commit
date
status
```

“어떤 설정으로 나온 숫자인지” 나중에 모르면 논문 작업이 매우 힘들어진다.

---

# 71. 실패 로그도 버리지 않는다

성공 결과뿐 아니라:

- timeout
- provider error
- invalid JSON
- tool error
- evaluation error
- max retry
- safety block

를 저장한다.

Agent 연구에서 실패 분포 자체가 결과가 될 수 있다.

---

# 72. 대회 개발 중 연구를 위해 꼭 남길 것

대회가 급해도 다음은 반드시 저장한다.

- raw trace
- agent config
- test input
- evaluator result
- version
- token
- latency
- candidate
- re-validation

대회 화면에는 안 보여도 된다.

---

# 73. 하지 말아야 할 개발

## 대회 전 금지에 가까운 것

- 범용 multi-agent framework
- 자유 코드 self-rewrite
- RL
- MCTS workflow search
- 여러 외부 Agent
- 10개 provider 지원
- 복잡한 causal graph
- 대규모 benchmark

## 논문 초기에 하지 말 것

- UI 재설계
- SaaS 배포
- user account/payment
- 예쁜 animation
- 자동 실제 production deploy

연구 기여와 관계 없는 개발에 시간을 쓰지 않는다.

---

# 74. 성공 기준

## MABC 성공 기준

다음 질문에 3분 안에 답할 수 있다.

> “무엇이 불편한가?”

> “Agent Upgrade Auditor가 무엇을 자동으로 해주는가?”

> “실제로 어떤 문제가 발견됐는가?”

> “얼마나 좋아졌는가?”

> “왜 일반 사용자/직장인에게 유용한가?”

그리고 live 또는 replay demo가 끝까지 작동한다.

---

## 논문 성공 기준

다음 주장을 데이터로 증명한다.

### Claim 1

최신/강한 model migration이 기존 Agent에서 항상 개선을 만들지는 않는다.

### Claim 2

paired differential trace가 migration regression localization에 도움을 준다.

### Claim 3

새 모델에서는 일부 legacy scaffold가 불필요해질 수 있다.

### Claim 4

scoped migration + validation이 blind/free-form optimization보다 적은 부작용으로 적절한 configuration을 찾는다.

### Claim 5

현상이 최소 두 Agent / 여러 migration pair에서 관찰된다.

---

# 75. Go / No-Go Gate

## Gate A — 2026-08-17

- Controlled Agent 실행 가능
- 10 TestCase
- V0/V1 difference
- Timely 구현 방식 결정

실패하면:
- 자동 Runner 포기
- Level 0 Audit Skill로 축소

## Gate B — 2026-08-24

- regression 한 개 명확하게 탐지
- optimization opportunity 한 개
- 보고서 안정적

실패하면:
- optimization 자동 추천을 빼고 regression audit에 집중

## Gate C — 2026-08-29

- 2~3분 demo
- fallback replay
- 사용자가 결과를 이해

실패하면:
- 기능 추가 중단
- presentation polish

## Paper Gate A

자연 migration regression이 실제로 관찰됨.

없으면 model pair/task 난이도 수정.

## Paper Gate B

paired trace가 output-only/new-trace-only보다 localization에 추가 정보 제공.

없으면 알고리즘 contribution을 재설계.

## Paper Gate C

최소 하나 이상의 scaffold simplification이 quality 유지 조건에서 비용/latency를 줄임.

없으면 “redundancy”를 주요 contribution에서 보조 분석으로 낮춤.

---


## Paper Gate D — Branching Evidence

최소한 controlled Agent의 대표 regression subset에서:

- checkpoint 복원 가능
- same-model control 가능
- model-switch branch 가능
- branch 이후 실제 rollout 가능

해야 한다.

이게 안 되면 `causal root cause` 표현을 쓰지 않고 **trace-guided localization + repair evidence** 수준으로 낮춘다.

## Paper Gate E — CISR Interaction

최소 2개 scaffold component에서 2×2 실험을 수행한다.

그 결과 old/new 차이가 거의 없다면:

- CISR를 핵심 contribution에서 제외
- 단순 Scaffold Removal Opportunity 분석으로 낮춘다.

억지로 “새 모델이 좋아져서 불필요해졌다”고 주장하지 않는다.

# 76. 예상 위험과 대응

## 위험 1 — MABC 플랫폼 제약

대응:

Level 0/1/2 구조.

## 위험 2 — 주제가 대회에서 너무 개발자 도구처럼 보임

대응:

“AI 연구 도구”가 아니라:

> **AI 업무자동화 수정 후 사람이 반복 검수하는 불편**

을 강조.

## 위험 3 — 논문 선행연구와 중복

대응:

RETAIN, AgentDevel, VeRO, HarnessFix와 contribution matrix를 논문 시작 전에 작성.

## 위험 4 — 모델 API 변화/retirement

Anthropic 등의 API는 실제로 model lifecycle에서 deprecated/retired model을 운영하며 migration을 요구한다.

대응:

- experiment date 기록
- exact model ID
- raw output 저장
- 가능한 경우 open-weight model도 일부 사용
- retirement 전에 필요한 old-model result 확보

Anthropic model lifecycle:
https://docs.anthropic.com/en/docs/about-claude/model-deprecations

## 위험 5 — 비용

대응:

- dev subset
- staged validation
- deterministic evaluator
- raw trace 재사용
- candidate shortlist

## 위험 6 — 실험 누수

대응:

hidden test를 엄격히 분리.

---


## 위험 7 — Model/Harness 외부 confound

특히 cross-provider migration에서는 API semantics, tool-call formatting, hidden serving behavior가 함께 바뀔 수 있다.

대응:

- primary evidence는 same-family successor pair
- exact model/provider/runtime config 기록
- cross-provider 결과는 별도 표로 보고
- “모델 capability 하나 때문”이라는 과도한 attribution 금지

## 위험 8 — Static Replay의 잘못된 결론

과거 trace에 다른 model output을 끼워 넣고 이후 trajectory를 고정하면 실제 model switch world와 달라질 수 있다.

대응:

- 논문 핵심 검증은 live re-run
- causal subset은 checkpoint-based branching rollout
- same-model control로 noise floor 측정

# 77. 추천 최종 스토리

## MABC

> **AI 업무자동화를 업데이트할 때 사람이 기존 업무를 하나씩 다시 테스트해야 하는 문제를 해결한다. Agent Upgrade Auditor는 이전/변경 버전을 동일한 업무에서 비교하여 새로 망가진 기능, 반복 오류, 불필요한 검증을 찾고 재검증 가능한 개선안을 제공한다.**

## 논문

> **Foundation Model의 발전이 Agent의 발전을 자동으로 보장하지 않는다. ModelShift는 동일 Agent의 old/new model execution을 paired trace로 비교하여 migration-induced regression과 capability-induced scaffold redundancy를 식별하고, 제한된 migration operator와 재검증을 통해 품질·안전성을 보존하는 효율적인 Agent configuration을 찾는다.**

두 이야기는 서로 다르지만 같은 기술 코어에서 나온다.

---

# 78. 지금 당장 구현해야 할 순서

내일부터 개발한다고 가정하면 다음 순서가 가장 좋다.

```text
[1]
질의·정책 검증 Agent 최소 구현

[2]
10개 TestCase + deterministic evaluator

[3]
AgentVersion schema

[4]
V0/V1 실행 결과 저장

[5]
PASS→FAIL / FAIL→PASS 비교

[6]
TraceStep schema

[7]
tool/retry/token/latency diff

[8]
MABC Upgrade Audit report

[9]
Timely AI Skill 구현

[10]
20~30 case 확대

[11]
대표 optimization opportunity

[12]
demo + replay

--------------------------------
MABC 이후
--------------------------------

[13]
model adapter

[14]
실제 old/new model pair 실행

[15]
natural regression dataset

[16]
paired trace alignment

[17]
localization

[18]
checkpoint + branching counterfactual rollout

[19]
migration operator pool

[20]
Old/New × Scaffold ON/OFF CISR 실험

[21]
external Agent adapter

[22]
baseline

[23]
ablation

[24]
full experiment

[25]
paper
```

---

# 79. 최종 추천

현재 프로젝트를 완전히 두 개로 쪼개지 않는다.

대회에서는 **연구를 축소한 버전**이 아니라, 같은 핵심 코어를 활용한 **사용자 문제 해결 제품**을 만든다.

그리고 대회 이후:

```text
“제품 기능”
→
“연구 질문”
→
“통제 실험”
→
“선행연구 비교”
→
“일반성 검증”
```

으로 확장한다.

가장 중요한 포인트는 다음 세 가지다.

## 1.

**MABC에서는 Model Migration 자체를 강제로 전면에 내세우지 않는다.**

Timely AI/Solar라는 대회 환경과 “단일 기능 Skill”이라는 미션에 맞게:

> Agent Upgrade / Regression Audit

으로 만든다.

## 2.

**대회 코드의 내부 구조는 논문을 고려한다.**

Version, Trace, Evaluation, Runner를 처음부터 저장한다.

## 3.

**논문에서는 단순 Agent Optimizer가 되지 않는다.**

반드시:

```text
Model Migration
+
Paired Differential Trace
+
Regression
+
Capability-Induced Scaffold Redundancy
+
Scoped Intervention
+
Re-validation
```

이 연구 축을 유지한다.

이렇게 가면 대회용 프로젝트와 논문용 프로젝트가 서로 발목을 잡는 것이 아니라, **대회가 연구용 실험 플랫폼의 1차 구현이 되고 논문이 그 플랫폼의 깊이를 확장하는 구조**가 된다.

---

# 80. 이 문서 기준 최종 프로젝트 정의

## 대회용

### **Agent Upgrade Auditor**

> AI 업무자동화 Agent의 변경 전후 실행을 비교하여 regression, 비효율, 구조 단순화 기회를 발견하고 안전한 개선 방향을 제시하는 Agent QA 서비스.

## 논문용

### **ModelShift**

> Foundation Model 교체 전후를 locked harness에서 반복 실행하고 observable paired trace를 비교하여 migration-induced regression을 진단한다. 의심 지점은 checkpoint-based branching rollout으로 검증하고, Old/New × Scaffold ON/OFF 실험으로 capability-induced scaffold redundancy를 분리한 뒤 scoped migration operator와 live re-validation을 통해 새 모델에 적합한 Agent 구성을 탐색하는 프레임워크.

---

# 참고 자료

1. MABC 2026 — Making AI Beneficial Challenge  
   https://www.upstage.ai/mabc-2026

2. Dixit et al., **RETAIN: Interactive Tool for Regression Testing Guided LLM Migration**, 2024  
   https://arxiv.org/abs/2409.03928

3. Zhang et al., **AFlow: Automating Agentic Workflow Generation**, 2024  
   https://arxiv.org/abs/2410.10762

4. Pan et al., **Measuring Agents in Production**, 2025  
   https://arxiv.org/abs/2512.04123

5. Zhang et al., **AgentDevel: Reframing Self-Evolving LLM Agents as Release Engineering**, 2026  
   https://arxiv.org/abs/2601.04620

6. Ursekar et al., **VeRO: An Evaluation Harness for Agents to Optimize Agents**, 2026  
   https://arxiv.org/abs/2602.22480

7. Casey et al., **When Your LLM Reaches End-of-Life: A Framework for Confident Model Migration in Production Systems**, 2026  
   https://arxiv.org/abs/2604.27082

8. Chen et al., **From Failed Trajectories to Reliable LLM Agents: Diagnosing and Repairing Harness Flaws (HarnessFix)**, 2026  
   https://arxiv.org/abs/2606.06324

9. Zhu et al., **Where LLM Agents Fail and How They Can Learn from Failures / AgentDebug**, 2025  
   https://arxiv.org/abs/2509.25370

10. Zhu et al., **AgentDebugX**, 2026  
    https://arxiv.org/abs/2607.18754


11. Yao et al., **Harness-Bench: Measuring Harness Effects across Models in Realistic Agent Workflows**, 2026  
    https://arxiv.org/abs/2605.27922

12. **HarnessOpt-Bench: Evaluating LLMs at Harness Optimization**, 2026  
    https://arxiv.org/abs/2608.06301

13. Huang et al., **Evo-Bench: Can Language Models Improve Agent Harness?**, 2026  
    https://arxiv.org/abs/2608.09096

14. Gonuguntla, **The Replay Gap: Static Evaluation of Model Switching in LLM Agents Scores the Wrong World**, 2026  
    https://arxiv.org/abs/2608.08239

15. Anthropic Claude Platform — Model Deprecations  
    https://docs.anthropic.com/en/docs/about-claude/model-deprecations

---


# 81. 지금부터 연구 자산으로 반드시 남겨야 할 것

모델은 빠르게 교체·retire될 수 있으므로 대회 개발 중에도 아래 자료는 저장한다.

- exact model ID / provider / 날짜
- old/new model이 동시에 사용 가능할 때의 **live baseline runs**
- raw observable traces
- full config hash
- API/client version
- tool schema / prompt / workflow version
- testcase split
- deterministic evaluator 결과
- environment snapshot/checkpoint 가능 여부

특히 **old model이 사라진 뒤 저장 로그만으로 모든 model-switch 실험을 재현할 수 있다고 가정하면 안 된다.**

The Replay Gap이 지적하는 것처럼 정적 로그 replay는 multi-step Agent의 실제 branch 결과를 대체하지 못할 수 있다.

따라서 논문 후보 model pair가 정해지는 즉시, 두 모델을 모두 호출할 수 있을 때 핵심 paired run을 먼저 확보한다.

---

# 마지막 체크리스트

## 대회 전

- [ ] 사용자 문제를 “Agent 연구”가 아니라 “업무자동화 변경 검수”로 설명할 수 있다.
- [ ] Timely AI에서 Level 0 이상의 구현 가능성을 확인했다.
- [ ] 10~30 TestCase가 있다.
- [ ] V0/V1 차이가 명확하다.
- [ ] 최소 한 개 regression을 잡는다.
- [ ] 최소 한 개 efficiency opportunity를 보여준다.
- [ ] 결과가 숫자로 보인다.
- [ ] live 실패 대비 replay가 있다.

## 대회 후

- [ ] 대회 코드를 tag로 freeze한다.
- [ ] 모델/Agent adapter를 분리한다.
- [ ] 자연 발생 model migration regression을 수집한다.
- [ ] RETAIN / AgentDevel / HarnessFix / VeRO / Harness-Bench / HarnessOpt-Bench / Evo-Bench와 차이를 다시 확인한다.
- [ ] paired differential trace baseline을 구현한다.
- [ ] static replay가 아니라 checkpoint 기반 branching intervention을 구현한다.
- [ ] Old/New × Scaffold ON/OFF 2×2 CISR 실험을 한다.
- [ ] external Agent를 추가한다.
- [ ] hidden test를 유지한다.
- [ ] baseline/ablation/statistics를 끝낸 뒤 논문을 작성한다.
