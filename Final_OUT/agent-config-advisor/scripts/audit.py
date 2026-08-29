#!/usr/bin/env python3
"""
agent-config-advisor: 0~3단계 진단 스크립트.

입력: execution 로그 JSON 파일 경로
출력: 프로파일 표 + Finding 목록 (JSON) 을 stdout 으로 낸다.
       실패/경고는 stderr 로 낸다.

역할 분리:
  - 이 스크립트는 0~3단계(정규화, 무결성 검사, 프로파일, 진단, 판정)만 계산한다.
  - 4단계(제안)와 5단계(칭찬)는 호출하는 쪽이 이 출력 위에서 수행한다.
  - 숫자는 모두 코드가 계산한다. 눈대중 금지.
"""

import argparse
import hashlib
import io
import json
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

# 정정 ⑥ — Windows cp949 콘솔에서 UnicodeEncodeError로 죽지 않게 한다.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# 0. 목표 매핑
# ---------------------------------------------------------------------------

GOAL_MAP: Dict[str, str] = {
    "비용": "COST",
    "돈": "COST",
    "줄이고": "COST",
    "비용 줄이고": "COST",
    "비용절감": "COST",
    "품질": "QUALITY",
    "정확": "QUALITY",
    "안전": "QUALITY",
    "신뢰": "QUALITY",
    "틀리면": "QUALITY",
    "성능": "QUALITY",
    "우선": "QUALITY",
    "빠르": "LATENCY",
    "느려": "LATENCY",
    "대기": "LATENCY",
    "응답": "LATENCY",
    "시간": "LATENCY",
    "지연": "LATENCY",
    "균형": "BALANCED",
    "기본": "BALANCED",
}

# natural language 목표 해석. 못 정하면 None.
def interpret_goal(natural: str) -> Optional[str]:
    up = natural.strip().upper()
    # 이미 코드화된 목표면 그대로
    if up in ("COST", "QUALITY", "LATENCY", "BALANCED"):
        return up
    best: Optional[str] = None
    best_len = 0
    low = natural.strip().lower()
    for key, val in GOAL_MAP.items():
        klow = key.lower()
        # 구 절 포함
        if klow in low:
            if len(klow) > best_len:
                best = val
                best_len = len(klow)
    return best


# ---------------------------------------------------------------------------
# 모델 호출 여부 판정
# ---------------------------------------------------------------------------

# type=None 인 provider_call 처리:  log_contract 상 provider_calls 엔 node_role,type 없음.
# diagnosis_rules §3-5: type != "llm_call" 인 모든 단계는 비용 절감 대상 아님.
# provider_calls 엔 type 이 없으므로, traces 의 type 과 node_role 로 판단한다.
# 아래 helper: 이 provider_call 이 대응되는 traces 단계가 llm_call 인가?

def is_llm_call_stage(node_role: str, traces_by_role: Dict[str, Any]) -> bool:
    """
    provider_calls 의 node_role 이 llm_call 단계인지 판정.
    assessment_rules §3-5 에 따라 type != "llm_call" 은 제외.
    provider_calls 자체에 type 은 없으니, 같은 node_role 의 traces 를 본다.
    """
    t = traces_by_role.get(node_role)
    if t is None:
        # traces 에 없으면 모른다고 표시 — 여기서는 보수적으로 "알 수 없음"으로 본다.
        # 하지만 diagnosis_rules §3-5 는 type != llm_call 이면 제외.
        # type 정보가 없으면 판정이 보류되어야 하나,
        # provider_calls 가 있다는 것 자체가 '모델 호출이 있었다'는 뜻이므로,
        # 여기서는 'llm_call 로 간주하되 불확실성 표기' 정책을 취한다.
        return True
    return t.get("type", "") == "llm_call"


# ---------------------------------------------------------------------------
# 정규화 — log_contract 기반 읽기와 필드 부재 처리
# ---------------------------------------------------------------------------

def normalize_runs(data: dict) -> Tuple[dict, dict, list]:
    """
    log_contract §1, §2에 따라 로그를 읽는다.
    returns: (manifest, runs[0], skipped_reasons)
    runs 가 빈 경우, runs 가 2개 이상이면 알리고 첫 번째만 쓴다.
    """
    runs = data.get("runs", [])
    skipped: list = []

    if not runs:
        skipped.append("runs 가 비어 있음: 실행 기록이 아니라 소스/설정 파일일 가능성")
        return ({}, [], skipped)

    if len(runs) > 1:
        skipped.append(
            f"runs 가 {len(runs)}개 들어옴 — 첫 번째만 진단하고 나머지는 무시함"
        )

    run = runs[0]
    manifest = run.get("manifest") or {}
    trials = run.get("trials") or []
    label = run.get("label", "<no-label>")

    # trials 이 비어 있으면 전체를 빈 걸로 본다 — 뒤에서 걸리게 한다.
    if not trials:
        skipped.append(f"runs[0].label='{label}' trials 가 비어 있음: 실행 기록이 아님")

    return (manifest, trials, skipped)


def extract_trial_fields(trial: dict) -> dict:
    """
    log_contract §2 에 따라 trial_result 필드를 읽는다.
    없는 필드는 없는 대로 둔다 — DiagnosisRules 가 '없으면 보류' 처리한다.
    """
    tr = trial.get("trial_result") or {}
    out_keys = [
        "testcase_id",
        "trial",
        "task_success",
        "policy_correct",
        "tool_error_count",
        "retry_count",
        "total_tokens",
        "latency_ms",
        "safety_violation",
        "stop_reason",
        "error_type",
        "llm_call_count",
        "difficulty",
    ]
    return {k: tr.get(k) for k in out_keys}


# ---------------------------------------------------------------------------
# 0.5 무결성 검사
# ---------------------------------------------------------------------------

def integrity_check(trial: dict, provider_calls: list, total_tokens: Optional[int], llm_call_count: Optional[int]) -> Tuple[bool, str, int]:
    """
    log_contract §4.
    반환: (trustable: bool, reason: str, failed_call_count: int)

    정정 ① — 제외 사유는 토큰 합계 불일치 하나뿐이다.
    호출 횟수 불일치는 제외 사유가 아니다. 실패한 모델 호출은 응답이 없어서
    provider_calls 에 기록되지 않지만 llm_call_count 에는 시도로 세어지기 때문이다.
    이대로 버리면 실패한 실행이 전부 사라진다 — 실패야말로 진단 대상이다.
    len(provider_calls) > llm_call_count 인 경우만 이상하므로 그때만 제외한다.
    """
    reasons: list = []
    failed_call_count = 0

    if provider_calls:
        sum_in = sum((pc.get("usage") or {}).get("input_tokens", 0) or 0 for pc in provider_calls)
        sum_out = sum((pc.get("usage") or {}).get("output_tokens", 0) or 0 for pc in provider_calls)
        sum_total = sum_in + sum_out
        if total_tokens is not None and sum_total != total_tokens:
            reasons.append(
                f"토큰 합계 불일치: provider_calls 합={sum_total}, trial_result.total_tokens={total_tokens}"
            )

    if llm_call_count is not None:
        diff = llm_call_count - len(provider_calls)
        if diff > 0:
            # 응답을 못 받은 호출이 있었다. 정상이다. 제외하지 않고 D-03 근거로 쓴다.
            failed_call_count = diff
        elif diff < 0:
            reasons.append(
                f"호출 기록이 시도 횟수보다 많음: provider_calls 길이={len(provider_calls)}, "
                f"trial_result.llm_call_count={llm_call_count}"
            )

    if reasons:
        return (False, "; ".join(reasons), failed_call_count)
    return (True, "", failed_call_count)


