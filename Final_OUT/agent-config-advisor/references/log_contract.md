# 대상 에이전트 로그 형태

이 문서는 **진단 대상 에이전트가 남기는 실행 로그**를 설명한다.
대상 에이전트는 이 진단 스킬의 존재를 모른다. 자기 운영을 위해 로그를 남길 뿐이다.
그 로그를 읽어 진단 지표로 옮기는 것은 **이 스킬의 책임**이다.

---

## 1. 입력 파일 구조

```json
{
  "runs": [
    { "label": "PROD", "manifest": { ... }, "trials": [ ... ] }
  ]
}
```

`runs`는 **1개**다. 하나의 에이전트를 여러 테스트케이스로 여러 번 돌린 기록이다.
두 개 이상이 오면 첫 번째만 진단하고 나머지는 무시한다고 알린다.

---

## 2. `trials[]` — 실행 1회의 로그

각 항목은 **테스트케이스 1개 × 반복 1회**의 기록이고 키가 5개다.

| 키 | 무엇 | 이 스킬이 |
|---|---|---|
| `trial_result` | 에이전트가 관측한 값 | **읽는다** |
| `traces` | 단계별 기록 | **읽는다 — 구조 진단의 핵심** |
| `provider_calls` | 모델 호출별 토큰·지연·모델명 | **읽는다 — 비용 진단의 핵심** |
| `runtime_metrics` | 실행 환경 지표 | 무시 |
| `agent_output` | 에이전트의 업무 결과물 | **내용을 읽지 마라. 해시만 낸다** (§5) |

### 2.1 `trial_result`

| 필드 | 뜻 |
|---|---|
| `testcase_id` | 반복을 묶는 키 |
| `trial` | 몇 번째 반복인지 (보통 1~3) |
| `task_success` | 업무를 끝냈는가 (bool) |
| `policy_correct` | 판정이 맞았는가 (bool) — **이미 채점된 값이다. 다시 따지지 마라** |
| `tool_error_count` · `retry_count` | 도구 실패·재시도 횟수 (int) |
| `total_tokens` · `latency_ms` | 비용 (int) |
| `safety_violation` | 안전 규칙 위반 (bool) |
| `stop_reason` | 종료 사유 (아래 8종) |
| `error_type` | 오류 분류 (없을 수 있음) |
| `llm_call_count` | 모델 호출 횟수 (없을 수 있음) |
| `difficulty` | 케이스 난이도 (없을 수 있음) |

```
OK · SQL_FAILURE · MAX_RETRY · MAX_REFLECTION
INSUFFICIENT_EVIDENCE · TOOL_SCHEMA_ERROR · TIMEOUT · PROVIDER_ERROR
```

### 2.2 `traces[]` — 단계별 기록

| 필드 | 뜻 |
|---|---|
| `node_role` | 어느 단계인가 (아래 12종) |
| `type` | `llm_call` / `tool_call` / `code` |
| `outcome` | `ok` / `fail` / `skip` |
| `iteration` | 재시도 회차 |
| `input_tokens` · `output_tokens` · `latency_ms` | 그 단계의 비용 |

```
CLASSIFY · PLAN · RETRIEVE_SCHEMA · GENERATE_QUERY · VALIDATE_QUERY
EXECUTE_TOOL · REPAIR_QUERY · CHECK_EVIDENCE · SELECT_POLICY
DECIDE · VERIFY_REASONING · GENERATE_RESPONSE
```

**`node_role`이 이 스킬의 진단 단위다.** 어느 단계가 비싼지, 어느 단계가
일을 안 하는지를 이 값으로 묶는다.

### 2.3 `provider_calls[]`

```json
{ "node_role": "DECIDE", "provider": "gemini", "model_id": "gemini-3.6-flash",
  "finish_reason": "stop", "latency_ms": 4200,
  "usage": { "input_tokens": 3100, "output_tokens": 240 } }
```

**어느 단계가 어떤 모델을 쓰고 얼마를 썼는지**가 여기 있다.
**`local-deterministic`은 `provider` 필드에 들어간다. `model_id`가 아니다.**
위 예에서 `GENERATE_QUERY`의 `provider`는 `local-deterministic`이고
`model_id`는 `sql-plan-v1`이다.

