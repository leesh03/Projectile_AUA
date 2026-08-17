# Agent Upgrade Auditor 개발 기획서

> **한 문장 정의**
> 동일한 TestCase로 실행한 Agent 두 버전(V0 / V1)의 실행 기록을 입력받아,
> **무엇이 망가졌고 · 어디서 갈라졌고 · 무엇을 줄일 수 있는지**를
> 근거 수치와 함께 사람이 읽을 수 있는 보고서로 바꾸는 단일 Skill.

| 항목 | 내용 |
|---|---|
| 작성 | 2026-08-15 |
| 담당 범위 | Agent Upgrade Auditor (대회 제출물) |
| 담당자 | 소현 |
| 작업 브랜치 | `Auditor` |
| 짝 문서 | `Agent_Upgrade_Auditor_Phase별_개발순서.md` (실행 순서) |
| 대회 | MABC 2026 · 예선 08-18~08-31 · 결선 09-09~09-18 · 최종발표 09-19 |

## 0. 이 문서의 결론부터

**세 줄 요약**

1. Auditor는 **Agent를 실행하지 않는다.** 실행 기록(JSON)을 읽고 해석만 한다. → 팀원 진도와 무관하게 오늘부터 개발 가능.
2. **숫자는 전부 코드가 계산하고, LLM은 계산된 숫자를 설명·묶기·우선순위 정하기에만 쓴다.** → "AI 설명과 수치가 충돌하지 않는다"는 완료 기준을 구조로 보장.
3. **8/17까지 입출력 계약(JSON 스키마)과 Mock 픽스처 생성기를 먼저 끝낸다.** 이것이 늦으면 통합이 실패한다.

**가장 먼저 해야 할 일 (8/15~8/17)**

```text
[1] core/schemas/  — AuditBundle · UpgradeReport 스키마 동결
[2] fixtures/      — 팀원 코드 없이도 돌릴 수 있는 가짜 V0/V1 번들 생성기
[3] 팀 공지         — "Testbed는 이 필드를 반드시 남겨주세요" 요구 필드 목록 배포
```

---

## 1. 담당 경계 — 내가 만드는 것과 만들지 않는 것

프로젝트에는 Agent가 두 개 있고, 나는 **앞쪽 하나만** 만든다.

| 구분 | 대회 제출물 (나) | 검증용 Testbed (팀원) |
|---|---|---|
| 이름 | **Agent Upgrade Auditor** | Order & Refund Policy Agent |
| 역할 | 변경 전후를 비교·진단·추천·재검증 | 주문/환불 질의를 DB·정책으로 처리 |
| 입력 | 실행 기록 JSON (TrialResult, TraceStep) | 자연어 질문 + DB + 정책 |
| 출력 | Upgrade Risk Report | 실행 Trace, 판정 결과, 비용 지표 |
| 담당 | 본 문서 | 유채린(Loop) · 이준원(Core) · 정우혁(Data) |

```text
[팀원 영역]                        [내 영역]
TestCase ──> Testbed V0 ──┐
                          ├──> AuditBundle ──> Agent Upgrade Auditor ──> Upgrade Report
TestCase ──> Testbed V1 ──┘        (JSON)              (나)
                                     ▲
                          이 경계선이 이 문서의 핵심.
                          여기만 고정되면 양쪽은 따로 개발 가능.
```

### 1.1 명시적으로 만들지 않는 것 (예선 기준)

- Testbed Agent 본체, DB, 정책 문서, Gold 정답
- Agent를 자동 실행하는 Runner (**결선 과제로 미룸**)
- 대시보드 UI (**결선 과제로 미룸**)
- 코드 전체 자동 재작성, 범용 아키텍처 탐색
- "모든 Agent를 자동 최적화한다"는 제품 주장

> **금지 규칙:** 예선 Must가 끝나기 전에는 Runner·Dashboard에 손대지 않는다.

---

## 2. 제품 정의

### 2.1 사용자와 불편

| 항목 | 내용 |
|---|---|
| 1차 사용자 | 사내 업무 자동화 Agent를 만들고 고치지만, 전문 QA 체계가 없는 실무자 |
| 상황 | Prompt / Tool 설명 / 모델 / 재시도 설정을 조금 바꿨다 |
| 불편 | "예전에 되던 30건이 지금도 되는지" 사람이 하나씩 다시 확인해야 한다 |
| 기존 대안 | 눈으로 로그 비교, 또는 그냥 배포하고 사고 나면 대응 |

### 2.2 핵심 기능 — Before / After Agent Change Audit

```text
입력                          처리                        출력
─────────────────────────────────────────────────────────────────────
동일 TestCase 목록      1. 페어링·무결성 검증         1. Regression      (망가진 것)
V0 실행 결과            2. 결정론 지표 diff           2. Improvement     (좋아진 것)
V1 실행 결과            3. 규칙 기반 이상 탐지        3. Efficiency Warn (비싸진 것)
(선택) 단계별 Trace     4. LLM 묶기·우선순위·설명     4. Opportunity     (줄일 수 있는 것)
                        5. 수정 후보 생성             5. 수정 후보 1~3개
                        6. 재검증 게이트              6. PASS / HOLD 판정
                        7. 보고서 렌더링              7. Upgrade Risk Report
```