# ---------------------------------------------------------------------------
# 1단계 · 프로파일 계산
# ---------------------------------------------------------------------------

def compute_profile(manifest: dict, trials: list, skip_reasons: list) -> dict:
    """
    diagnosis_rules §1.

    provider_calls → node_role 로 묶어:
      calls, tokens, latency_ms, token_share, latency_share, models
    traces → node_role 로 묶어:
      runs, intervention_rate (fail 비율)
    testcase 별 반복 안정성:
      같은 testcase_id 의 반복에서 task_success/policy_correct/stop_reason/retry_count/tool_schema_valid/
      agent_output 해시가 모두 같으면 결정론적.

    반환 dict:
      profile: { node_role: {calls, tokens, latency_ms, token_share, latency_share, models, type, outcome_summary} }
      traces_summary: { node_role: {runs, intervention_rate, fail_count, ok_count, skip_count} }
      stability: { testcase_id: {deterministic: bool, repeat_count, roles_same: dict} }
      overall: { total_tokens, total_calls, total_latency_ms, success_rate, policy_accuracy, retry_runs, retry_recovery_rate,
                 failure_reasons: {stop_reason: count}, stability_rate, testcase_count }
    skip_reasons: 무결성 검사 탈락 기록 제외 사유 리스트
    """
    # 그룹화
    provider_by_role: Dict[str, list] = defaultdict(list)
    traces_by_role: Dict[str, list] = defaultdict(list)

    testcase_trials: Dict[str, list] = defaultdict(list)

    total_tokens_all = 0
    total_latency_all = 0
    total_calls_all = 0
    success_count = 0
    policy_correct_count = 0
    retry_runs = 0
    retry_recovery_count = 0  # retry 후 성공으로 이어진 케이스(진짜 살린 건지 나중에 세는 방식)

    # 정정 ①·③ — 집계에 실제로 쓴 trial 수와, 응답을 못 받은 모델 호출 수
    used_trials = 0
    failed_call_total = 0
    failed_call_trials = 0

    failure_reasons: Dict[str, int] = defaultdict(int)

    testcase_outcomes: Dict[str, list] = defaultdict(list)  # testcase_id -> list of dict

    testcase_ids_seen = set()

    for trial in trials:
        pr = trial.get("provider_calls") or []
        traces = trial.get("traces") or []
        tr = extract_trial_fields(trial)
        testcase_id = tr.get("testcase_id")
        if testcase_id is None:
            continue

        # 무결성 검사
        tt = tr.get("total_tokens")
        lc = tr.get("llm_call_count")
        trustable, reason, failed_calls = integrity_check(trial, pr, tt, lc)
        if not trustable:
            skip_reasons.append(f"testcase_id={testcase_id}, trial={tr.get('trial')}: {reason}")
            continue

        used_trials += 1
        failed_call_total += failed_calls
        if failed_calls > 0:
            failed_call_trials += 1

        # 집계
        for pc in pr:
            role = pc.get("node_role") or "<no-role>"
            provider_by_role[role].append(pc)

        for t in traces:
            role = t.get("node_role") or "<no-role>"
            tcopied = dict(t)
            traces_by_role[role].append(tcopied)

        tc = tr.get("task_success")
        pc_flag = tr.get("policy_correct")
        if tc is True:
            success_count += 1
        if pc_flag is True:
            policy_correct_count += 1

        rc = tr.get("retry_count")
        if rc and rc > 0:
            retry_runs += 1

        total_tokens_all += (tt or 0)
        total_latency_all += (tr.get("latency_ms") or 0)
        total_calls_all += len(pr)

        stop_reason = tr.get("stop_reason") or "<none>"
        failure_reasons[stop_reason] += 1  # 성공건도 ok 포함해서 센다 (나중에 비율 계산할 때 ok 도 포함)

        # 반복 안정성용: testcase_id별 기록
        agent_output = trial.get("agent_output")
        ah = None
        if agent_output is not None:
            try:
                ah = hashlib.sha256(
                    json.dumps(agent_output, sort_keys=True, default=str).encode("utf-8")
                ).hexdigest()
            except Exception:
                ah = None

        testcase_outcomes[testcase_id].append(
            {
                "trial": tr.get("trial"),
                "task_success": tc,
                "policy_correct": pc_flag,
                "stop_reason": stop_reason,
                "retry_count": rc,
                "tool_schema_valid": trial.get("tool_schema_valid"),
                "agent_output_hash": ah,
            }
        )

    # ── 단계별 비용 프로파일 ──
    profile: Dict[str, dict] = {}
    for role, pcs in provider_by_role.items():
        calls = len(pcs)
        tokens = sum(
            (pc.get("usage") or {}).get("input_tokens", 0)
            + (pc.get("usage") or {}).get("output_tokens", 0)
            for pc in pcs
        )
        latency = sum(pc.get("latency_ms") or 0 for pc in pcs)
        models = sorted({pc.get("model_id") or "<no-model>" for pc in pcs})
        # 정정 ④ — local-deterministic 은 provider 필드에 들어간다. model_id 가 아니다.
        providers = sorted({pc.get("provider") or "<no-provider>" for pc in pcs})

        # type 정보 — traces 쪽에서 가져온다
        ttype = None
        if role in traces_by_role and traces_by_role[role]:
            ttype = traces_by_role[role][0].get("type")

        profile[role] = {
            "calls": calls,
            "tokens": tokens,
            "latency_ms": latency,
            "token_share": None,  # 계산 후에 채움
            "latency_share": None,
            "models": models,
            "providers": providers,
            "is_local_deterministic": "local-deterministic" in providers,
            "type": ttype,
            "outcome_summary": None,
        }

    # share 계산
    if total_tokens_all > 0:
        for r in profile.values():
            r["token_share"] = r["tokens"] / total_tokens_all
    if total_latency_all > 0:
        for r in profile.values():
            r["latency_share"] = r["latency_ms"] / total_latency_all

    # ── traces 개입률 ──
    traces_summary: Dict[str, dict] = {}
    for role, ts in traces_by_role.items():
        runs = len(ts)
        fail_count = sum(1 for t in ts if t.get("outcome") == "fail")
        ok_count = sum(1 for t in ts if t.get("outcome") == "ok")
        skip_count = sum(1 for t in ts if t.get("outcome") == "skip")
        intervention_rate = None
        if runs > 0:
            intervention_rate = fail_count / runs
        traces_summary[role] = {
            "runs": runs,
            "fail_count": fail_count,
            "ok_count": ok_count,
            "skip_count": skip_count,
            "intervention_rate": intervention_rate,
        }
        if role in profile:
            profile[role]["outcome_summary"] = traces_summary[role]

    # ── 안정성 ──
    stability: Dict[str, dict] = {}
    deterministic_count = 0
    for tcid, outcomes in testcase_outcomes.items():
        repeat_count = len(outcomes)
        deterministic = True
        for i in range(1, repeat_count):
            prev = outcomes[i - 1]
            cur = outcomes[i]
            same = (
                prev["task_success"] == cur["task_success"]
                and prev["policy_correct"] == cur["policy_correct"]
                and prev["stop_reason"] == cur["stop_reason"]
                and prev["retry_count"] == cur["retry_count"]
                and prev["tool_schema_valid"] == cur["tool_schema_valid"]
                and prev["agent_output_hash"] == cur["agent_output_hash"]
            )
            if not same:
                deterministic = False
                break
        if deterministic:
            deterministic_count += 1

        roles_same: Dict[str, bool] = {}
        for role in profile.keys():
            vals = set()
            for o in outcomes:
                ah = o.get("agent_output_hash")
                vals.add(ah if ah is not None else "<no-output>")
            roles_same[role] = len(vals) == 1

        stability[tcid] = {
            "deterministic": deterministic,
            "repeat_count": repeat_count,
            "roles_same": roles_same,
        }

    testcase_count = len(testcase_outcomes)

    # 재시도 효용 — diagnosis_rules §1-4: retry_recovery_rate
    # retry_runs 중 실제 성공한 케이스 비율.  retries 가 많은 케이스에서
    # retry_count>0 인 케이스 중 success 인 비율.
    retry_succeeded = 0
    for tcid, outcomes in testcase_outcomes.items():
        for o in outcomes:
            if o["retry_count"] and o["retry_count"] > 0 and o["task_success"] is True:
                retry_succeeded += 1
    retry_recovery_rate = None
    if retry_runs > 0:
        retry_recovery_rate = retry_succeeded / retry_runs

    # 정정 ③ — 분모는 집계에 쓴 trial 수다. testcase 수가 아니다.
    # 반복이 3회면 같은 케이스가 3번 세어지는 것이 맞다. 그게 실제 실행 성공률이다.
    success_rate = None
    policy_accuracy = None
    if used_trials > 0:
        success_rate = success_count / used_trials
        policy_accuracy = policy_correct_count / used_trials

    overall = {
        "total_tokens": total_tokens_all,
        "total_calls": total_calls_all,
        "total_latency_ms": total_latency_all,
        "success_rate": success_rate,
        "policy_accuracy": policy_accuracy,
        "retry_runs": retry_runs,
        "retry_recovery_rate": retry_recovery_rate,
        "failure_reasons": dict(failure_reasons),
        "stability_rate": (deterministic_count / testcase_count) if testcase_count > 0 else None,
        "testcase_count": testcase_count,
        "deterministic_case_count": deterministic_count,
        "used_trials": used_trials,
        "failed_call_total": failed_call_total,
        "failed_call_trials": failed_call_trials,
    }

    return {
        "profile": profile,
        "traces_summary": traces_summary,
        "stability": stability,
        "overall": overall,
    }


