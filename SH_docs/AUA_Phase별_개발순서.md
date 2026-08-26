# Agent Upgrade Auditor — Phase별 개발 순서

> **이 문서에 적힌 모든 항목은 내가 직접 하는 작업이다.**
> 팀원(준원·채린·우혁)의 작업은 포함하지 않는다.
> 팀원 산출물이 필요한 지점은 "내가 요청하는 행동"으로만 표기한다.

| 항목 | 내용 |
|---|---|
| 작성 | 2026-08-15 |
| 담당 | 소현 — Agent Upgrade Auditor |
| 작업 브랜치 | `Auditor` |
| 예선 | 2026-08-18 ~ 08-31 |
| 결선 | 2026-09-09 ~ 09-18 (최종발표 09-19) |

---

## 0. 전체 순서

```text
P0  Git 구성            8/15      ← 코드 작성 전, 최초 1회
     │
P1  계약 동결           8/15~17   ← 스키마 + 픽스처 + CONTRACT.md
     │
P2  결정론 코어         8/18~20   ┐
P3  규칙 탐지기         8/20~22   │
P4  보고서 렌더러       8/22~23   ├─ 전부 Mock 기반 · 팀원 진도와 무관
P5  LLM 진단            8/23~25   │
P6  후보 생성           8/25~26   │
P7  재검증 게이트       8/26~27   ┘
     │
P8  Skill 어댑터        8/27~28
P9  실데이터 통합       8/28~29   ← 팀원 산출물이 필요한 유일한 구간
P10 Freeze · 제출       8/30~31
     │
P11 결선 확장           9/9~18
```

**순서 근거 3가지**

| 결정 | 이유 |
|---|---|
| Git 구성이 코드보다 먼저 | 4명이 각자 `pyproject.toml`을 만들면 머지할 때마다 충돌한다 |
| 계약(P1)이 로직보다 먼저 | 스키마가 늦으면 팀원 로그에 필드가 빠지고, 그건 나중에 못 고친다 |
| 렌더러(P4)가 LLM(P5)보다 먼저 | fallback을 나중에 만드는 보험이 아니라 **기본 동작**으로 만들기 위해 |

---

## 1. 리포지토리 구조와 내 소유 영역

> **브랜치는 폴더가 아니다.** `Auditor` 브랜치에도 팀원 디렉터리는 그대로 존재한다.
> 나는 그 폴더를 **건드리지 않을 뿐**이다.

