# CONTRACT.md — Agent Upgrade Auditor 입출력 계약 (schema v1)

> **전원 필독.** 여기 적힌 필드가 실행 기록에 안 남으면, 그 필드를 쓰는 규칙만 조용히
> `SKIPPED` 처리되고 Auditor 자체는 계속 동작합니다. 필드가 있고 없고가
> 예선 데모 3종(A/B/C) 중 무엇이 나오는지를 그대로 결정합니다.

| 항목 | 내용 |
|---|---|
| 스키마 버전 | v1 |
| 배포일 | 2026-08-16 |
| 담당 | 소현 |
| 정의 위치 | `core/schemas/` (Pydantic) — 이 문서는 그걸 사람이 읽는 형태로 옮긴 것 |
| 이의 제기 기한 | 8/19까지 (그 뒤엔 확정값으로 진행) |

---

## 0. 한 장 요약

```text
[팀원 영역]                                [내 영역]
Testbed V0 실행 ──┐
                  ├──> AuditBundle (JSON) ──> Agent Upgrade Auditor ──> UpgradeReport (JSON)
Testbed V1 실행 ──┘
```

- Auditor는 **Agent를 실행하지 않는다.** 여러분이 만든 실행 기록(JSON)만 읽는다.
- 입력은 `AuditBundle` 하나, 출력은 `UpgradeReport` 하나. 둘 다 `core/schemas/`에 Pydantic으로 고정돼 있다.
- **필수 필드가 없으면 그 필드가 필요한 규칙만 `SKIPPED`.** 안 남겨도 전체가 죽지는 않지만,
  그만큼 보고서에서 못 보는 게 생긴다.

---

## 1. `TrialResult` — 실행 1회의 기록 (가장 중요)

`AuditBundle.trials`는 `TrialResult` 배열이다. **testcase 1개 × trial 1회 × 버전(V0/V1) 1개 = 1건.**

### 1.1 필수 — 없으면 Auditor가 그 케이스를 아예 못 씀

| 필드 | 타입 | 없으면 못 하는 것 |
|---|---|---|
| `testcase_id` | str | **페어링 자체 불가** — V0/V1을 매칭 못 함 |
| `agent_label` | str (`baseline.label` 또는 `candidate.label`과 일치, 보통 `"V0"`/`"V1"`) | **비교 자체 불가** |
| `trial` | int (1~3) | 반복 안정성 확인 |
| `task_success` | bool | Regression(R-01) 탐지 |
| `policy_correct` | bool | 정책 오류 구분(R-03) |
| `tool_error_count` | int | 시나리오 A |
| `retry_count` | int | 시나리오 C (E-01) |
| `total_tokens` | int | 효율 비교 (E-02) |
| `latency_ms` | int | 효율 비교 (E-03) |
| `safety_violation` | bool | 안전 게이트 (S-01) — **가장 중요, 절대 빠뜨리지 말 것** |
| `stop_reason` | enum (§4) | 실패 유형 분류 (R-04) |

### 1.2 권장 — 있으면 진단 품질이 크게 올라감

| 필드 | 타입 | 활성화되는 기능 |
|---|---|---|
| `error_type` | str \| null | Regression 그룹핑, O-02 회복률 계산 |
| `tool_schema_valid` | bool \| null | 시나리오 A 정밀도 (R-02) |
| `llm_call_count` | int \| null | 시나리오 B 절감 추정 (O-01) |
| `scaffold_config` | object \| null | Opportunity 탐지. 예: `{"planner": false, "repair": 2, "verifier": 1}` |
| `difficulty` | str \| null | 난이도별 회귀 탐지 (R-05). `data/test_cases.json`의 `difficulty`를 그대로 실어주면 됨 |

> **`difficulty`는 원래 기획서 표에는 없었지만 P1에서 TrialResult에 편입했다.**
> R-05가 난이도별 성공률을 보려면 결국 testcase당 난이도를 어디선가 받아야 하는데,
> 별도 TestCase 카탈로그 스키마를 새로 만들기보다 이미 있는 testcase_id 옆에 얹는 쪽이 더 단순하다.

---

## 2. `TraceStep` — 선택. Trace Diff / O-01 / O-02 전용

`AuditBundle.traces`는 통째로 없어도 된다 (`null`). 있으면 Trace Diff 섹션과 O-01·O-02 규칙이 켜진다.

| 필드 | 타입 | 비고 |
|---|---|---|
| `testcase_id` | str | 페어링 키 |
| `agent_label` | str | 페어링 키 |
| `run_id` | str \| null | 같은 testcase·trial의 실행 1회 식별 |
| `trial` | int \| null | 어느 `TrialResult`에 속하는지 (1~3) |
| `step_index` | int | 같은 run 안에서의 순서 |
| `node_role` | enum (§4) | **고정 목록만 사용** — 양쪽 버전이 같은 이름을 써야 정렬됨 |
| `type` | `llm_call` \| `tool_call` \| `code` | |
| `outcome` | `ok` \| `fail` \| `skip` | |
| `tool_name` | str \| null | |
| `arguments_valid` | bool \| null | 시나리오 A |
| `error_type` | str \| null | O-02 회복률 계산에 씀 |
| `iteration` | int \| null | retry 회차 |
| `input_tokens` / `output_tokens` / `latency_ms` | int \| null | |

**`node_role` 고정 목록** (양쪽 버전이 같은 이름을 써야 Trace Diff가 정렬됨):

```text
CLASSIFY · PLAN · RETRIEVE_SCHEMA · GENERATE_QUERY · VALIDATE_QUERY
EXECUTE_TOOL · REPAIR_QUERY · CHECK_EVIDENCE · SELECT_POLICY
DECIDE · VERIFY_REASONING · GENERATE_RESPONSE
```