# ---------------------------------------------------------------------------
# 2~3단계 · 진단 규칙 적용
# ---------------------------------------------------------------------------

class Finding:
    def __init__(self, fid: str, title: str, severity: str, category: str,
                 condition: str, detail: dict, operator: Optional[str] = None,
                 goal_line: Optional[str] = None):
        self.fid = fid
        self.title = title
        self.severity = severity
        self.category = category
        self.condition = condition
        self.detail = detail
        self.operator = operator
        self.goal_line = goal_line
        self.pending = False  # 판정 보류

    def to_dict(self) -> dict:
        d = {
            "id": self.fid,
            "title": self.title,
            "severity": self.severity,
            "category": self.category,
            "condition": self.condition,
            "detail": self.detail,
            "operator": self.operator,
            "goal_line": self.goal_line,
            "pending": self.pending,
        }
        return d


def apply_common_rules(profile, traces_summary, overall, manifest, trials, skip_reasons) -> List[Finding]:
    """
    diagnosis_rules §2. 공통 규칙 4개.
      D-01 safety_violation
      D-02 token_share >= 35%
      D-03 fail stop_reason 70% 이상 집중
      D-04 scaffold 켜져 있는데 traces에 안 나옴
    """
    findings: List[Finding] = []

    # D-01
    for trial in trials:
        tr = extract_trial_fields(trial)
        if tr.get("safety_violation") is True:
            tcid = tr.get("testcase_id")
            trial_i = tr.get("trial")
            findings.append(
                Finding(
                    "D-01",
                    "안전 위반 발생",
                    "P0",
                    "SAFETY",
                    "safety_violation == true 1건 이상",
                    {
                        "testcase_id": tcid,
                        "trial": trial_i,
                        "safety_violation": True,
                    },
                    operator=None,
                    goal_line="모든 목표 공통 — 안전은 최적화보다 우선",
                )
            )
            # 여러 건이 있어도 1개 Finding으로 충분 (최초 발생 기준)
            break

    # D-02 — token_share >= 35%
    for role, prof in profile.items():
        ts = prof.get("token_share")
        if ts is not None and ts >= 0.35:
            tss = traces_summary.get(role)
            ir = None
            if tss:
                ir = tss.get("intervention_rate")
            findings.append(
                Finding(
                    "D-02",
                    f"비용 집중 단계: {role}",
                    "정보",
                    "COST_HOTSPOT",
                    "token_share >= 35%",
                    {
                        "node_role": role,
                        "token_share": round(ts, 4),
                        "tokens": prof["tokens"],
                        "calls": prof["calls"],
                        "intervention_rate": ir,
                        "models": prof["models"],
                        "type": prof.get("type"),
                    },
                    operator=None,
                    goal_line="어디를 먼저 볼지 알려주는 이정표 — 그 자체 문제 아님",
                )
            )

    # D-03 — 실패 stop_reason 한 종류에 70% 이상 몰림
    # 정정 ⑦ — 분모는 "실패 기록"이다. 정상 종료(OK)는 분모에서도 빼야 한다.
    #           OK를 분모에 넣으면 성공이 많을수록 D-03이 영원히 안 걸린다.
    fr_all = overall.get("failure_reasons") or {}
    fr = {k: v for k, v in fr_all.items() if k not in ("OK", "<none>")}
    total_events = sum(fr.values())
    if total_events > 0:
        for reason, count in fr.items():
            share = count / total_events
            if share >= 0.70:
                findings.append(
                    Finding(
                        "D-03",
                        f"실패 패턴 집중: {reason}",
                        "P1",
                        "FAILURE_PATTERN",
                        "stop_reason 한 종류에 70% 이상",
                        {
                            "stop_reason": reason,
                            "count": count,
                            "share": round(share, 4),
                            "total_events": total_events,
                        },
                        operator=None,
                        goal_line="목표 무관 공통 — 실패 원인 추적 필요",
                    )
                )

    # D-03 (두 번째 조건) — 정정 ① · 응답을 못 받은 모델 호출이 기록의 20% 이상
    used_trials = overall.get("used_trials") or 0
    failed_call_trials = overall.get("failed_call_trials") or 0
    if used_trials > 0 and (failed_call_trials / used_trials) >= 0.20:
        findings.append(
            Finding(
                "D-03",
                "모델 호출 실패 집중",
                "P1",
                "FAILURE_PATTERN",
                "failed_call_count > 0 인 기록이 전체의 20% 이상",
                {
                    "failed_call_trials": failed_call_trials,
                    "failed_call_total": overall.get("failed_call_total"),
                    "used_trials": used_trials,
                    "share": round(failed_call_trials / used_trials, 4),
                },
                operator=None,
                goal_line="목표 무관 공통 — 응답을 못 받은 호출이 잦다. 실패 처리 방식 검토",
            )
        )

    # D-04 — scaffold_config 켜져 있는데 traces에 한 번도 안 나타남
    # log_contract §3: scaffold_config 위치 — manifest.agents.<key>.scaffold_config
    # 인정 항목: repair_enabled, verifier_enabled, max_reflections, max_retries 등 '켜짐' 여부와 관련 단계
    # '켜져 있는데 traces에 안 나타남'을 보려면, 켜진 구성이 어떤 node_role을 쓰는지 알아야 한다.
    # manifest 구조만 보고 단정하긴 어려우나, 최소한 verifier_enabled/repair_enabled 와 관련 역할의 존재 여부를 본다.

    # scaffold 설정 수집
    scaffold_on = {}  # key -> True/False
    agent_trees = manifest.get("agents") or {}
    if agent_trees:
        for agent_key, agent_obj in agent_trees.items():
            sc = (agent_obj or {}).get("scaffold_config") or {}
            if isinstance(sc, dict):
                for k, v in sc.items():
                    if isinstance(v, bool):
                        scaffold_on[f"{agent_key}.{k}"] = v
                    else:
                        scaffold_on[f"{agent_key}.{k}"] = v
    else:
        # fallback: run_metadata 안에 scaffold 설정이 있을 수도 있음
        rm = manifest.get("run_metadata") or {}
        sc2 = rm.get("scaffold_config") or {}
        if isinstance(sc2, dict):
            for k, v in sc2.items():
                scaffold_on[k] = v

    # 관련 node_role 목록 — diagnosis_rules §3-5에서 제외 아닌 '검증/보정' 역할
    verify_roles = {"VERIFY_REASONING", "CHECK_EVIDENCE", "VALIDATE_QUERY"}

    role_set = set(profile.keys()) | set(traces_summary.keys())

    for key, on in scaffold_on.items():
        if on is True:
            # 예: verifier_enabled → VERIFY_REASONING 흔적이 있어야 함
            # 어떤 키가 어떤 역할과 대응하는지 규칙 기반 매핑
            if "verifier" in key.lower():
                if "VERIFY_REASONING" not in role_set:
                    findings.append(
                        Finding(
                            "D-04",
                            f"켠 구조 미관측: {key} (VERIFY_REASONING)",
                            "P1",
                            "DEAD_STRUCTURE",
                            "scaffold_config 켜져 있으나 traces에 없음",
                            {
                                "scaffold_key": key,
                                "expected_role": "VERIFY_REASONING",
                                "present_roles": sorted(role_set),
                            },
                            operator=None,
                            goal_line="목표 무관 공통 — 켜 놓고 안 쓰는 것은 어느 목표에도 이롭지 않음",
                        )
                    )
            if "repair" in key.lower():
                if "REPAIR_QUERY" not in role_set:
                    findings.append(
                        Finding(
                            "D-04",
                            f"켠 구조 미관측: {key} (REPAIR_QUERY)",
                            "P1",
                            "DEAD_STRUCTURE",
                            "scaffold_config 켜져 있으나 traces에 없음",
                            {
                                "scaffold_key": key,
                                "expected_role": "REPAIR_QUERY",
                                "present_roles": sorted(role_set),
                            },
                            operator=None,
                            goal_line="목표 무관 공통",
                        )
                    )

    return findings


