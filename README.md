# Agent Migration

MABC 2026 출품 프로젝트.
Agent를 수정·업그레이드했을 때 **무엇이 망가졌고 무엇을 줄일 수 있는지** 점검해 주는 도구와,
그 도구를 검증하기 위한 시험용 Agent를 함께 만든다.

| Agent | 역할 | 위치 |
|---|---|---|
| **Agent Upgrade Auditor** | 변경 전후 Agent를 비교·진단·추천·재검증 (대회 제출물) | `core/` `apps/` `fixtures/` |
| **Order & Refund Policy Agent** | 주문·환불 질의를 DB와 정책으로 처리 (Auditor 검증용) | `agents/` `data/` `policies/` |

---

## 시작하기 — 자기 줄만 보면 됩니다 ^^

| 담당 | 내 폴더 | 만들 브랜치 이름 | 첫 산출물 |
|---|---|---|---|
| **준원** | `agents/policy_agent/nodes/` | `feat/core-graph` | state.py, graph.py |
| **채린** | `agents/policy_agent/scaffolds/` | `feat/repair-loop` | sql_repair.py, reasoning_verifier.py |
| **우혁** | `data/` · `policies/` | `feat/dataset` | shop.db, test_cases.json, policy_oracle.py |
| **소현** | `core/` `apps/` `fixtures/` `docs/` | `Auditor` | schemas, CONTRACT.md |

### 준원 · 채린 · 우혁

```bash
git clone <리포주소> && cd agent-migration
uv sync --extra testbed --extra dev

git checkout tester && git pull
git checkout -b feat/core-graph        # 자기 브랜치 이름으로

cd agents/policy_agent/nodes           # 자기 폴더로
cat README.md                          # 여기에 할 일이 적혀 있습니다
```

### 소현

```bash
git checkout Auditor && uv sync --extra auditor --extra dev
```

> **폴더마다 README.md가 있습니다.** 자기 폴더에 들어가서 그것부터 읽으세요.
> 무엇을 만들지, 어떤 형식으로 출력해야 하는지가 거기 적혀 있습니다.

---

## 공동 규칙 3개

**① 내 폴더만 고칩니다.**
남의 폴더가 필요하면 직접 고치지 말고 담당자에게 요청하세요.
같이 고치면 머지할 때마다 서로 코드가 사라집니다.

**② `core/schemas/`는 이소현 불러서 요청하시길...**
여기는 네 명이 전부 쓰는 공용 공간. 누가 바꾸면 나머지 세 명 코드가 동시에 깨집니다이..
필드 추가가 필요하면 이슈로 남기거나 말하셔라.

**③ 격일로 main을 받아옵니다.**

```bash
git checkout tester && git merge main     # 또는 Auditor
```

2주 넘게 안 섞으면 마지막 주에 힘드니까 ㅇㅇ. 근데 이건 조금 기간 두고 해도 괜찮긴 함

---

## 브랜치

```text
main                    항상 동작하는 상태 유지 · 직접 push 금지 (PR 필수)
 ├─ contract/*          공용 스키마 변경 전용 → main으로 즉시 머지
 ├─ tester              Testbed 통합
 │   ├─ feat/core-graph      준원
 │   ├─ feat/repair-loop     채린
 │   └─ feat/dataset         우혁
 └─ Auditor             소현
```

- feature 브랜치는 `tester`에서 분기하고 `tester`로 되돌립니다
- PR에는 **정상 사례 1개 + 실패 사례 1개**를 함께 올립니다

---

## 환경

```bash
# uv 설치 (최초 1회)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 의존성
uv sync --extra testbed --extra dev     # 준원·채린·우혁
uv sync --extra auditor --extra dev     # 소현

# API 키
cp .env.example .env                    # 값을 채워 넣으세요. .env는 절대 커밋 금지
```

Python 3.11 기준입니다.

---

## 폴더 구조

<details>
<summary>펼쳐 보기</summary>

```text
agent-migration/
├─ pyproject.toml            공유 · 의존성은 extras로 분리
├─ .env.example              키 이름만 (값 없이)
├─ README.md                 이 파일
│
├─ core/                     ── 소현 (Auditor 엔진)
│  ├─ schemas/               ★ 공용 계약 — 전원이 소비, 소현이 소유
│  ├─ diff/                  집계 · 버전 비교
│  ├─ detector/              규칙 기반 이상 탐지
│  ├─ report/                보고서 렌더러
│  ├─ diagnosis/             LLM 진단
│  ├─ candidate/             수정 후보 생성
│  └─ validation/            재검증 게이트
│
├─ apps/
│  ├─ cli.py                 소현
│  ├─ mabc_skill/            소현 · Timely AI 어댑터
│  └─ dashboard/             결선 이후
│
├─ fixtures/                 소현 · Mock 실행기록 생성기
│
├─ agents/policy_agent/      ── Testbed
│  ├─ nodes/                 준원 · Core 질의 처리 경로
│  └─ scaffolds/             채린 · Repair Loop, Verifier
│
├─ data/                     우혁 · shop.db, test_cases.json
├─ policies/                 우혁 · 정책 문서, policy_oracle.py
│
├─ tests/
│  ├─ auditor/               소현
│  └─ testbed/               준원 · 채린 · 우혁
│
├─ docs/CONTRACT.md          ★ 실행기록 필수 필드 명세 — 전원 필독
└─ reports/                  생성물 (git 추적 안 함)
```

</details>

---

## 문서

| 문서 | 위치 | 대상 |
|---|---|---|
| **CONTRACT.md** | `docs/` (main) | **전원 필독** — 실행 기록에 남겨야 할 필드 |
| 폴더별 README | 각 폴더 | 담당자 |
| Auditor 개발 기획서 | `Auditor` 브랜치 `docs/` | 소현 |

---

## 용어

| 용어 | 뜻 |
|---|---|
| Core | Scaffold를 다 꺼도 업무가 끝까지 돌아가는 최소 구성 |
| Scaffold | 모델을 보완하는 보조 구조 (Planner, Repair, Verifier) |
| Trace | Agent가 거쳐간 단계별 기록 |
| Regression | 되던 게 안 되게 된 것 |
| Finding | Auditor가 찾아낸 문제 1건 |