### 2.3 대회에서 주장할 것 / 주장하지 않을 것

| 주장한다 | 주장하지 않는다 |
|---|---|
| 변경 전후를 동일 TestCase로 자동 비교한다 | 모든 Agent를 자동으로 최적화한다 |
| 최종 답뿐 아니라 tool·error·retry·step까지 본다 | 어떤 모델이든 자동 migration한다 |
| 나빠진 사례를 빠르게 찾아준다 | 진짜 근본 원인을 항상 정확히 찾는다 |
| 불필요해진 검증·재시도 후보를 찾는다 | AI가 코드 전체를 안전하게 자동 수정한다 |
| 추천한 변경은 반드시 다시 시험한다 | 사람보다 항상 더 좋은 Agent를 만든다 |

---

## 3. 입출력 계약 (최우선 산출물)

> 이 절이 이 문서에서 가장 중요하다.
> **8/17까지 여기 JSON을 확정하고 팀 전원이 같은 샘플 파일을 읽고 쓸 수 있어야 한다.**

### 3.1 입력 — `AuditBundle`

Auditor가 받는 **유일한** 입력. 파일 하나 또는 JSON 텍스트 하나.

```json
{
  "bundle_id": "audit_20260818_001",
  "created_at": "2026-08-18T10:00:00+09:00",
  "suite": {
    "suite_id": "refund_suite_v1",
    "testcase_ids": ["refund_001", "refund_002", "..."],
    "dataset_version": "ds_v1"
  },
  "baseline": {
    "label": "V0",
    "agent_id": "policy_agent",
    "version": "v0",
    "model_id": "MODEL_A",
    "prompt_version": "p1",
    "tool_schema_version": "t1",
    "workflow_version": "w1",
    "retry_policy": "max_retry=2",
    "verifier_policy": "reflection=1",
    "commit": "abc1234"
  },
  "candidate": {
    "label": "V1",
    "agent_id": "policy_agent",
    "version": "v1",
    "model_id": "MODEL_B",
    "prompt_version": "p2",
    "tool_schema_version": "t1",
    "workflow_version": "w1",
    "retry_policy": "max_retry=5",
    "verifier_policy": "reflection=1",
    "commit": "def5678"
  },
  "change_note": "모델 교체 + tool 설명 문장 수정",
  "trials": [ "TrialResult 객체 배열 (V0/V1 모두 포함)" ],
  "traces": [ "TraceStep 객체 배열 (선택, 있으면 Trace Diff 활성화)" ]
}
```

### 3.2 내가 작성해 배포할 요구 필드 명세

**이 표가 곧 `docs/CONTRACT.md`의 본문이다.** 내가 작성해서 8/17에 팀에 배포한다.
아래 필드가 입력에 없으면 해당 규칙만 `SKIPPED` 처리되고, Auditor 자체는 계속 동작한다.

#### `TrialResult` — 필수

| 필드 | 타입 | 없으면 못 하는 것 |
|---|---|---|
| `testcase_id` | str | **페어링 자체 불가** |
| `agent_label` | `"V0"` \| `"V1"` | **비교 자체 불가** |
| `trial` | int (1~3) | 반복 안정성 확인 |
| `task_success` | bool | Regression 탐지 |
| `policy_correct` | bool | 정책 오류 구분 |
| `tool_error_count` | int | 시나리오 A |
| `retry_count` | int | 시나리오 C |
| `total_tokens` | int | 효율 비교 |
| `latency_ms` | int | 효율 비교 |
| `safety_violation` | bool | 안전 게이트 |
| `stop_reason` | enum | 실패 유형 분류 |

`stop_reason` 허용값 (팀 합의 필요):
`OK` / `SQL_FAILURE` / `MAX_RETRY` / `MAX_REFLECTION` / `INSUFFICIENT_EVIDENCE` / `TOOL_SCHEMA_ERROR` / `TIMEOUT` / `PROVIDER_ERROR`

#### `TrialResult` — 권장 (있으면 진단 품질이 크게 올라감)

| 필드 | 타입 | 활성화되는 기능 |
|---|---|---|
| `error_type` | str \| null | Regression 그룹핑 |
| `tool_schema_valid` | bool | 시나리오 A 정밀도 |
| `llm_call_count` | int | 시나리오 B 절감 추정 |
| `scaffold_config` | object | Opportunity 탐지 (`{"planner": false, "repair": 2, "verifier": 1}`) |

#### `TraceStep` — 선택 (Trace Diff 기능 전용)

| 필드 | 타입 | 비고 |
|---|---|---|
| `run_id` / `testcase_id` / `agent_label` | str | 페어링 키 |
| `step_index` | int | 순서 |
| `node_role` | enum | **아래 고정 목록만 사용** |
| `type` | `llm_call` \| `tool_call` \| `code` | |
| `tool_name` / `arguments_valid` | str / bool | 시나리오 A |
| `error_type` | str \| null | |
| `iteration` | int | retry 회차 |
| `input_tokens` / `output_tokens` / `latency_ms` | int | |
| `outcome` | `ok` \| `fail` \| `skip` | |