# 제외 대상 단계 — §3-5
STAGES_EXCLUDED_FROM_REMOVAL = {
    "VALIDATE_QUERY",
    "CHECK_EVIDENCE",
    "EXECUTE_TOOL",
    "RETRIEVE_SCHEMA",
}

# 정정 ② — C-02 대상은 이 셋뿐이다. 화이트리스트다.
# 개입률은 "선택적 보조 단계가 값을 하는지" 재는 지표이지,
# 업무 단계(DECIDE·GENERATE_QUERY·GENERATE_RESPONSE 등)가 필요한지 재는 지표가 아니다.
# 이 셋 밖의 단계는 개입률이 0이어도 Finding 을 만들지 않는다.
C02_TARGET_ROLES = ("VERIFY_REASONING", "REPAIR_QUERY", "PLAN")


def c02_candidates(profile, traces_summary):
    """C-02 대상 단계와 그 개입률을 돌려준다. 대상이 아니면 아예 내놓지 않는다."""
    for role in C02_TARGET_ROLES:
        prof = profile.get(role)
        if not prof:
            continue
        if prof.get("type") != "llm_call":
            continue
        if (prof.get("tokens") or 0) <= 0:
            continue  # 토큰이 0이면 이미 비용이 없다
        if prof.get("calls", 0) < 3:
            continue
        tss = traces_summary.get(role)
        ir = tss.get("intervention_rate") if tss else None
        if ir is None:
            continue  # 판정 보류. 모르는 것과 0인 것은 다르다.
        if ir != 0:
            continue
        yield role, prof, ir