```text
agent-migration/                리포 루트
│
├─ pyproject.toml               △ 공유 (P0에서 내가 1회 생성)
├─ uv.lock                      △ 공유
├─ .gitignore  .env.example     △ 공유 (P0에서 내가 1회 생성)
├─ README.md                    △ 공유 (소유권 표)
│
├─ core/                        ★ 내 소유
│  ├─ schemas/                  ★ 내가 작성 · 팀 전원이 소비
│  ├─ diff/                     ★ P2
│  ├─ detector/                 ★ P3
│  ├─ report/                   ★ P4
│  ├─ diagnosis/                ★ P5
│  ├─ candidate/                ★ P6
│  └─ validation/               ★ P7
│
├─ apps/
│  ├─ cli.py                    ★ P4
│  ├─ mabc_skill/               ★ P8
│  └─ dashboard/                ☆ P11 (결선)
│
├─ fixtures/                    ★ 내 소유 (Mock 번들)
│  ├─ generator.py
│  └─ bundles/
│
├─ agents/                      □ 팀원 소유 — 열어보기만, 수정 금지
├─ data/  policies/             □ 팀원 소유 — 열어보기만, 수정 금지
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

### 충돌 가능 지점은 3개뿐

| 파일 | 왜 충돌하나 | 대응 |
|---|---|---|
| `pyproject.toml` | 각자 의존성 추가 | optional 그룹으로 줄을 분리 → 충돌해도 1초 |
| `README.md` | 각자 문서 추가 | 편집 빈도 낮음. 발생 시 수동 병합 |
| `core/schemas/` | 내가 소유, 전원이 소비 | **`contract/*` 브랜치 → main 직접 머지** |

나머지는 디렉터리가 자연히 갈리므로 부딪힐 일이 없다.

---

# P0 — Git 구성

**날짜** 8/15(토) · 반나절
**목표** 팀 전원이 같은 뼈대 위에서 각자 브랜치를 팔 수 있게 만든다.
**선행 조건** 없음
**작업 위치** `main` → 이후 `Auditor`

> 이건 코드 작업이 아니라 **환경 세팅**이다. 이게 끝나야 P1을 시작한다.

### P0-1. 리포 생성과 클론

- [ ] GitHub에 `agent-migration` 리포 생성 (Private, 팀원 3명 Collaborator 추가)
- [ ] 로컬 클론

```bash
git clone git@github.com:<계정>/agent-migration.git
cd agent-migration
```

### P0-2. main에 공유 스캐폴드 1회 커밋 ★

> **브랜치를 먼저 파면 안 된다.** main에 뼈대를 올린 뒤 분기한다.

- [ ] `pyproject.toml` 작성 — optional 그룹으로 팀별 의존성 분리

```toml
[project]
name = "agent-migration"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["pydantic>=2.0"]

[project.optional-dependencies]
auditor = ["typer", "jinja2", "openai", "python-dotenv"]
testbed = []          # 팀원이 채움 — 내가 건드리지 않는다
dev     = ["pytest", "ruff", "pre-commit"]
```

- [ ] `.gitignore` — `.env`, `reports/`, `__pycache__`, `.venv`, `*.db`
- [ ] `.env.example` — 키 이름만 (값 없이)
- [ ] `README.md` — **디렉터리 소유권 표**와 브랜치 규칙만 (내용은 나중에)
- [ ] 빈 디렉터리에 `.gitkeep` 배치 (위 구조 그대로)
- [ ] 커밋 & 푸시

```bash
git add .
git commit -m "chore: 리포 스캐폴드 및 디렉터리 소유권 정의"
git push origin main
```

### P0-3. 브랜치 분기

- [ ] main에서 두 브랜치 생성

```bash
git checkout -b tester  main && git push -u origin tester
git checkout -b Auditor main && git push -u origin Auditor
```

- [ ] GitHub에서 `main` 브랜치 보호 설정 (직접 push 금지, PR 필수)
- [ ] 기본 브랜치는 `main` 유지

### P0-4. 내 로컬 개발 환경

- [ ] `Auditor` 브랜치로 이동해 환경 구성

```bash
git checkout Auditor
uv sync --extra auditor --extra dev
```

- [ ] `.env` 생성 (Solar API 키) — **커밋 안 되는지 확인**
- [ ] `pre-commit install`
- [ ] `ruff check .` 통과 확인

### P0-5. 팀 공지 (내가 보내는 것)

- [ ] 리포 주소 + 브랜치 규칙 공유
- [ ] "`agents/`, `data/`, `policies/`는 팀원 영역이며 내가 건드리지 않는다" 명시
- [ ] "`pyproject.toml`의 `testbed` 그룹은 비워뒀으니 채워달라" 요청
- [ ] "`core/schemas/`는 내가 소유하며 변경은 `contract/*`로 main에 직접 간다" 공지

### ✅ P0 완료 게이트

- [ ] `main` · `tester` · `Auditor` 세 브랜치가 원격에 존재한다
- [ ] `Auditor`에서 `uv sync`가 성공한다
- [ ] 팀원이 각자 `tester`에서 feature 브랜치를 팔 수 있다
- [ ] `.env`가 git status에 안 잡힌다

---

# P1 — 계약 동결

**날짜** 8/15(토) ~ 8/17(월) · 2.5일
**목표** 팀 전원이 같은 JSON을 읽고 쓸 수 있게 만든다.
**선행 조건** P0
**작업 위치** `contract/schema-v1` (스키마) + `Auditor` (나머지)

> 이번 주 유일한 크리티컬 패스. 여기가 늦으면 팀원 로그에 필드가 빠지고 P9에서 복구 불가능하다.

### P1-1. Pydantic 스키마 작성 (1.5일) ★최우선

`core/schemas/` 에 작성. **이 파일이 곧 계약 문서다.**

- [ ] `agent_version.py` — `AgentVersion`
- [ ] `trial.py` — `TrialResult`
- [ ] `trace.py` — `TraceStep`
- [ ] `bundle.py` — `AuditBundle` (최상위 입력)
- [ ] `finding.py` — `Finding`, `Candidate`
- [ ] `report.py` — `UpgradeReport` (최종 출력)
- [ ] `enums.py` — `StopReason`, `NodeRole`, `FindingType`, `Severity`, `Verdict`
- [ ] 필수/선택을 `Optional`로 명확히 구분
- [ ] JSON Schema 내보내기 함수 1개 (`export_schemas()`)

**Enum 확정값 (내가 정하고 통보한다)**

```text
StopReason:  OK / SQL_FAILURE / MAX_RETRY / MAX_REFLECTION /
             INSUFFICIENT_EVIDENCE / TOOL_SCHEMA_ERROR / TIMEOUT / PROVIDER_ERROR

NodeRole:    CLASSIFY / PLAN / RETRIEVE_SCHEMA / GENERATE_QUERY / VALIDATE_QUERY /
             EXECUTE_TOOL / REPAIR_QUERY / CHECK_EVIDENCE / SELECT_POLICY /
             DECIDE / VERIFY_REASONING / GENERATE_RESPONSE

FindingType: REGRESSION / IMPROVEMENT / EFFICIENCY_WARNING /
             OPTIMIZATION_OPPORTUNITY / SAFETY_ALERT / INCONCLUSIVE

Verdict:     PASS / HOLD / BLOCK
```

### P1-2. Mock 픽스처 생성기 (0.5일)

**팀원 없이 P2~P8을 개발하기 위한 핵심 도구.** `fixtures/generator.py`

우선순위 순서로 만든다. 시간이 부족하면 위 2개만 먼저.

| 순위 | 픽스처 | 내용 | 발화해야 할 규칙 |
|---|---|---|---|
| 1 | `scenario_a.json` | V1 일부가 tool 인자 스키마 위반 | R-02 |
| 2 | `scenario_clean.json` | **문제 없는 정상 변경** | 아무것도 안 나와야 함 ★ |
| 3 | `scenario_c.json` | 동일 오류 5회 반복, 회복률 0 | E-01, O-02 |
| 4 | `scenario_b.json` | Verifier가 판정을 한 번도 안 바꿈 | O-01 |
| 5 | `scenario_safety.json` | safety_violation 1건 | S-01 → BLOCK |
| 6 | `scenario_broken.json` | 필수 필드 누락, 페어링 실패 | 계약 위반 처리 |

- [ ] 시드 고정 (같은 시드 → 같은 번들)
- [ ] TestCase 20개 · trial 2회 규모
- [ ] trace 포함/미포함 버전 각각 생성

### P1-3. CONTRACT.md 작성 (0.5일)

`docs/CONTRACT.md` — **팀원에게 "이 필드를 남겨달라"고 요청하는 문서.**

- [ ] `TrialResult` 필수 필드 표 + "없으면 못 하는 것" 열
- [ ] `TraceStep` 선택 필드 표
- [ ] Enum 확정값 목록
- [ ] 샘플 JSON 1건 (복붙 가능한 형태)
- [ ] 필드 누락 시 어떻게 되는지 (규칙 SKIPPED 처리) 설명

### P1-4. 배포 (내가 하는 행동)

- [ ] `contract/schema-v1` 브랜치 → **main에 PR 머지**
- [ ] `main`을 `Auditor`에 머지
- [ ] 팀 채널에 CONTRACT.md 링크 + Enum 확정 통보
- [ ] "이의는 8/19까지" 기한 명시

### ✅ P1 완료 게이트

- [ ] `core/schemas/`가 **main에 있다** (Auditor 브랜치가 아니라)
- [ ] `fixtures/bundles/`에 최소 3종(a, clean, c)이 생성된다
- [ ] `docs/CONTRACT.md`가 배포됐다
- [ ] 팀원이 샘플 JSON을 보고 자기 출력 형식을 맞출 수 있다

---

# P2 — 결정론 코어

**날짜** 8/18(화) ~ 8/20(목) · 3일
**목표** Mock 번들을 넣으면 숫자 표가 나온다. LLM 호출 0회.
**선행 조건** P1
**작업 위치** `Auditor`

### P2-1. Loader & Validator — `core/schemas/loader.py`

- [ ] JSON → `AuditBundle` 파싱 + 스키마 검증
- [ ] **페어링**: V0/V1을 `testcase_id`로 매칭
- [ ] `UNPAIRED` 목록 분리 (한쪽에만 있는 케이스)
- [ ] 필수 필드 누락 → 해당 규칙만 `SKIPPED(reason)` (전체 실패 아님)
- [ ] trial 수 < 2 → 전역 `low_confidence` 플래그

### P2-2. Metric Aggregator — `core/diff/aggregate.py`

testcase별 → 버전별 → 전체 순으로 집계.

| 지표 | 계산 |
|---|---|
| success_rate | task_success 평균 |
| policy_accuracy | policy_correct 평균 |
| tool_error_rate | tool_error_count > 0 비율 |
| avg_retry | retry_count 평균 |
| avg_tokens / avg_latency_ms | 평균 |
| stop_reason 분포 | 값별 카운트 |
| safety_violation | 합계 |

- [ ] trial 반복은 평균으로 축약하되 원본도 보존
- [ ] difficulty 필드가 있으면 난이도별로도 집계

### P2-3. Diff Engine — `core/diff/compare.py`

- [ ] 모든 지표의 `delta` / `delta_pp` / `delta_pct` 계산
- [ ] **Flip 행렬** 산출

```text
              V1 PASS      V1 FAIL
V0 PASS      preserved    regression ★
V0 FAIL      improvement  persistent
```

- [ ] testcase별 flip 분류 결과 저장
- [ ] 0 나눗셈 · 빈 목록 방어

### P2-4. 골든 테스트 첫 세트 — `tests/auditor/golden/`

- [ ] 각 픽스처 → 기대 집계값 JSON 저장
- [ ] pytest로 재실행 시 동일성 검증
- [ ] 이후 모든 Phase에서 회귀 방지선 역할

### ✅ P2 완료 게이트

- [ ] `scenario_a.json` → 성공률·retry·token 비교표가 출력된다
- [ ] flip 행렬에서 regression 케이스 목록이 나온다
- [ ] 골든 테스트 통과
- [ ] **LLM 호출 0회**

---

# P3 — 규칙 탐지기

**날짜** 8/20(목) ~ 8/22(토) · 2.5일
**목표** 픽스처마다 "의도한 규칙만" 발화한다.
**선행 조건** P2

### P3-1. 규칙 인터페이스 — `core/detector/base.py`

```text
Rule
 ├─ rule_id       "R-02"
 ├─ severity      P0 / P1 / P2
 ├─ requires      필요한 필드 목록 (없으면 SKIPPED)
 ├─ threshold     임계값 (보고서에 함께 출력)
 └─ evaluate(diff) -> Finding | None
```

- [ ] 레지스트리 방식으로 규칙을 하나씩 등록
- [ ] 필요 필드가 없으면 예외가 아니라 `SKIPPED` 반환

### P3-2. 규칙 구현 순서

| 순서 | 규칙 | 근거 필드 | 데모 |
|---|---|---|---|
| 1 | **R-01** PASS→FAIL 뒤집힘 | task_success | 공통 |
| 2 | **R-02** tool 인자 유효율 하락 | tool_schema_valid | A |
| 3 | **E-01** 평균 retry 증가 ≥0.5 | retry_count | C |
| 4 | **O-02** 재시도 회복률 ≈0 | trace iteration | C |
| 5 | **O-01** Verifier 판정 불변 | trace VERIFY_REASONING | B |
| 6 | **S-01/S-02** 안전 위반 | safety_violation | BLOCK |
| 7 | R-03 정책 정확도 하락 | policy_correct | |
| 8 | R-04 stop_reason 악화 | stop_reason | |
| 9 | E-02/E-03/E-04 토큰·지연·단계 | 각 지표 | |
| 10 | R-05 난이도별 하락 · O-03 무영향 노드 | 여유 있으면 | |

> 1~6번이 데모 3종을 커버한다. **여기까지가 필수.** 7~10은 여유분.

### P3-3. 오탐 방지 장치

- [ ] 영향 케이스 1건 + trial<2 → `INCONCLUSIVE`로 강등
- [ ] 모든 E 규칙은 Finding에 임계값을 함께 담는다 (`+21% ≥ 임계 15%`)
- [ ] Improvement도 Finding으로 생성 (Regression만 보여주지 않기)

### ✅ P3 완료 게이트

- [ ] `scenario_a` → R-02 발화, 다른 규칙은 조용
- [ ] `scenario_c` → E-01 + O-02 발화
- [ ] `scenario_b` → O-01 발화
- [ ] **`scenario_clean` → Finding 0건** ★ 이게 제일 중요
- [ ] `scenario_safety` → verdict BLOCK
- [ ] trace 없는 번들에서 O 규칙이 `SKIPPED` 처리되고 나머지는 정상 동작

---

# P4 — 보고서 렌더러

**날짜** 8/22(토) ~ 8/23(일) · 1.5일
**목표** **LLM 없이도 완성된 보고서 1장이 나온다.**
**선행 조건** P3

> 이 Phase를 LLM보다 먼저 두는 게 이 계획의 핵심이다.
> fallback을 나중에 만들면 급할 때 못 만든다. 처음부터 기본 동작으로 만든다.

### P4-1. UpgradeReport 조립 — `core/report/build.py`

- [ ] Finding 정렬: severity(P0→P2) → 영향 케이스 수 → rule_id
- [ ] verdict 결정: 안전 위반 → BLOCK, P0 존재 → HOLD, 없음 → PASS
- [ ] `limitations` 자동 생성 (표본 수, trial 수, trace 유무 명시)

### P4-2. Markdown 템플릿 — `core/report/templates/`

6개 섹션 **고정 순서**, 비어도 "해당 없음"을 출력한다.

```text
1. Summary        판정 + 핵심 지표 5개
2. Regression     P0부터
3. Efficiency     증가폭 + 임계값
4. Trace Diff     최초 갈라진 지점 (없으면 NOT_AVAILABLE)
5. Recommendation 후보 (P6 이전에는 "준비 중")
6. Risk & Limits  재검증 상태 + 한계
```

- [ ] Trace Diff는 텍스트 화살표로 표현
- [ ] 모든 수치 옆에 V0/V1 원본값 병기

### P4-3. CLI — `apps/cli.py`

```bash
uv run auditor run \
  --bundle fixtures/bundles/scenario_a.json \
  --out reports/rpt_a \
  --no-llm
```

- [ ] `--no-llm` 플래그를 **지금** 만든다 (P5에서 쓸 것)
- [ ] JSON + Markdown 동시 출력

### ✅ P4 완료 게이트

- [ ] 픽스처 전부에서 보고서 Markdown이 생성된다
- [ ] **LLM 없이 사람이 읽을 수 있는 보고서가 완성된다** ← 예선 Must 절반 완료
- [ ] 같은 입력 → 같은 보고서 (골든 테스트)

---

# P5 — LLM 진단 계층

**날짜** 8/23(일) ~ 8/25(화) · 2일
**목표** 보고서에 사람 언어 설명이 붙는다. 단, 숫자는 절대 LLM이 만들지 않는다.
**선행 조건** P4

### P5-1. Solar 클라이언트 래퍼 — `core/diagnosis/client.py`

- [ ] 타임아웃 · 1회 재시도 · 실패 시 예외 대신 `None` 반환
- [ ] JSON 강제 출력 + Pydantic 검증, 파싱 실패 시 1회 재요청
- [ ] 호출 로그 저장 (프롬프트 해시, 토큰, 지연)
- [ ] API 키는 `.env`에서 로드

### P5-2. LLM 호출 3곳만 구현

| 순서 | 함수 | 출력 | 실패 시 폴백 |
|---|---|---|---|
| 1 | `cluster_findings` | 묶인 Finding + 제목 | rule_id 그대로 나열 |
| 2 | `explain_and_rank` | 우선순위 + 설명문 | severity 정렬만 |
| 3 | `write_candidates` | change_spec 문안 | operator 기본 템플릿 (P6) |

- [ ] 프롬프트를 파일로 분리 (`core/diagnosis/prompts/`)
- [ ] 각 호출은 독립 실패 가능 — 하나 실패해도 나머지 진행

### P5-3. 숫자 방어 장치 ★

- [ ] LLM 출력 스키마에서 수치 필드를 아예 제거 (설명 텍스트만 받음)
- [ ] 설명문에 숫자 패턴이 있으면 경고 로그 + 집계값 참조로 교체
- [ ] 골든 테스트: LLM on/off 두 경우의 **수치 섹션이 완전히 동일**한지 검증

### ✅ P5 완료 게이트

- [ ] `--no-llm`과 기본 실행 모두 보고서가 나온다
- [ ] 두 경우의 수치가 100% 동일하다
- [ ] 네트워크를 끊어도 보고서가 생성된다
- [ ] 비슷한 Regression 3건이 하나로 묶여 나온다

---

# P6 — 수정 후보 생성

**날짜** 8/25(화) ~ 8/26(수) · 1.5일
**목표** 시나리오마다 올바른 후보가 1~3개 나온다.
**선행 조건** P5

### P6-1. Operator 정의 — `core/candidate/operators.py`

예선은 **4개만.**

| Operator | 대응 규칙 | 대상 | 위험도 |
|---|---|---|---|
| `ADD_ARGUMENT_EXAMPLE` | R-02 | tool schema 설명 | low |
| `ADD_SCHEMA_VALIDATOR` | R-02 | 코드 검증 단계 | low |
| `CONDITIONAL_VERIFIER` | O-01 | verifier 설정 | medium |
| `REDUCE_MAX_RETRY` / `STOP_ON_REPEAT` | E-01, O-02 | retry 설정 | medium |

### P6-2. 규칙 → Operator 매핑

- [ ] 매핑 테이블을 코드 상수로 작성
- [ ] 매핑에 없는 operator는 LLM이 제안해도 **폐기**
- [ ] 모든 후보에 `addresses`(해결 대상 Finding) + `risk` 필수
- [ ] `status`는 항상 `PROPOSED`로 시작
- [ ] 최대 3개까지만 출력

### P6-3. 안전 하드 차단 ★

- [ ] SQL Guard · 스키마 검증 · 금지 명령 차단은 **REMOVE 후보 생성 자체를 차단**
- [ ] 차단 리스트를 코드 상수로 관리 (LLM 판단에 맡기지 않음)
- [ ] 테스트: 안전 컴포넌트 제거 후보가 절대 안 나오는지 검증

### ✅ P6 완료 게이트

- [ ] `scenario_a` → ADD_ARGUMENT_EXAMPLE + ADD_SCHEMA_VALIDATOR
- [ ] `scenario_b` → CONDITIONAL_VERIFIER
- [ ] `scenario_c` → REDUCE_MAX_RETRY
- [ ] 안전 컴포넌트 제거 후보 0건
- [ ] 후보마다 근거 Finding과 예상 효과가 붙는다

---

# P7 — 재검증 게이트

**날짜** 8/26(수) ~ 8/27(목) · 1.5일
**목표** 후보 적용 전후를 비교해 PASS/HOLD 판정이 나온다.
**선행 조건** P6

### P7-1. 재검증 경로 — `core/validation/gate.py`

```text
V0 vs V1  →  Finding + Candidate
                  │  (후보 적용해 V2 실행)
                  ▼
V0 vs V2  →  동일 파이프라인  →  PASS / HOLD / BLOCK / INCONCLUSIVE
```

- [ ] `--revalidate` 옵션으로 V2 번들을 받는 입력 경로 추가
- [ ] 동일 suite · 동일 testcase 검증 (다르면 거부)
- [ ] V2 Mock 픽스처 3종 추가 생성 (PASS / HOLD / BLOCK 각 케이스)

### P7-2. 판정 로직 — 코드만 판단

| 제약 | 조건 | 위반 시 |
|---|---|---|
| 안전 | safety_violation == 0 | **BLOCK (최우선)** |
| 품질 | 성공률이 V0 대비 하락 없음 | HOLD |
| 효율 | token · latency · retry 중 최소 1개 개선 | HOLD |
| 표본 | trial ≥ 2, 영향 케이스 ≥ 2 | INCONCLUSIVE |

- [ ] 판정은 코드가 내리고, LLM은 결과를 설명만 한다
- [ ] 보고서 5번 섹션에 각 후보의 재검증 상태 표시

### ✅ P7 완료 게이트

- [ ] 후보 적용 Mock(V2)을 넣으면 PASS가 나온다
- [ ] 품질이 떨어진 Mock → HOLD
- [ ] 안전 위반 Mock → BLOCK
- [ ] **예선 Must + Should를 Mock 기준으로 전부 완성** ← 1차 종료선

---

# P8 — Timely AI Skill 어댑터

**날짜** 8/27(목) ~ 8/28(금) · 1.5일
**목표** 플랫폼에서 실제로 1건이 end-to-end로 돈다.
**선행 조건** P7 + 플랫폼 제약 확인 결과

> P1 기간(8/17까지) 내가 직접 확인한 Timely AI 제약에 따라 구현이 갈린다.

### P8-1. 확인 결과별 분기

| 확인 결과 | 구현 |
|---|---|
| 외부 API 호출 **가능** | Skill → 백엔드 호출 → 보고서 반환 |
| 외부 API 호출 **불가** | **Level 0 확정** — 사용자가 JSON 텍스트를 붙여넣는 단일 Skill |
| 입력 길이 제한 있음 | 요약 번들 포맷 별도 정의 (trace 제외 + 집계값 사전 계산) |
| 파일 업로드 불가 | 텍스트 붙여넣기 UX로 안내 문구 설계 |

### P8-2. 어댑터 구현 — `apps/mabc_skill/`

- [ ] 입력 어댑터: 붙여넣은 텍스트 → `AuditBundle` 파싱
- [ ] 파싱 실패 시 이해 가능한 오류 안내
- [ ] 출력 어댑터: Markdown을 플랫폼 표시 형식에 맞게 조정
- [ ] 요약 번들 포맷 정의 (입력이 길 경우 대비)
- [ ] Skill 설명문 · 사용법 · 입력 예시 작성

### ✅ P8 완료 게이트

- [ ] Timely AI에서 실제로 1건 실행 → 보고서 출력
- [ ] 잘못된 입력에 오류 메시지가 나온다
- [ ] 길이 제한 안에서 20 케이스 번들이 들어간다

---

# P9 — 실데이터 통합

**날짜** 8/28(금) ~ 8/29(토) · 2일
**목표** Mock을 실제 Testbed 실행 기록으로 갈아끼운다.
**선행 조건** P8 + **팀원 산출물** (외부 의존이 있는 유일한 Phase)

### P9-1. 내가 받아야 할 것 (요청 행동)

| 받을 것 | 없으면 내가 하는 조치 |
|---|---|
| 20개 TestCase의 V0/V1 실행 결과 (trial 2회) | Mock 유지, 데모를 Mock으로 확정 |
| trace (iteration 포함) | O-01/O-02 규칙 `SKIPPED` 처리 |
| TestCase difficulty 필드 | R-05 규칙 `SKIPPED` 처리 |

> **8/26까지 실데이터가 안 오면** 팀에 즉시 통보하고 Mock 데모로 확정한다. 기다리지 않는다.

### P9-2. 통합 작업

- [ ] 실제 JSON을 로더에 통과시켜 스키마 불일치 목록 작성
- [ ] 누락 필드 → 규칙별 `SKIPPED`가 정상 동작하는지 확인
- [ ] 20 케이스 전체 실행, 처리 시간 측정
- [ ] **오탐 재점검** — 정상 변경 데이터에서 "이상 없음"이 나오는지
- [ ] 데모 3종을 실데이터로 재현
- [ ] 필드 추가 요청은 **8/28까지만** (이후는 포기하고 SKIPPED로 간다)

### ✅ P9 완료 게이트

- [ ] 실제 Testbed 데이터로 보고서가 나온다
- [ ] 데모 3종이 실데이터에서 재현된다
- [ ] 정상 변경 데이터에서 오탐 0건

---

# P10 — Freeze · 제출

**날짜** 8/30(일) ~ 8/31(월) · 2일
**목표** 네트워크가 죽어도 3분 데모가 돌아간다.
**선행 조건** P9

> **이 시점에 새 기능을 추가하지 않는다.** 버그 수정과 포장만.

### P10-1. Fallback Replay 패키지

- [ ] 데모 3종의 입력 JSON + 생성된 보고서를 저장
- [ ] `auditor replay --case a` 로 즉시 재생 (API 호출 없음)
- [ ] 화면 녹화 백업

### P10-2. 제출 자료

- [ ] Skill 소개 문장 (사용자 문제 → 해결 → 결과)
- [ ] 사용 방법 + 입력 예시
- [ ] 결과 예시 (보고서 1장)
- [ ] **한계 명시** — TestCase 20개, 합성 데이터, 일반화 주장 안 함
- [ ] 3분 발표 스크립트

### P10-3. 최종 점검

- [ ] 예선 Must 체크리스트 전항목 확인
- [ ] `.env` 등 비밀정보 커밋 여부 확인
- [ ] `Auditor` → `main` PR 머지
- [ ] 태그 `mabc-prelim` 부착

### ✅ P10 완료 게이트

- [ ] 인터넷 없이 3분 데모 재생 성공
- [ ] 제출 완료

---

# P11 — 결선 확장

**날짜** 9/9(수) ~ 9/18(금) · 최종발표 9/19(토)
**목표** 점검 Skill → 사용 가능한 서비스 MVP
**선행 조건** 예선 통과

우선순위 순. 아래로 갈수록 여유 있으면 하는 것.

| 순위 | 항목 |
|---|---|
| 1 | **자동 Runner** — TestCase → V0/V1 자동 실행 → 번들 자동 생성 |
| 2 | **Agent Version 저장소** — 버전 등록·이력 관리 |
| 3 | **Dashboard** (Streamlit) — 등록/실행/요약/TraceDiff/추천/재검증 6화면 |
| 4 | **Trace Diff 시각화** — 최초 갈라진 지점을 그래프로 |
| 5 | 후보 자동 적용 (config 수준만) |
| 6 | Operator 확장 4개 → 6~8개 |
| 7 | 보고서 PDF/Markdown 내보내기 |

> 결선에서도 원칙은 같다. **Runner가 실패해도 저장된 번들로 보고서가 나와야 한다.**

---

# 부록 A. Phase × 브랜치

| Phase | 작업 브랜치 | main 머지 시점 |
|---|---|---|
| P0 | `main` 직접 (스캐폴드 최초 1회) | 즉시 |
| P1-1 스키마 | `contract/schema-v1` | **즉시** (팀 전체가 봐야 함) |
| P1 나머지 | `Auditor` | P1 종료 시 |
| P2~P4 | `Auditor` | P4 종료 시 (숫자 보고서 완성) |
| P5~P7 | `Auditor` | P7 종료 시 (Must+Should 완성) |
| P8 | `Auditor` | P8 종료 시 |
| P9~P10 | `Auditor` → `main` | P10에서 태그 `mabc-prelim` |
| P11 | `Auditor` | 결선 종료 시 태그 `mabc-final` |

**동기화 규칙**

```bash
# 격일로 실행
git checkout Auditor && git merge main

# 스키마 변경 시
git checkout -b contract/schema-vN main
# ... 수정 ...
# PR → main 머지 → 팀에 즉시 공지
```

---

# 부록 B. 팀 커뮤니케이션 일정 (내가 하는 행동)

```text
P0 ─ P1 ─ P2 ─ P3 ─ P4 ─ P5 ─ P6 ─ P7 ─ P8 ────── P9 ─ P10
     │                                              │
     │  ← 여기까지 전부 Mock으로 진행 (외부 의존 0) →  │
     └─ 8/17 CONTRACT.md 배포 ─────────────────────┘
                                                    ▲
                                       팀원 실행 기록이 필요한 유일한 지점
```

| 날짜 | 내가 보내는 것 |
|---|---|
| 8/15 | 리포 주소 + 브랜치 규칙 + 디렉터리 소유권 공지 |
| 8/17 | CONTRACT.md 배포 + Enum 확정 통보 ("이의는 8/19까지") |
| 8/22 | 중간 확인 — 필드가 실제로 기록되는지 샘플 1건 요청 |
| 8/26 | 실데이터 마감 통보 (이후는 Mock 데모 확정) |
| 8/28 | 필드 추가 요청 마감 |

---

# 부록 C. 하루 단위 요약

| 날짜 | Phase | 그날 끝내야 하는 것 |
|---|---|---|
| 8/15 토 | **P0** + P1-1 | **Git 구성 완료** + 스키마 초안 |
| 8/16 일 | P1-1,2 | 스키마 확정 + 픽스처 3종 |
| 8/17 월 | P1-3,4 | **CONTRACT.md 배포 · 계약 동결** ★ |
| 8/18 화 | P2-1,2 | 로더 + 집계 |
| 8/19 수 | P2-3 | Diff + flip 행렬 |
| 8/20 목 | P2-4 / P3-1 | 골든 테스트 + 규칙 인터페이스 |
| 8/21 금 | P3-2 | 규칙 1~4번 |
| 8/22 토 | P3-2,3 / P4-1 | 규칙 5~6번 + 오탐 장치 |
| 8/23 일 | P4-2,3 | **LLM 없는 보고서 완성** ★ |
| 8/24 월 | P5-1,2 | Solar 클라이언트 + 호출 2개 |
| 8/25 화 | P5-3 / P6-1 | 숫자 방어 + operator 정의 |
| 8/26 수 | P6-2,3 / P7-1 | 후보 생성 + 재검증 경로 |
| 8/27 목 | P7-2 / P8-1 | **Must+Should 완성** ★ + Skill 분기 결정 |
| 8/28 금 | P8-2 | 플랫폼 end-to-end |
| 8/29 토 | P9 | 실데이터 통합 + 오탐 재점검 |
| 8/30 일 | P10-1,2 | Replay + 제출 자료 |
| 8/31 월 | P10-3 | **제출** |

---

# 부록 D. 위험 신호와 대응

| 신호 | 언제 | 대응 |
|---|---|---|
| 스키마 합의가 안 됨 | 8/17 | 내가 정한 안으로 확정 통보, 이의는 8/19까지만 |
| P3에서 규칙 6개를 못 채움 | 8/22 | 데모 3종 커버 규칙(1~6번)만 남기고 나머지 삭제 |
| LLM 출력이 불안정 | 8/25 | `--no-llm`을 기본값으로 전환, LLM은 부가 기능으로 강등 |
| 플랫폼 제약이 심각 | 8/27 | Level 0 + 요약 번들 포맷으로 축소 |
| 실데이터가 안 옴 | 8/26 | Mock 데모 확정, 발표에서 "합성 데이터" 명시 |
| 일정이 2일 이상 밀림 | 언제든 | P6·P7을 Should로 강등하고 P4까지를 제출본으로 |

> **최후 방어선: P4까지만 끝나도 예선 Must의 절반은 제출 가능하다.**
> 순서를 이렇게 잡은 이유가 이것이다.

---

*작성 2026-08-15 · Agent Upgrade Auditor (소현) · MABC 2026*