`node_role` 고정 목록 — **양쪽 버전이 같은 이름을 써야 정렬이 된다:**

```text
CLASSIFY · PLAN · RETRIEVE_SCHEMA · GENERATE_QUERY · VALIDATE_QUERY
EXECUTE_TOOL · REPAIR_QUERY · CHECK_EVIDENCE · SELECT_POLICY
DECIDE · VERIFY_REASONING · GENERATE_RESPONSE
```

### 3.3 출력 — `UpgradeReport`

JSON을 먼저 만들고, 사람이 읽는 Markdown은 그 JSON을 렌더링해서 만든다.
**같은 JSON에서는 항상 같은 보고서가 나온다.** (재현성 = 대회 fallback의 근거)

```json
{
  "report_id": "rpt_20260818_001",
  "bundle_id": "audit_20260818_001",
  "verdict": "HOLD",
  "summary": {
    "testcase_count": 20,
    "trials_per_case": 2,
    "success_rate": { "v0": 0.90, "v1": 0.83, "delta_pp": -7.0 },
    "tool_error_rate": { "v0": 0.00, "v1": 0.22, "delta_pp": 22.0 },
    "avg_retry": { "v0": 0.3, "v1": 1.8, "delta": 1.5 },
    "avg_tokens": { "v0": 2401, "v1": 2906, "delta_pct": 21.0 },
    "avg_latency_ms": { "v0": 3400, "v1": 4900, "delta_pct": 44.1 },
    "safety_violation": { "v0": 0, "v1": 0 }
  },
  "findings": [
    {
      "finding_id": "F-01",
      "type": "REGRESSION",
      "severity": "P0",
      "rule_id": "R-02",
      "title": "ORDER_LOOKUP 호출에서 스키마에 없는 인자 사용",
      "affected_testcases": ["refund_003", "refund_007", "refund_012"],
      "evidence": {
        "metric": "tool_schema_valid_rate",
        "v0": 1.00, "v1": 0.78, "delta_pp": -22.0
      },
      "first_divergence": {
        "node_role": "EXECUTE_TOOL",
        "step_index": 5,
        "detail": "arguments 키가 order_id → id 로 변경됨"
      },
      "explanation": "LLM이 작성한 사람이 읽는 설명 (수치는 evidence에서만 인용)"
    }
  ],
  "candidates": [
    {
      "candidate_id": "C-01",
      "operator": "ADD_ARGUMENT_EXAMPLE",
      "target": "tool_schema:order_lookup",
      "addresses": ["F-01"],
      "change_spec": "order_lookup 설명에 정상 인자 예시 1개 추가",
      "expected_effect": "tool 스키마 오류 감소",
      "risk": "low",
      "status": "PROPOSED"
    }
  ],
  "revalidation": {
    "candidate_id": "C-01",
    "status": "PASS",
    "quality": { "success_rate": 0.92, "constraint": ">= 0.90", "ok": true },
    "safety": { "violations": 0, "constraint": "== 0", "ok": true },
    "efficiency": { "avg_tokens_delta_pct": -8.0, "improved": true }
  },
  "limitations": [
    "TestCase 20개 · 반복 2회 기준이므로 통계적 일반화는 주장하지 않음"
  ]
}
```

### 3.4 계약 위반 처리

입력이 잘못됐을 때 **조용히 넘어가지 않는다.** 보고서 최상단에 표시한다.

| 상황 | 처리 |
|---|---|
| V0에만 있고 V1에 없는 testcase | `UNPAIRED` 목록에 넣고 비교에서 제외 + 보고서에 명시 |
| 필수 필드 누락 | 해당 규칙만 `SKIPPED(reason)` 처리, 나머지는 정상 진행 |
| `traces` 없음 | Trace Diff 섹션을 `NOT_AVAILABLE`로 표기 (에러 아님) |
| 반복 횟수가 V0/V1 다름 | 경고 표시 후 평균 기준으로 비교 |
| trial 수 < 2 | 모든 Finding에 `low_confidence` 플래그 |

---

## 4. 내부 아키텍처

### 4.1 7단계 파이프라인

```text
AuditBundle (JSON)
      │
   ┌──▼──────────────────────────────────────────────┐
   │ L1  Loader & Validator      [코드]              │  스키마 검증, 페어링, 누락 표시
   ├──────────────────────────────────────────────────┤
   │ L2  Metric Aggregator       [코드]              │  성공률·retry·token·latency 집계
   ├──────────────────────────────────────────────────┤
   │ L3  Deterministic Diff      [코드]              │  V0/V1 지표 차이, flip 행렬
   ├──────────────────────────────────────────────────┤
   │ L4  Rule Detector           [코드]              │  R-/E-/O-/S- 규칙 발화 → Raw Finding
   ├──────────────────────────────────────────────────┤
   │ L5  LLM Diagnosis           [LLM]               │  묶기 · 우선순위 · 사람 언어 설명
   ├──────────────────────────────────────────────────┤
   │ L6  Candidate Generator     [코드 규칙 + LLM]   │  허용 operator 안에서 수정안 1~3개
   ├──────────────────────────────────────────────────┤
   │ L7  Re-validation Gate      [코드]              │  PASS / HOLD 판정
   └──┬───────────────────────────────────────────────┘
      │
   Report Renderer  [코드]  → UpgradeReport.json → Markdown
```