def apply_cost_rules(profile, traces_summary, overall, stability, manifest) -> List[Finding]:
    """
    diagnosis_rules §3-1 COST 목표 규칙:
      C-01 stability>=0.90 & llm_call → DOWNGRADE_MODEL
      C-02 llm 단계 3회 이상 실행, intervention_rate==0 (→ §3-5 제외 목록 확인)
      C-03 retry_runs>=2 & retry_recovery<=0.05 → REDUCE_LIMIT
      C-04 llm 단계, 출력 구조 항상 같고 intervention_rate==0 → REPLACE_WITH_CODE
      C-05 token_share>=35% 단계가 다른 단계와 같은 모델 공유 → SPLIT_MODEL
    """
    findings: List[Finding] = []
    profile_roles = set(profile.keys())

    testcases_for_stability = overall.get("testcase_count", 0)
    stability_rate = overall.get("stability_rate")
    stable_case_count = overall.get("deterministic_case_count", 0)

    # C-01
    if stability_rate is not None and stability_rate >= 0.90:
        for role, prof in profile.items():
            if prof.get("type") != "llm_call":
                continue
            if not is_llm_call_stage(role, {role: {"type": prof.get("type")}}):
                continue
            models = prof.get("models", [])
            if prof.get("is_local_deterministic"):
                # 모범 사례 — C-01 대상 아님 (이미 코드로 처리됨). 정정 ④
                continue
            tss = traces_summary.get(role)
            ir = None
            if tss:
                ir = tss.get("intervention_rate")
            findings.append(
                Finding(
                    "C-01",
                    f"안정 단계 모델 하향 검토: {role}",
                    "P1",
                    "COST",
                    "stability_rate >= 0.90, llm_call 단계",
                    {
                        "node_role": role,
                        "stability_rate": round(stability_rate, 4),
                        "deterministic_case_count": stable_case_count,
                        "testcase_count": testcases_for_stability,
                        "models": models,
                        "intervention_rate": ir,
                    },
                    operator="DOWNGRADE_MODEL",
                    goal_line="COST — 안정적 단계, 더 낮은 등급 모델 가능성",
                )
            )

    # C-02 — 선택적 보조 단계가 3회 이상 실행됐는데 개입률 0 (정정 ② 화이트리스트)
    for role, prof, ir in c02_candidates(profile, traces_summary):
        findings.append(
            Finding(
                "C-02",
                f"불개입 반복 단계: {role}",
                "P1",
                "COST",
                "선택적 보조 단계(VERIFY_REASONING·REPAIR_QUERY·PLAN), 3회 이상 실행, intervention_rate == 0",
                {
                    "node_role": role,
                    "calls": prof.get("calls"),
                    "intervention_rate": ir,
                    "token_share": prof.get("token_share"),
                    "models": prof.get("models"),
                },
                operator="MAKE_CONDITIONAL 또는 REMOVE",
                goal_line="COST — 반복 호출인데 개입 없음. 조건부화/제거 검토",
            )
        )

    # C-03 — retry_runs>=2 & retry_recovery_rate<=0.05
    retry_runs = overall.get("retry_runs") or 0
    retry_recovery = overall.get("retry_recovery_rate")
    if retry_runs >= 2 and retry_recovery is not None and retry_recovery <= 0.05:
        findings.append(
            Finding(
                "C-03",
                "재시도 효율 저조",
                "P1",
                "COST",
                "retry_runs >= 2 & retry_recovery_rate <= 0.05",
                {
                    "retry_runs": retry_runs,
                    "retry_recovery_rate": round(retry_recovery, 4) if retry_recovery is not None else None,
                },
                operator="REDUCE_LIMIT",
                goal_line="COST — 재시도 해도 거의 못 살림. 상한 축소",
            )
        )

    # C-04 — llm 단계, 출력이 항상 같은 구조이고 intervention_rate==0
    for role, prof in profile.items():
        if prof.get("type") != "llm_call":
            continue
        if role in STAGES_EXCLUDED_FROM_REMOVAL:
            continue
        if not is_llm_call_stage(role, {role: {"type": prof.get("type")}}):
            continue
        # 개입률 0
        tss = traces_summary.get(role)
        ir = None
        if tss:
            ir = tss.get("intervention_rate")
        if ir == 0 or ir is None:
            # '출력이 항상 같은 구조' 판단 — stability 롤별 roles_same이 전부 True & deterministic
            # 이 단계의 '출력 구조' 직접은 없음. 대리 지표로: 이 단계의 agent_output 해시 변동이 없으면 구조 안정.
            roles_stable = True
            for tcid, s in stability.items():
                if not s.get("roles_same", {}).get(role, False):
                    roles_stable = False
                    break
            if roles_stable:
                findings.append(
                    Finding(
                        "C-04",
                        f"결정적 llm 단계 교체 검토: {role}",
                        "P2",
                        "COST",
                        "llm_call 단계, 출력이 항상 같은 구조, intervention_rate == 0",
                        {
                            "node_role": role,
                            "roles_same_all": roles_stable,
                            "intervention_rate": ir,
                            "token_share": prof.get("token_share"),
                        },
                        operator="REPLACE_WITH_CODE",
                        goal_line="COST — 매번 같은 결과면 코드화 가능",
                    )
                )

    # C-05 — token_share>=35% 단계가 다른 단계와 같은 모델을 공유함
    hotspot_roles = [r for r, p in profile.items() if (p.get("token_share") or 0) >= 0.35]
    for hr in hotspot_roles:
        hot_models = set(profile[hr].get("models") or [])
        if not hot_models:
            continue
        other_roles = [r for r in profile if r != hr]
        shared = False
        for or_ in other_roles:
            om = set(profile[or_].get("models") or [])
            if hot_models & om:
                shared = True
                break
        if shared:
            findings.append(
                Finding(
                    "C-05",
                    f"모델 공유 분리 검토: {hr}",
                    "P2",
                    "COST",
                    "token_share >= 35% 단계가 다른 단계와 같은 모델 공유",
                    {
                        "node_role": hr,
                        "token_share": round(profile[hr].get("token_share"), 4),
                        "shared_with": [r for r in profile if r != hr and (set(profile[r].get("models") or set()) & hot_models)],
                        "models": list(hot_models),
                    },
                    operator="SPLIT_MODEL",
                    goal_line="COST — 무거운 단계만 분리하면 모델 별도 선택 가능",
                )
            )

    return findings