---

## 3. `AuditBundle` — 최상위 입력 구조

```text
AuditBundle
├─ bundle_id          str
├─ created_at         datetime
├─ suite               { suite_id, testcase_ids[], dataset_version }
├─ baseline            AgentVersion  (label="V0")
├─ candidate           AgentVersion  (label="V1")
├─ change_note         str | null
├─ trials[]            TrialResult   (1개 이상 필수)
└─ traces[]            TraceStep | null
```

`AgentVersion` 필드: `label · agent_id · version · model_id · prompt_version · tool_schema_version · workflow_version · retry_policy · verifier_policy · commit`

---

## 4. Enum 확정값

```text
StopReason:  OK / SQL_FAILURE / MAX_RETRY / MAX_REFLECTION /
             INSUFFICIENT_EVIDENCE / TOOL_SCHEMA_ERROR / TIMEOUT / PROVIDER_ERROR

NodeRole:    CLASSIFY / PLAN / RETRIEVE_SCHEMA / GENERATE_QUERY / VALIDATE_QUERY /
             EXECUTE_TOOL / REPAIR_QUERY / CHECK_EVIDENCE / SELECT_POLICY /
             DECIDE / VERIFY_REASONING / GENERATE_RESPONSE

FindingType: REGRESSION / IMPROVEMENT / EFFICIENCY_WARNING /
             OPTIMIZATION_OPPORTUNITY / SAFETY_ALERT / INCONCLUSIVE

Severity:    P0 / P1 / P2

Verdict:          PASS / HOLD / BLOCK                (UpgradeReport.verdict)
RevalidationStatus: PASS / HOLD / BLOCK / INCONCLUSIVE  (Candidate 재검증 결과, P7)
RiskLevel:        low / medium / high
CandidateStatus:  PROPOSED / APPLIED / REJECTED
```

`Verdict`에는 `INCONCLUSIVE`가 없다 — 그건 개별 재검증(`RevalidationResult.status`)에서만 쓰는 값이다.

---

## 5. 샘플 JSON (복붙 가능한 최소 형태)

```json
{
  "bundle_id": "audit_20260818_001",
  "created_at": "2026-08-18T10:00:00+09:00",
  "suite": {
    "suite_id": "refund_suite_v1",
    "testcase_ids": ["refund_001", "refund_002"],
    "dataset_version": "ds_v1"
  },
  "baseline": {
    "label": "V0", "agent_id": "policy_agent", "version": "v0", "model_id": "MODEL_A",
    "prompt_version": "p1", "tool_schema_version": "t1", "workflow_version": "w1",
    "retry_policy": "max_retry=2", "verifier_policy": "reflection=1", "commit": "abc1234"
  },
  "candidate": {
    "label": "V1", "agent_id": "policy_agent", "version": "v1", "model_id": "MODEL_B",
    "prompt_version": "p2", "tool_schema_version": "t1", "workflow_version": "w1",
    "retry_policy": "max_retry=5", "verifier_policy": "reflection=1", "commit": "def5678"
  },
  "change_note": "모델 교체 + tool 설명 문장 수정",
  "trials": [
    {
      "testcase_id": "refund_001", "agent_label": "V0", "trial": 1,
      "task_success": true, "policy_correct": true, "tool_error_count": 0,
      "retry_count": 0, "total_tokens": 2401, "latency_ms": 3400,
      "safety_violation": false, "stop_reason": "OK",
      "tool_schema_valid": true, "difficulty": "Medium"
    },
    {
      "testcase_id": "refund_001", "agent_label": "V1", "trial": 1,
      "task_success": false, "policy_correct": true, "tool_error_count": 1,
      "retry_count": 2, "total_tokens": 2906, "latency_ms": 4900,
      "safety_violation": false, "stop_reason": "TOOL_SCHEMA_ERROR",
      "tool_schema_valid": false, "error_type": "TOOL_ARG_SCHEMA_MISMATCH", "difficulty": "Medium"
    }
  ],
  "traces": null
}
```

더 큰 실제 예시는 `fixtures/bundles/scenario_a.json`을 참고하세요 (20 testcase × trial 2회 규모).

---

## 6. 계약 위반 처리 — 조용히 넘어가지 않는다

| 상황 | 처리 |
|---|---|
| V0에만 있고 V1에 없는 testcase (또는 반대) | `UNPAIRED` 목록에 넣고 비교에서 제외 + 보고서 최상단에 명시 |
| 필수 필드 누락 | 그 필드가 필요한 규칙만 `SKIPPED(reason)`, 나머지는 정상 진행 |
| `traces` 없음 | Trace Diff 섹션을 `NOT_AVAILABLE`로 표기 (에러 아님), O-01/O-02는 `SKIPPED` |
| trial 반복 횟수가 V0/V1 다름 | 경고 표시 후 평균 기준으로 비교 |
| trial 수 < 2 | 영향받는 모든 Finding에 `low_confidence` 플래그 |

이 표의 실제 동작은 `core/schemas/loader.py`(P2)가 구현합니다 — `fixtures/bundles/scenario_broken.json`이
이 표를 검증하는 테스트 픽스처입니다 (일부러 페어링 실패 1건 + 필수 필드 누락 1건을 심어 둠).

---

## 7. 변경 규칙

- 이 파일과 `core/schemas/`는 소현이 소유합니다. 직접 고치지 마세요.
- 필드 추가/변경이 필요하면 이슈로 남기거나 요청하세요.
- 실제 변경은 `contract/*` 브랜치로 **`main`에 바로 머지**되고, 머지 즉시 팀에 공지합니다.
- 이의 제기 기한: **8/19까지.** 그 이후는 위 확정값 기준으로 P2~P8이 진행됩니다.