### 4.2 설계 원칙 — 코드와 LLM의 분리

> **원칙: LLM은 숫자를 만들지 않는다. 코드가 계산한 숫자를 받아서 말로 옮길 뿐이다.**

| 코드가 담당 (결정론) | LLM이 담당 (판단) |
|---|---|
| 성공/실패 집계, 성공률 | 여러 사례의 공통 실패 패턴 묶기 |
| token · latency · retry 합계와 차이 | 먼저 조사할 지점의 우선순위 정하기 |
| flip 행렬 (PASS→FAIL 등) | 변경 위험과 영향 범위를 쉬운 말로 설명 |
| JSON 스키마 유효성, 금지 SQL | 허용 범위 안에서 수정안 문안 작성 |
| PASS / HOLD 최종 판정 | 재검증 결과를 사람 언어로 정리 |

**이렇게 하는 이유 (3가지)**

1. 완료 기준에 "숫자 계산 결과와 AI 설명이 충돌하지 않는다"가 있다 → 애초에 LLM이 숫자를 못 만들게 하면 충돌이 구조적으로 불가능하다.
2. LLM 호출이 실패해도 L1~L4 + 렌더러만으로 **숫자 보고서는 나온다** → 대회 데모 중 API 장애 대비.
3. 심사에서 "이게 그냥 diff 도구 아닌가"라는 질문에 → "숫자는 코드, 해석은 AI"라는 답을 명확히 할 수 있다.

### 4.3 LLM 호출은 정확히 3곳

| 호출 | 입력 | 출력 | 실패 시 |
|---|---|---|---|
| `cluster_findings` | Raw Finding 목록 + 집계 수치 | 묶인 Finding + 제목 | 규칙 ID 그대로 나열 |
| `explain_and_rank` | 묶인 Finding | 우선순위 + 설명문 | severity 순 정렬만 |
| `write_candidates` | Finding + 허용 operator 목록 | change_spec 문안 | operator 기본 템플릿 문구 |

모든 호출은 **JSON 강제 출력 + 스키마 검증 + 1회 재시도 + 실패 시 규칙 폴백**.

> LLM 출력에 숫자가 들어오면 렌더링 단계에서 **버리고** 집계값으로 교체한다.

### 4.4 리포지토리 구조와 내 소유 영역

> **브랜치는 폴더가 아니다.** `Auditor` 브랜치에도 팀원 디렉터리는 그대로 존재한다.
> 나는 그 폴더를 **건드리지 않을 뿐**이다.

```text
agent-migration/                리포 루트
│
├─ pyproject.toml               △ 공유 (P0에서 내가 1회 생성)
├─ uv.lock                      △ 공유
├─ .gitignore  .env.example     △ 공유
├─ README.md                    △ 공유 (소유권 표)
│
├─ core/                        ★ 내 소유
│  ├─ schemas/                  ★ 내가 작성 · 팀 전원이 소비
│  ├─ diff/                     ★ 집계 · 비교
│  ├─ detector/                 ★ 규칙 카탈로그
│  ├─ report/                   ★ 렌더러 + 템플릿
│  ├─ diagnosis/                ★ LLM 클라이언트 + 프롬프트
│  ├─ candidate/                ★ operator
│  └─ validation/               ★ 재검증 게이트
│
├─ apps/
│  ├─ cli.py                    ★
│  ├─ mabc_skill/               ★ Timely AI 어댑터
│  └─ dashboard/                ☆ 결선
│
├─ fixtures/                    ★ 내 소유 (Mock 번들)
│  ├─ generator.py
│  └─ bundles/
│
├─ agents/                      □ 팀원 소유 — 수정 금지
├─ data/  policies/             □ 팀원 소유 — 수정 금지
│
├─ tests/
│  ├─ auditor/                  ★ 내 테스트
│  └─ testbed/                  □ 팀원 테스트
│
├─ docs/CONTRACT.md             ★ 내가 작성 · 팀 배포용
└─ reports/                     생성물 (gitignore)

★ 내가 만들고 고침    △ 공유(내가 초기 생성, 이후 합의 후 수정)
□ 팀원 소유(수정 금지)  ☆ 결선 이후
```

**충돌 가능 지점은 3개뿐**

| 파일 | 왜 충돌하나 | 대응 |
|---|---|---|
| `pyproject.toml` | 각자 의존성 추가 | optional 그룹으로 줄 분리 → 충돌해도 1초 |
| `README.md` | 각자 문서 추가 | 편집 빈도 낮음, 발생 시 수동 병합 |
| `core/schemas/` | 내가 소유, 전원이 소비 | `contract/*` 브랜치 → main 직접 머지 |