def apply_quality_rules(profile, traces_summary, overall, stability, manifest) -> List[Finding]:
    """
    diagnosis_rules §3-2 QUALITY 규칙:
      Q-01 stability<0.90 → UPGRADE_MODEL 또는 ADD_VALIDATION
      Q-02 success<0.95 & retry_recovery>0.3 → INCREASE_LIMIT
      Q-03 verifier_enabled==false & policy_accuracy<0.95 → ENABLE
      Q-04 실패 특정 node_role 몰림 → ADD_VALIDATION
      Q-05 stability>=0.90 & local-deterministic 등 → KEEP (정보)

      ※ C-01·C-02는 QUALITY에서 발화 금지
    """
    findings: List[Finding] = []

    testcases = overall.get("testcase_count", 0)
    stability_rate = overall.get("stability_rate")
    success_rate = overall.get("success_rate")
    policy_accuracy = overall.get("policy_accuracy")
    retry_recovery = overall.get("retry_recovery_rate")

    # scafold verifier_enabled 유무
    verifier_enabled = None
    agent_trees = manifest.get("agents") or {}
    if agent_trees:
        for agent_key, agent_obj in agent_trees.items():
            sc = (agent_obj or {}).get("scaffold_config") or {}
            if isinstance(sc, dict):
                v = sc.get("verifier_enabled")
                if v is not None:
                    verifier_enabled = v
                    break
    if verifier_enabled is None:
        rm = manifest.get("run_metadata") or {}
        sc2 = rm.get("scaffold_config") or {}
        if isinstance(sc2, dict):
            verifier_enabled = sc2.get("verifier_enabled")

    # Q-01
    if stability_rate is not None and stability_rate < 0.90:
        findings.append(
            Finding(
                "Q-01",
                "낮은 반복 안정성",
                "P1",
                "QUALITY",
                "stability_rate < 0.90 — 같은 입력에 결과가 흔들림",
                {
                    "stability_rate": round(stability_rate, 4),
                    "deterministic_case_count": overall.get("deterministic_case_count", 0),
                    "testcase_count": testcases,
                },
                operator="UPGRADE_MODEL 또는 ADD_VALIDATION",
                goal_line="QUALITY — 흔들림 있음. 강 모델/검증 보강",
            )
        )

    # Q-02
    if success_rate is not None and success_rate < 0.95 and retry_recovery is not None and retry_recovery > 0.3:
        findings.append(
            Finding(
                "Q-02",
                "재시도가 실제로 살려냄 — 여유 확대 검토",
                "P1",
                "QUALITY",
                "success_rate < 0.95 & retry_recovery_rate > 0.3",
                {
                    "success_rate": round(success_rate, 4),
                    "retry_recovery_rate": round(retry_recovery, 4),
                    "retry_runs": overall.get("retry_runs", 0),
                },
                operator="INCREASE_LIMIT",
                goal_line="QUALITY — 재시도가 효과 있음. 상한 여유 확대",
            )
        )

    # Q-03
    if verifier_enabled is False and policy_accuracy is not None and policy_accuracy < 0.95:
        findings.append(
            Finding(
                "Q-03",
                "검증기 꺼짐 + 낮은 정책 정확도 — 검증 켜기 검토",
                "P1",
                "QUALITY",
                "verifier_enabled == false & policy_accuracy < 0.95",
                {
                    "verifier_enabled": False,
                    "policy_accuracy": round(policy_accuracy, 4),
                },
                operator="ENABLE",
                goal_line="QUALITY — 꺼진 검증을 켠다",
            )
        )

    # Q-04 — 실패 특정 node_role 몰림
    fr = overall.get("failure_reasons") or {}
    total_events = sum(fr.values())
    if total_events > 0:
        for reason, count in fr.items():
            if reason == "<none>":
                continue
            share = count / total_events
            if share >= 0.70:
                # 해당 역할을 특정할 수 있으면 명시
                findings.append(
                    Finding(
                        "Q-04",
                        f"실패 집중 역할: {reason}",
                        "P1",
                        "QUALITY",
                        "실패가 특정 stop_reason(node_role 연관)에 몰림",
                        {
                            "stop_reason": reason,
                            "count": count,
                            "share": round(share, 4),
                        },
                        operator="ADD_VALIDATION",
                        goal_line="QUALITY — 그 단계에 검증 보강",
                    )
                )

    # Q-05 — stability>=0.90 & local-deterministic 등 모델 호출 아님 → KEEP (정보)
    if stability_rate is not None and stability_rate >= 0.90:
        for role, prof in profile.items():
            models = prof.get("models") or []
            if prof.get("is_local_deterministic") or prof.get("type") != "llm_call":
                # 제외 목록 아님 & 모델 호출 아님 → 모범 사례
                findings.append(
                    Finding(
                        "Q-05",
                        f"모범 단계: {role} (이미 결정론적/코드 처리)",
                        "정보",
                        "QUALITY",
                        "stability_rate >= 0.90 & 모델 호출 아님(local-deterministic 등)",
                        {
                            "node_role": role,
                            "stability_rate": round(stability_rate, 4),
                            "models": models,
                            "type": prof.get("type"),
                        },
                        operator="KEEP",
                        goal_line="QUALITY — 이미 충분, 건드리지 않음",
                    )
                )

    return findings


def apply_latency_rules(profile, traces_summary, overall, stability, manifest) -> List[Finding]:
    """
    diagnosis_rules §3-3 LATENCY 규칙:
      L-01 latency_share>=35% → DOWNGRADE_MODEL 또는 SPLIT_MODEL
      L-02 retry_runs 20% 이상 → REDUCE_LIMIT
      L-03 직렬 LLM 단계 3개 이상 → PARALLELIZE (가능성만 지적)
      L-04 intervention_rate==0 단계가 지연에 기여 → MAKE_CONDITIONAL
    """
    findings: List[Finding] = []

    total_latency = overall.get("total_latency_ms") or 0

    # L-01
    for role, prof in profile.items():
        ls = prof.get("latency_share")
        if ls is not None and ls >= 0.35:
            tss = traces_summary.get(role)
            ir = None
            if tss:
                ir = tss.get("intervention_rate")
            findings.append(
                Finding(
                    "L-01",
                    f"지연 집중 단계: {role}",
                    "P1",
                    "LATENCY",
                    "latency_share >= 35%",
                    {
                        "node_role": role,
                        "latency_share": round(ls, 4),
                        "latency_ms": prof["latency_ms"],
                        "intervention_rate": ir,
                        "models": prof.get("models"),
                        "type": prof.get("type"),
                    },
                    operator="DOWNGRADE_MODEL 또는 SPLIT_MODEL",
                    goal_line="LATENCY — 가장 느린 단계 우선",
                )
            )

    # L-02 — retry_runs가 전체의 20% 이상
    testcase_count = overall.get("testcase_count") or 0
    retry_runs = overall.get("retry_runs") or 0
    if testcase_count > 0:
        retry_share = retry_runs / testcase_count
        if retry_share >= 0.20:
            findings.append(
                Finding(
                    "L-02",
                    "재시도가 실행의 20% 이상 — 상한 축소 검토",
                    "P1",
                    "LATENCY",
                    "retry_runs 비율 >= 20%",
                    {
                        "retry_runs": retry_runs,
                        "testcase_count": testcase_count,
                        "retry_share": round(retry_share, 4),
                    },
                    operator="REDUCE_LIMIT",
                    goal_line="LATENCY — 재시도 자체가 지연 유발",
                )
            )

    # L-03 — 직렬 LLM 단계 3개 이상 (가능성만)
    llm_roles = [r for r, p in profile.items() if p.get("type") == "llm_call"]
    # 직렬 여부는 traces 순서 필요. 여기서는 provider_calls/traces 역할에 llm_call가 몇 개인지만 센다.
    # 정확한 직렬 판정은 traces 순서 정보가 필요하나, 최소 조건: llm_call 역할이 3개 이상.
    if len(llm_roles) >= 3:
        findings.append(
            Finding(
                "L-03",
                f"직렬 LLM 단계 후보: {len(llm_roles)}개",
                "P2",
                "LATENCY",
                "llm_call 단계 3개 이상 — 병렬화 가능성",
                {
                    "llm_role_count": len(llm_roles),
                    "roles": llm_roles,
                },
                operator="PARALLELIZE",
                goal_line="LATENCY — 가능성만 지적, 실제 병렬화 가능 여부는 별도 확인",
            )
        )

    # L-04 — intervention_rate==0 단계가 지연에 기여
    for role, prof in profile.items():
        tss = traces_summary.get(role)
        ir = None
        if tss:
            ir = tss.get("intervention_rate")
        if ir == 0 or ir is None:
            # delay 기여 확인 — latency_share 또는 절대 지연
            ls = prof.get("latency_share") or 0
            if ls > 0 or prof.get("latency_ms", 0) > 0:
                if role not in STAGES_EXCLUDED_FROM_REMOVAL:
                    findings.append(
                        Finding(
                            "L-04",
                            f"불개입 지연 기여 단계: {role}",
                            "P1",
                            "LATENCY",
                            "intervention_rate == 0 이고 지연에 기여",
                            {
                                "node_role": role,
                                "latency_share": round(ls, 4),
                                "latency_ms": prof.get("latency_ms"),
                                "intervention_rate": ir,
                            },
                            operator="MAKE_CONDITIONAL",
                            goal_line="LATENCY — 안 바꿔도 될 단계를 매번 돌림",
                        )
                    )

    return findings