`provider == "local-deterministic"` 인 단계는 이미 코드로 처리되는 단계다 —
최적화 대상이 아니라 **모범 사례**다. 토큰도 0으로 측정된다.

---

## 3. `manifest` — 에이전트의 현재 구성

| 경로 | 무엇 |
|---|---|
| `run_metadata.provider` · `run_metadata.model` | 주 모델 |
| `run_metadata.agent_version.*` | 프롬프트·툴 스키마·워크플로 버전 |
| `agents.<키>.scaffold_config` | **보조 구조 설정** — `repair_enabled` `max_retries` `verifier_enabled` `max_reflections` |
| `agents.<label>.core_config` | 단계 상한 등 |
| `run_metadata.runtime.provider_parameters` | temperature, timeout 등 |

> **주의:** `manifest.agents`의 키는 `runs[].label`과 **다를 수 있다.**
> 로그를 묶는 과정에서 이름표가 새로 붙기 때문이다.
> `runs[].label`로 찾지 말고 **`manifest.agents`의 키를 그대로 읽어라.**
> 항목이 하나뿐이면 그것을 쓰면 된다.

`scaffold_config`가 **"무엇이 켜져 있는가"**이고, 로그가 **"그게 실제로 값을 했는가"**다.
둘을 대조하는 것이 이 스킬의 핵심이다.

---

## 4. 무결성 검사 — 로그를 그냥 믿지 않는다

| 검사 | 조건 | 어긋나면 |
|---|---|---|
| 토큰 합계 | `sum(provider_calls[].usage.*_tokens) == total_tokens` | **신뢰 불가 → 집계에서 제외** |
| 표본 | 같은 `testcase_id`의 반복이 몇 회인가 | 2회 미만이면 안정성 진단 불가 |

제외한 기록은 **몇 건을 왜 뺐는지 보고서에 적는다.** 조용히 버리지 마라.

### 호출 횟수 불일치는 제외 사유가 아니다

`len(provider_calls) < llm_call_count` 는 흔히 일어나고 **정상이다.**
**실패한 모델 호출은 응답이 없어서 `provider_calls`에 기록되지 않지만,
`llm_call_count`에는 시도로 세어지기 때문이다.**

```
llm_call_count = 2 · provider_calls = 1 · stop_reason = PROVIDER_ERROR
→ 두 번 부르려 했고 한 번은 응답을 못 받았다
```

이걸 신뢰 불가로 처리하면 **실패한 실행이 전부 버려진다.**
실패야말로 진단해야 할 대상인데 그것을 못 보게 된다.

대신 이렇게 다룬다.

- `failed_call_count = llm_call_count - len(provider_calls)` 로 계산한다
- 이 값이 0보다 크면 **"모델 호출 실패가 있었다"는 신호**로 쓴다 (D-03 근거)
- 기록 자체는 **집계에 그대로 포함한다**
- `len(provider_calls) > llm_call_count` 인 경우만 이상하다. 그때는 제외한다

---

## 5. `agent_output` — 내용은 읽지 않고 해시만 낸다

여기엔 에이전트가 내놓은 실제 업무 결과가 들어 있다(예: 환불 승인 여부와 근거).

**옳고 그름을 따지지 마라.** 그 채점은 이미 `policy_correct`에 들어와 있고,
정답을 아는 독립 평가자가 한 것이다. 내용을 해석하기 시작하면 이 스킬은
범용 진단 도구에서 특정 업무 전용 도구로 전락한다.

다만 **해시는 낸다.** 같은 입력에 대해 반복 실행했을 때 출력이 매번 같은지를
알아야 하기 때문이다. 해시 비교는 내용 해석이 아니다.

```
stability_hash = sha256(json.dumps(agent_output, sort_keys=True))
```

같은 `testcase_id`의 모든 반복에서 이 해시가 동일하면 **그 케이스는 결정론적**이다.
이것이 "저가 모델로 내려도 되는가"의 핵심 근거가 된다 (진단 규칙 D-05).