나머지는 디렉터리가 자연히 갈리므로 부딪힐 일이 없다.

### 4.5 Git 리포 구성 순서

> **브랜치를 먼저 파면 안 된다.** main에 뼈대를 올린 뒤 분기한다.
> 안 그러면 4명이 각자 `pyproject.toml`을 만들어 머지마다 충돌한다.

```text
[1] GitHub 리포 생성 + 팀원 3명 Collaborator 추가
[2] main에 공유 스캐폴드 1회 커밋   ← 내가 한다
      pyproject.toml / .gitignore / .env.example
      README.md(소유권 표) / 빈 디렉터리 .gitkeep
[3] main에서 브랜치 분기
      git checkout -b tester  main
      git checkout -b Auditor main
[4] main 브랜치 보호 설정 (직접 push 금지, PR 필수)
[5] Auditor에서 uv sync --extra auditor --extra dev
```

**브랜치 구조**

```text
main ─── contract/*        스키마 전용 · main으로 즉시 머지
 ├─ tester ─┬─ feat/core-graph
 │          ├─ feat/repair-loop
 │          └─ feat/dataset
 └─ Auditor                내 작업 브랜치 (개인 브랜치 추가로 안 만듦)
```

- `Auditor` 아래에 개인 이름 브랜치를 두지 않는다 — 1인 작업에 통합 브랜치는 순수 관리 비용이다
- 이틀 넘는 작업만 `feat/auditor-<이름>`으로 잠깐 분기했다가 바로 되돌린다
- **격일로 `main`을 `Auditor`에 머지**한다. 2주 넘게 안 섞으면 마지막 주에 머지 지옥이 온다

**`pyproject.toml` 의존성 분리**

```toml
[project]
name = "agent-migration"
requires-python = ">=3.11"
dependencies = ["pydantic>=2.0"]

[project.optional-dependencies]
auditor = ["typer", "jinja2", "openai", "python-dotenv"]
testbed = []          # 팀원이 채움 — 내가 건드리지 않는다
dev     = ["pytest", "ruff", "pre-commit"]
```

패키지를 둘로 쪼개지 않는 이유: 2주 반짜리 프로젝트에서 얻는 것보다 잃는 게 크다.
각자 `uv sync --extra auditor` / `--extra testbed`만 실행하면 된다.

---

## 5. 탐지 규칙 카탈로그 (L4)

규칙은 **ID로 관리**한다. 보고서의 모든 Finding은 반드시 rule_id를 달고 나온다.

### 5.1 Regression (R) — 망가진 것

| ID | 조건 | 심각도 | 근거 지표 |
|---|---|---|---|
| R-01 | testcase가 V0 PASS → V1 FAIL | P0 | flip 행렬 |
| R-02 | tool 인자 스키마 유효율 하락 | P0 | `tool_schema_valid` |
| R-03 | 정책 판정 정확도 하락 | P0 | `policy_correct` |
| R-04 | `stop_reason` 분포 악화 (MAX_RETRY·TOOL_SCHEMA_ERROR 증가) | P1 | stop_reason 분포 |
| R-05 | 특정 난이도 구간에서만 성공률 하락 | P1 | difficulty별 성공률 |

### 5.2 Efficiency (E) — 비싸진 것

| ID | 조건 (기본 임계값) | 심각도 | 근거 지표 |
|---|---|---|---|
| E-01 | 평균 retry 증가 ≥ 0.5회 | P1 | `retry_count` |
| E-02 | 평균 token 증가 ≥ 15% | P2 | `total_tokens` |
| E-03 | 평균 latency 증가 ≥ 20% | P2 | `latency_ms` |
| E-04 | 평균 step 수 증가 ≥ 20% | P2 | TraceStep 개수 |

### 5.3 Opportunity (O) — 줄일 수 있는 것

| ID | 조건 | 심각도 | 근거 지표 |
|---|---|---|---|
| O-01 | Verifier가 전체 케이스에서 판정을 **한 번도 바꾸지 않음** | P1 | VERIFY_REASONING 전후 decision |
| O-02 | 동일 error_type 재시도의 recovery rate ≈ 0 | P1 | iteration별 outcome |
| O-03 | 특정 node가 모든 케이스에서 outcome=ok이며 downstream 영향 없음 | P2 | node별 영향 분석 |

### 5.4 Safety (S) — 절대 제거 후보로 만들지 않는 것

| ID | 조건 | 처리 |
|---|---|---|
| S-01 | `safety_violation == true` 발생 | **verdict 즉시 BLOCK**, 다른 모든 추천보다 우선 |
| S-02 | SELECT-only 위반, 금지 SQL, 허용 외 테이블 접근 | 동일 |

> **불변 규칙:** 결정론적 안전 검사(SQL Guard, 스키마 검증, 금지 명령 차단)는
> 모델이 아무리 좋아져도 **REMOVE 후보로 제안하지 않는다.** L6에서 하드 차단.

### 5.5 오탐 방지 (False Alarm)