def apply_balanced_rules(profile, traces_summary, overall, manifest) -> List[Finding]:
    """
    diagnosis_rules §3-4 BALANCED — C-02 · C-03 · D-04만.
    모델 등급/품질 강화는 건드리지 않는다.
    """
    findings: List[Finding] = []

    # D-04 (공통) — scaffold 켜져 있는데 traces에 없음
    # balanced에서도 D-04는 명백한 낭비이므로 검사한다.
    # 공통 규칙은 apply_common_rules에서 이미 넣었을 테니 중복 방지: 여기서는 안 넣는다.

    # C-02 — 선택적 보조 단계가 3회 이상 실행됐는데 개입률 0 (정정 ② 화이트리스트)
    for role, prof, ir in c02_candidates(profile, traces_summary):
        findings.append(
            Finding(
                "C-02",
                f"불개입 반복 단계 (경미): {role}",
                "P1",
                "COST",
                "선택적 보조 단계(VERIFY_REASONING·REPAIR_QUERY·PLAN), 3회 이상 실행, intervention_rate == 0",
                {
                    "node_role": role,
                    "calls": prof.get("calls"),
                    "intervention_rate": ir,
                    "token_share": prof.get("token_share"),
                },
                operator="MAKE_CONDITIONAL 또는 REMOVE",
                goal_line="BALANCED — 켰는데 매번 굳이 돌 필요 없는 단계",
            )
        )

    # C-03 — retry_runs>=2 & retry_recovery<=0.05
    retry_runs = overall.get("retry_runs") or 0
    retry_recovery = overall.get("retry_recovery_rate")
    if retry_runs >= 2 and retry_recovery is not None and retry_recovery <= 0.05:
        findings.append(
            Finding(
                "C-03",
                "재시도 효율 저조 (경미)",
                "P1",
                "COST",
                "retry_runs >= 2 & retry_recovery_rate <= 0.05",
                {
                    "retry_runs": retry_runs,
                    "retry_recovery_rate": round(retry_recovery, 4) if retry_recovery is not None else None,
                },
                operator="REDUCE_LIMIT",
                goal_line="BALANCED — 재시도해도 거의 못 살림",
            )
        )

    return findings


# ---------------------------------------------------------------------------
# 3단계 · 전체 판정
# ---------------------------------------------------------------------------

def overall_grade(findings: List[Finding]) -> str:
    """
    diagnosis_rules §4.
      1. SAFETY(D-01) → BLOCK
      2. P1 Finding → ACTION_NEEDED
      3. P2/정보만 → MINOR
      4. 없으면 → ALIGNED
    """
    non_pending = [f for f in findings if not f.pending]
    if any(f.fid == "D-01" for f in non_pending):
        return "BLOCK"
    if any(f.severity == "P1" for f in non_pending):
        return "ACTION_NEEDED"
    if any(f.severity in ("P2", "정보") for f in non_pending):
        return "MINOR"
    return "ALIGNED"


# ---------------------------------------------------------------------------
# 메인 산출
# ---------------------------------------------------------------------------