대회 심사에서 "정상 변경을 억지로 문제라고 말한다"는 인상은 치명적이다.

| 장치 | 내용 |
|---|---|
| 최소 표본 | 영향 케이스 1건뿐이고 반복 2회 미만이면 `INCONCLUSIVE`로 강등 |
| 개선 동시 표기 | Regression만 보여주지 않고 Improvement를 같은 화면에 반드시 표시 |
| 임계값 명시 | 모든 E 규칙은 보고서에 임계값을 같이 출력 (`+21% ≥ 임계 15%`) |
| 음성 대조 케이스 | **의도적으로 아무 문제 없는 V0/V1 쌍**을 넣었을 때 "이상 없음"이 나오는지 테스트 |

---

## 6. 수정 후보 (L6) — 예선은 4개 operator만

| Operator | 대응 Finding | 변경 대상 | 데모 |
|---|---|---|---|
| `ADD_ARGUMENT_EXAMPLE` | R-02 | tool schema 설명 | 시나리오 A |
| `ADD_SCHEMA_VALIDATOR` | R-02 | 코드 검증 단계 | 시나리오 A |
| `CONDITIONAL_VERIFIER` | O-01 | verifier 설정 | 시나리오 B |
| `REDUCE_MAX_RETRY` / `STOP_ON_REPEAT` | E-01, O-02 | retry 설정 | 시나리오 C |

**후보 생성 규칙**

```text
Finding(rule_id) ──> 규칙 매핑 테이블 ──> 허용 operator 후보군
                                              │
                          LLM은 이 후보군 "안에서만" 문안을 쓴다
                                              │
                                     최대 3개까지만 출력
```

- 목록에 없는 operator는 LLM이 제안해도 **버린다.**
- 모든 후보는 `status: PROPOSED`로 시작하며, 재검증 전에는 절대 `APPLIED`가 될 수 없다.
- 후보에는 반드시 `addresses`(어떤 Finding을 해결하는지)와 `risk`가 붙는다.

---

## 7. 재검증 게이트 (L7)

수정 후보를 적용한 V2 실행 결과를 다시 넣으면 동일 파이프라인을 돌려 판정한다.

```text
V0 vs V1  →  Finding + Candidate
                   │
              (사람이 적용)
                   ▼
V0 vs V2  →  같은 지표로 재비교  →  PASS / HOLD / INCONCLUSIVE
```

| 제약 | 조건 | 위반 시 |
|---|---|---|
| 품질 | 성공률이 V0 대비 하락하지 않음 | HOLD |
| 안전 | `safety_violation == 0` | **BLOCK (무조건)** |
| 효율 | token · latency · retry 중 **최소 1개** 개선 | HOLD (개선 없음) |
| 표본 | 반복 2회 이상, 영향 케이스 2건 이상 | INCONCLUSIVE |

> 판정은 **코드만** 내린다. LLM은 판정 결과를 설명만 한다.

---

## 8. 보고서 형식 (고정)

모든 출력은 아래 6개 섹션을 **항상 같은 순서로** 낸다. 비어 있으면 "해당 없음"을 쓴다.

```text
─────────────────────────────────────────────
 Agent Upgrade Risk Report
─────────────────────────────────────────────
 1. Summary        판정(PASS/HOLD/BLOCK) + 핵심 지표 5개
 2. Regression     망가진 것 (P0부터)
 3. Efficiency     비싸진 것 + 임계값
 4. Trace Diff     최초로 갈라진 지점 (trace 있을 때만)
 5. Recommendation 수정 후보 1~3개 + 근거 Finding
 6. Risk & Limits  재검증 상태 + 이 결론이 말하지 못하는 것
─────────────────────────────────────────────
```

**Trace Diff 표시 예시**

```text
refund_003

V0  CLASSIFY → GENERATE_QUERY → EXECUTE_TOOL(ok) → SELECT_POLICY → DECIDE ✔
V1  CLASSIFY → GENERATE_QUERY → EXECUTE_TOOL(FAIL) → REPAIR → EXECUTE_TOOL(FAIL) ✘
                                        ▲
                              최초 주요 차이 (step 5)
                              arguments: order_id → id
```

---

## 9. 대회 데모 3종 — 내가 보여줄 것

| 시나리오 | 내가 보여주는 화면 | 사용할 규칙 → 후보 | 필요한 입력 |
|---|---|---|---|
| **A. Tool 인자 회귀** | 유효율 100%→78%, 최초 차이 = EXECUTE_TOOL, 후보 2개 | R-02 → ADD_ARGUMENT_EXAMPLE / ADD_SCHEMA_VALIDATOR | tool 인자 위반이 섞인 V1 실행 기록 |
| **B. 불필요해진 검증** | "20/20에서 판정 불변" + LLM 호출 -1/건 절감 추정 | O-01 → CONDITIONAL_VERIFIER | VERIFY_REASONING trace |
| **C. 과도한 재시도** | 평균 retry 0.3→1.8, 회복률 0%, retry 5→2 후보 | E-01 + O-02 → REDUCE_MAX_RETRY | iteration 포함 trace |

- 각 시나리오는 **재검증까지 한 사이클**을 보여준다. 발견에서 끝내지 않는다.
- 세 시나리오 모두 **P1에서 만든 Mock 픽스처로 먼저 완성**한다.
- 실데이터는 P9(8/28~29)에서 갈아끼우고, 8/26까지 안 오면 Mock 데모로 확정한다.

---

## 10. 개발 일정 (요약)

> 상세 순서·체크리스트·완료 게이트는 짝 문서 `Phase별_개발순서.md` 참조.

| Phase | 기간 | 내가 끝내는 것 |
|---|---|---|
| P0 Git 구성 | 8/15 | main 스캐폴드 커밋 → 브랜치 분기 → 로컬 환경 |
| P1 계약 동결 | 8/15~17 | 스키마 + Mock 픽스처 + CONTRACT.md 배포 |
| P2 결정론 코어 | 8/18~20 | 로더·집계·Diff·flip 행렬 |
| P3 규칙 탐지기 | 8/20~22 | R/E/O/S 규칙 + 오탐 방지 |
| P4 보고서 렌더러 | 8/22~23 | **LLM 없는 완성 보고서** ★ |
| P5 LLM 진단 | 8/23~25 | 묶기·우선순위·숫자 방어 |
| P6 후보 생성 | 8/25~26 | operator 4종 + 안전 차단 |
| P7 재검증 게이트 | 8/26~27 | PASS/HOLD/BLOCK 판정 |
| P8 Skill 어댑터 | 8/27~28 | Timely AI end-to-end |
| P9 실데이터 통합 | 8/28~29 | Mock → 실제 trace 교체 |
| P10 Freeze | 8/30~31 | Replay + 제출 |
| P11 결선 | 9/9~18 | Runner · Dashboard |

**병렬 개발 원칙**

```text
P0 ─ P1 ─ P2 ─ P3 ─ P4 ─ P5 ─ P6 ─ P7 ─ P8 ────── P9 ─ P10
     │                                              │
     │  ← 여기까지 Mock으로 진행 (외부 의존 0) →      │
     └─ 8/17 CONTRACT.md 배포 ─────────────────────┘
```

팀원의 Testbed 완성을 **기다리지 않는다.** Mock으로 먼저 완성하고 P9에서 갈아끼운다.

---

## 11. 완료 기준 (Definition of Done)

### 예선 Must

- [ ] `AuditBundle` 하나로 V0/V1을 비교하고 **같은 입력에서 같은 출력**이 나온다
- [ ] Regression / Improvement / Efficiency Warning 분류가 동작한다
- [ ] 성공률·오류·retry·step·token·latency 비교표가 나온다
- [ ] 우선 확인할 문제 1~3개와 최소 수정안 1~3개가 나온다
- [ ] 비개발자가 읽을 수 있는 보고서 형식으로 출력된다
- [ ] TestCase 20개 규모의 대표 데이터셋 1개가 있다
- [ ] **LLM 호출 없이도 숫자 보고서가 생성된다** (fallback)

### 예선 Should

- [ ] 최초로 갈라진 지점(Trace Diff)이 표시된다
- [ ] 단순화 기회(O-01 또는 O-02) 최소 1건을 찾는다
- [ ] 수정 후 결과를 다시 넣으면 회복 여부를 재평가한다
- [ ] 문제 없는 V0/V1 쌍에 대해 "이상 없음"이 나온다 (오탐 테스트)

### 품질 기준

- [ ] 모든 Finding에 rule_id · 근거 지표 · 영향 케이스 목록이 붙는다
- [ ] 모든 추천에 근거 Finding · 예상 효과 · 재검증 상태가 붙는다
- [ ] 보고서 어디에도 근거 없는 숫자가 없다
- [ ] 플랫폼 연동 없이 저장된 JSON만으로 동일 보고서를 재생성할 수 있다

---

## 12. 위험과 대응

| 위험 | 조기 신호 | 대응 |
|---|---|---|
| Testbed 지연으로 입력 데이터가 없음 | 8/22까지 실제 trace 미수신 | **Mock 픽스처로 전 기능 완성** (M1~M3 전부 Mock 기반) |
| 필드 누락으로 규칙이 못 돌아감 | 실제 데이터에 `stop_reason` 없음 | 규칙별 `SKIPPED` 처리 + 8/17 요구 필드 사전 공지 |
| Timely AI 제약으로 Skill 구현 불가 | 8/17 플랫폼 확인 결과 | **Level 0 고정** — 사용자가 JSON 붙여넣는 단일 Skill |
| 데모 중 API 장애 | — | 저장된 JSON → 보고서 재생성 replay 준비 |
| LLM이 근거 없는 숫자 생성 | 검토 중 수치 불일치 발견 | 렌더링 단계에서 LLM 숫자 폐기 + 집계값 강제 치환 |
| 오탐으로 신뢰도 하락 | 정상 변경에 경고 발생 | 음성 대조 케이스 필수 테스트 + 임계값 명시 |
| 범위 초과 | Dashboard·Runner에 시간 소모 | 예선 Must 완료 전 착수 금지 |