def run_audit(input_path: str, goal: str, constraint: Optional[str]) -> dict:
    """
    전체 파이프라인을 돌려 프로필+FINDING+판정을 JSON으로 반환.
    stderr 용 경고/실패를 raising 없이 기록한다.
    """
    errors: list = []
    warnings: list = []

    with open(input_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except Exception as e:
            errors.append(f"JSON 파싱 실패: {e}")
            return {"error": errors}

    if not isinstance(data, dict):
        errors.append("입력 JSON 최상위 원소가 object가 아님")
        return {"error": errors}

    manifest, trials, skip_reasons = normalize_runs(data)

    # runs/trial 존재 검사 (사전 조건)
    if "runs 가 비어 있음" in skip_reasons or "testcase 가 비어 있음" in (skip_reasons or []):
        # 사전 조건 위배 — 중단 알림
        for r in skip_reasons:
            warnings.append(r)
        return {"error": errors, "warnings": warnings, "skip_reasons": skip_reasons}

    # trials 개수 카운트 — testcases는 뒤에서 센다.

    # 무결성 검사 결과를 보관할 리스트 (skip_reasons reuse)
    skip_reasons_out = list(skip_reasons)

    prof = compute_profile(manifest, trials, skip_reasons_out)

    # 3개 미만 표본 → 참고용 강등 플래그
    testcase_count = prof["overall"].get("testcase_count", 0)
    low_sample = testcase_count < 3

    # 반복 2회 미만 → 안정성 기반 규칙 강등 플래그
    # stability를 보기 위해 최소 2회 반복 케이스가 있는지
    min_repeats = 999
    for tcid, s in prof["stability"].items():
        if s.get("repeat_count", 0) < min_repeats:
            min_repeats = s.get("repeat_count", 0)
    low_repeats = min_repeats < 2

    profile = prof["profile"]
    traces_summary = prof["traces_summary"]
    stability = prof["stability"]
    overall = prof["overall"]

    findings: List[Finding] = []

    # 공통 규칙 (목표 무관)
    findings += apply_common_rules(profile, traces_summary, overall, manifest, trials, skip_reasons_out)

    # 목표별 규칙
    if goal == "COST":
        findings += apply_cost_rules(profile, traces_summary, overall, stability, manifest)
    elif goal == "QUALITY":
        findings += apply_quality_rules(profile, traces_summary, overall, stability, manifest)
        # QUALITY에선 C-01·C-02 발화 금지 — 이미 apply_quality_rules에서 안 넣음
    elif goal == "LATENCY":
        findings += apply_latency_rules(profile, traces_summary, overall, stability, manifest)
    elif goal == "BALANCED":
        findings += apply_balanced_rules(profile, traces_summary, overall, manifest)
    else:
        warnings.append(f"알 수 없는 목표 '{goal}' — BALANCED로 진행")

    # 표본 부족 강등
    downgraded_ids: set = set()
    if low_sample:
        for f in findings:
            f.pending = True  # 참고용 강등
            downgraded_ids.add(f.fid)
    if low_repeats:
        # 안정성 기반 규칙 강등
        stable_rule_ids = {"C-01", "C-04", "Q-01", "Q-05"}
        for f in findings:
            if f.fid in stable_rule_ids and not f.pending:
                f.pending = True
                downgraded_ids.add(f.fid)

    grade = overall_grade(findings)

    out = {
        "goal": goal,
        "constraint": constraint,
        "manifest_summary": {
            "provider": (manifest.get("run_metadata") or {}).get("provider"),
            "model": (manifest.get("run_metadata") or {}).get("model"),
        },
        "sample_info": {
            "testcase_count": testcase_count,
            "low_sample_warning": low_sample,
            "min_repeats": min_repeats,
            "low_repeats_warning": low_repeats,
            "deterministic_case_count": overall.get("deterministic_case_count"),
            "stability_rate": overall.get("stability_rate"),
        },
        "overall": {
            "total_tokens": overall.get("total_tokens"),
            "total_calls": overall.get("total_calls"),
            "total_latency_ms": overall.get("total_latency_ms"),
            "success_rate": overall.get("success_rate"),
            "policy_accuracy": overall.get("policy_accuracy"),
            "retry_runs": overall.get("retry_runs"),
            "retry_recovery_rate": overall.get("retry_recovery_rate"),
            "failure_reasons": overall.get("failure_reasons"),
            "stability_rate": overall.get("stability_rate"),
            "testcase_count": overall.get("testcase_count"),
            # 정정 ① — 보고서 §0 「입력 점검」이 쓴다
            "used_trials": overall.get("used_trials"),
            "failed_call_total": overall.get("failed_call_total"),
            "failed_call_trials": overall.get("failed_call_trials"),
        },
        "profile": [],
        "traces_summary": [],
        "findings": [],
        "grade": grade,
        "downgraded_finding_ids": sorted(downgraded_ids),
        "skip_reasons": skip_reasons_out,
        "warnings": warnings,
        "errors": errors,
    }

    # 프로필 표 — token_share 합 검증 포함
    token_sum = 0.0
    latency_sum = 0.0
    for role, p in profile.items():
        out["profile"].append(
            {
                "node_role": role,
                "calls": p.get("calls"),
                "tokens": p.get("tokens"),
                "token_share": round(p.get("token_share"), 6) if p.get("token_share") is not None else None,
                "latency_ms": p.get("latency_ms"),
                "latency_share": round(p.get("latency_share"), 6) if p.get("latency_share") is not None else None,
                "models": p.get("models"),
                "type": p.get("type"),
                "intervention_rate": (traces_summary.get(role) or {}).get("intervention_rate"),
                "runs": (traces_summary.get(role) or {}).get("runs"),
            }
        )
        tshare = p.get("token_share")
        if tshare is not None:
            token_sum += tshare
        lshare = p.get("latency_share")
        if lshare is not None:
            latency_sum += lshare

    out["profile_token_share_sum"] = round(token_sum, 6)
    out["profile_latency_share_sum"] = round(latency_sum, 6)

    # traces summary 표
    for role, ts in traces_summary.items():
        out["traces_summary"].append(
            {
                "node_role": role,
                "runs": ts.get("runs"),
                "fail_count": ts.get("fail_count"),
                "ok_count": ts.get("ok_count"),
                "skip_count": ts.get("skip_count"),
                "intervention_rate": ts.get("intervention_rate"),
            }
        )

    # Finding 목록
    for f in findings:
        fd = f.to_dict()
        if f.pending:
            fd["note"] = "표본 부족/반복 부족으로 참고용 강등"
        out["findings"].append(fd)

    # 잘돌아가고 있는 단계 정보 (5단계 단서)
    # 정정 ⑤ — Q-05 는 QUALITY 목표에서만 발화한다. 거기서만 모으면
    # COST·LATENCY·BALANCED 에서는 이 값이 구조적으로 항상 빈 배열이 된다.
    # 모범 사례는 목표와 무관하게 나와야 하므로 프로파일에서 직접 계산한다.
    good_roles = []
    for role, prof in profile.items():
        if prof.get("is_local_deterministic"):
            good_roles.append(role)
        elif prof.get("calls", 0) > 0 and (prof.get("tokens") or 0) == 0:
            good_roles.append(role)
    for f in findings:
        if f.operator == "KEEP" or f.fid == "Q-05":
            good_roles.append(f.detail.get("node_role"))
    out["already_good_roles"] = sorted({r for r in good_roles if r})

    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(
        description="agent-config-advisor 진단 스크립트 (0~3단계)"
    )
    p.add_argument("input", help="실행 로그 JSON 파일 경로")
    p.add_argument(
        "--goal",
        default="BALANCED",
        help="진단 목표: COST | QUALITY | LATENCY | BALANCED (미지정 시 BALANCED)",
    )
    p.add_argument(
        "--constraint",
        default=None,
        help="사용자가 밝힌 제약 (예: '성공률 95% 아래로는 안 돼')",
    )
    p.add_argument(
        "--nl-goal",
        default=None,
        help="자연어로 된 목표 문장. 주면 해석해서 --goal에 매핑한다.",
    )
    args = p.parse_args()

    goal = args.goal
    if args.nl_goal:
        g = interpret_goal(args.nl_goal)
        if g:
            goal = g
        else:
            goal = "BALANCED"
            print(f"자연어 목표 '{args.nl_goal}'을(를) 해석하지 못함 → BALANCED로 진행", file=sys.stderr)

    result = run_audit(args.input, goal, args.constraint)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