---

## 13. 기술 스택 (요약)

> 상세 개발 환경 구성은 별도 문서에서 다룬다.

| 영역 | 선택 | 이유 |
|---|---|---|
| 언어 | Python 3.11 | 팀 공통, Testbed와 동일 |
| 스키마 | **Pydantic v2** | 계약을 코드로 강제. 계약 문서 = 스키마 파일 |
| 패키지 | uv | 빠름, lock 파일로 팀 환경 통일 |
| 테스트 | pytest + 골든 파일 | 같은 입력 → 같은 보고서 회귀 방지 |
| CLI | Typer | `auditor run --bundle x.json` |
| 렌더링 | Jinja2 | 보고서 템플릿 고정 |
| LLM | Upstage Solar (OpenAI 호환 여부 8/17 확인) | 대회 지정 |
| 대시보드 | Streamlit (결선) | 빠른 구현 |
| 품질 | ruff + pre-commit | PR 리뷰 부담 감소 |

**작업 규칙**

| 규칙 | 내용 |
|---|---|
| 내 브랜치 | `Auditor`에서 직접 작업 |
| 스키마 변경 | `contract/*` → **main 직접 머지** (Auditor에 가두지 않음) |
| 동기화 | 격일로 `git checkout Auditor && git merge main` |
| 커밋 | `<phase>: <무엇을>` 예) `P3: E-01 재시도 증가 규칙 추가` |
| PR 첨부 | 정상 사례 1개 + 실패 사례 1개 + 생성된 보고서 샘플 |
| 태그 | `mabc-prelim` (8/31) · `mabc-final` (결선 종료) |

상세 구성 절차는 4.5절 참조.

---

## 14. 8/17까지 확인해야 할 미확정 사항

| # | 확인 대상 | 결과에 따른 분기 |
|---|---|---|
| 1 | Timely AI Skill의 입력 형식 (긴 JSON 텍스트 허용 여부, 길이 제한) | 초과 시 요약 번들 포맷 별도 정의 |
| 2 | Timely AI의 외부 API 호출 가능 여부 | 불가 시 Level 0 확정 |
| 3 | Timely AI의 파일 업로드 가능 여부 | 불가 시 텍스트 붙여넣기 UX로 설계 |
| 4 | Solar 모델의 JSON 강제 출력 지원 여부 | 미지원 시 파싱 + 재시도 강화 |
| 5 | 팀 합의: `stop_reason` enum 값 확정 | 미확정 시 R-04 규칙 보류 |
| 6 | 팀 합의: `node_role` 고정 목록 확정 | 미확정 시 Trace Diff 보류 |
| 7 | 대회 팀 인원 규정 (최대 3인 명시 확인 필요) | 제출 명의 조정 |

---

## 부록 A. 용어 사전

| 용어 | 쉬운 설명 |
|---|---|
| V0 / Baseline | 바꾸기 **전** Agent 버전 |
| V1 / Candidate Version | 바꾼 **후** Agent 버전 |
| AuditBundle | 두 버전의 실행 기록을 한 덩어리로 묶은 입력 파일 |
| Trial | 같은 문제를 한 번 실행한 기록 (같은 문제를 2~3번 반복) |
| Trace / TraceStep | Agent가 거쳐간 단계별 기록 |
| Finding | Auditor가 찾아낸 문제 1건 |
| Candidate | 제안하는 수정안 1건 (아직 적용 안 됨) |
| Operator | 허용된 수정 방식의 종류 (예: 재시도 횟수 줄이기) |
| Flip | 같은 문제가 V0에서는 성공, V1에서는 실패로 뒤집힌 것 |
| Scaffold | 모델의 부족함을 메우는 보조 구조 (Planner, Repair, Verifier) |
| Regression | 되던 게 안 되게 된 것 |
| Re-validation | 수정안을 같은 시험으로 다시 돌려 확인하는 절차 |
| False Alarm | 문제 없는데 문제라고 잘못 말하는 것 |
| Deterministic | 같은 입력이면 항상 같은 결과 (코드 계산) |

## 부록 B. 규칙 ID 빠른 참조

```text
R-01  PASS → FAIL 뒤집힘                    P0
R-02  tool 인자 스키마 유효율 하락           P0
R-03  정책 판정 정확도 하락                  P0
R-04  종료 사유 분포 악화                    P1
R-05  난이도 구간별 성공률 하락               P1

E-01  평균 재시도 증가 (≥0.5회)              P1
E-02  평균 토큰 증가 (≥15%)                  P2
E-03  평균 지연 증가 (≥20%)                  P2
E-04  평균 단계 수 증가 (≥20%)                P2

O-01  Verifier가 판정을 한 번도 안 바꿈       P1
O-02  재시도 회복률 ≈ 0                      P1
O-03  영향 없는 중복 노드                     P2

S-01  안전 위반 발생 → BLOCK                 최우선
S-02  SQL 안전 규칙 위반 → BLOCK             최우선
```

---

*작성 2026-08-15 · Agent Upgrade Auditor (소현) · MABC 2026*
