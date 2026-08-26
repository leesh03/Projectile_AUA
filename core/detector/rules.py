"""탐지 규칙 카탈로그. AUA_개발_기획서.md §5의 R-/E-/O-/S- 규칙을 그대로 구현한다.

우선순위 1~6(R-01, R-02, E-01, O-02, O-01, S-01/S-02)이 데모 3종을 커버하는 필수 규칙이고,
나머지(R-03~R-05, E-02~E-04, O-03)는 여유분이다. O-03(무영향 중복 노드)은 "downstream 영향"을
정의하기 까다로워 이번 스프린트에서는 보류한다.
"""

from __future__ import annotations

from collections import defaultdict

from core.detector.base import REGISTRY, DetectionContext, Rule, register
from core.diff.aggregate import VersionMetrics
from core.diff.compare import FlipClass
from core.schemas.enums import FindingType, Severity
from core.schemas.finding import Evidence, Finding, FirstDivergence
from core.schemas.trace import TraceStep

# ── 임계값 (AUA_개발_기획서.md §5) ────────────────────────────────────────
E01_RETRY_DELTA_MIN = 0.5  # 평균 retry 증가 (횟수)
E02_TOKEN_PCT_MIN = 15.0  # 평균 token 증가 (%)
E03_LATENCY_PCT_MIN = 20.0  # 평균 latency 증가 (%)
E04_STEP_PCT_MIN = 20.0  # 평균 step 수 증가 (%)

R02_SCHEMA_DROP_PP_MIN = 5.0  # tool_schema_valid_rate 하락 (퍼센트 포인트)
R03_POLICY_DROP_PP_MIN = 5.0  # policy_accuracy 하락 (퍼센트 포인트)
R04_STOP_REASON_DROP_PP_MIN = 5.0  # non-OK stop_reason 비율 증가 (퍼센트 포인트)
R05_DIFFICULTY_DROP_PP_MIN = 10.0  # 난이도 구간별 성공률 하락 (퍼센트 포인트)

O01_MIN_VERIFY_STEPS = 3  # 이 미만이면 표본 부족으로 판단 보류
O02_MIN_RETRY_RUNS = 2  # 재시도가 있었던 run이 이만큼은 있어야 회복률을 말할 수 있음
O02_RECOVERY_RATE_MAX = 0.05  # 이 이하면 "회복률 ≈ 0"

SQL_GUARD_ERROR_TYPES = {
    "FORBIDDEN_SQL_COMMAND",
    "SELECT_ONLY_VIOLATION",
    "UNAUTHORIZED_TABLE_ACCESS",
}


# ── 공용 헬퍼 ─────────────────────────────────────────────────────────────
def _rate_drop_cases(ctx: DetectionContext, getter, min_drop_pp: float) -> list[str]:
    """testcase별로 getter(VersionMetrics) -> float|None 값이 V0보다 V1에서 떨어진 케이스."""
    affected = []
    for tc, tc_agg in ctx.agg.by_testcase.items():
        v0m = tc_agg.metrics_by_label.get(ctx.v0_label)
        v1m = tc_agg.metrics_by_label.get(ctx.v1_label)
        if v0m is None or v1m is None:
            continue
        v0_val, v1_val = getter(v0m), getter(v1m)
        if v0_val is None or v1_val is None:
            continue
        if (v0_val - v1_val) * 100 >= min_drop_pp:
            affected.append(tc)
    return sorted(affected)


def _group_traces_by_run(traces: list[TraceStep], label: str) -> dict[tuple, list[TraceStep]]:
    runs: dict[tuple, list[TraceStep]] = defaultdict(list)
    for step in traces:
        if step.agent_label != label:
            continue
        key = (step.testcase_id, step.run_id or f"{step.testcase_id}:{step.trial}")
        runs[key].append(step)
    for steps in runs.values():
        steps.sort(key=lambda s: s.step_index)
    return runs


# ── Regression ────────────────────────────────────────────────────────────
@register
class R01PassToFail(Rule):
    rule_id = "R-01"
    severity = Severity.P0

    def evaluate(self, ctx: DetectionContext) -> list[Finding]:
        findings: list[Finding] = []
        v0m = ctx.agg.overall[ctx.v0_label]
        v1m = ctx.agg.overall[ctx.v1_label]
        sr = ctx.diff.overall.metrics["success_rate"]

        regressed = ctx.diff.testcases_by(FlipClass.REGRESSION)
        if regressed:
            findings.append(
                Finding(
                    finding_id=f"F-{self.rule_id}",
                    type=FindingType.REGRESSION,
                    severity=self.severity,
                    rule_id=self.rule_id,
                    title=f"{len(regressed)}개 testcase가 {ctx.v0_label} PASS -> {ctx.v1_label} FAIL로 뒤집힘",
                    affected_testcases=regressed,
                    evidence=Evidence(
                        metric="success_rate", v0=v0m.success_rate, v1=v1m.success_rate, delta_pp=sr.delta_pp
                    ),
                )
            )

        improved = ctx.diff.testcases_by(FlipClass.IMPROVEMENT)
        if improved:
            findings.append(
                Finding(
                    finding_id=f"F-{self.rule_id}-IMPROVEMENT",
                    type=FindingType.IMPROVEMENT,
                    severity=Severity.P2,
                    rule_id=self.rule_id,
                    title=f"{len(improved)}개 testcase가 {ctx.v0_label} FAIL -> {ctx.v1_label} PASS로 개선됨",
                    affected_testcases=improved,
                    evidence=Evidence(
                        metric="success_rate", v0=v0m.success_rate, v1=v1m.success_rate, delta_pp=sr.delta_pp
                    ),
                )
            )
        return findings


@register
class R02ToolSchemaRegression(Rule):
    rule_id = "R-02"
    severity = Severity.P0
    requires = ("tool_schema_valid",)

    def evaluate(self, ctx: DetectionContext) -> list[Finding]:
        metric = ctx.diff.overall.metrics.get("tool_schema_valid_rate")
        if metric is None or metric.delta_pp is None or metric.delta_pp > -R02_SCHEMA_DROP_PP_MIN:
            return []

        affected = _rate_drop_cases(
            ctx, lambda m: m.tool_schema_valid_rate, R02_SCHEMA_DROP_PP_MIN
        )
        if not affected:
            return []

        first_divergence = None
        if ctx.has_trace:
            first_divergence = _first_tool_arg_divergence(ctx, affected[0])

        return [
            Finding(
                finding_id=f"F-{self.rule_id}",
                type=FindingType.REGRESSION,
                severity=self.severity,
                rule_id=self.rule_id,
                title="tool 인자 스키마 유효율 하락",
                affected_testcases=affected,
                evidence=Evidence(
                    metric="tool_schema_valid_rate",
                    v0=metric.v0,
                    v1=metric.v1,
                    delta_pp=metric.delta_pp,
                    threshold=f"{metric.delta_pp:+.1f}pp <= 임계 -{R02_SCHEMA_DROP_PP_MIN:.1f}pp",
                ),
                first_divergence=first_divergence,
            )
        ]


def _first_tool_arg_divergence(ctx: DetectionContext, testcase_id: str) -> FirstDivergence | None:
    if not ctx.load_result.traces:
        return None
    candidates = [
        s
        for s in ctx.load_result.traces
        if s.testcase_id == testcase_id
        and s.agent_label == ctx.v1_label
        and s.node_role.value == "EXECUTE_TOOL"
        and s.arguments_valid is False
    ]
    if not candidates:
        return None
    step = min(candidates, key=lambda s: s.step_index)
    return FirstDivergence(
        node_role=step.node_role,
        step_index=step.step_index,
        detail=f"tool_name={step.tool_name!r}, arguments_valid=False (error_type={step.error_type})",
    )


@register
class R03PolicyAccuracyRegression(Rule):
    rule_id = "R-03"
    severity = Severity.P0
    requires = ()  # policy_correct는 필수 필드라 항상 있음

    def evaluate(self, ctx: DetectionContext) -> list[Finding]:
        metric = ctx.diff.overall.metrics.get("policy_accuracy")
        if metric is None or metric.delta_pp is None or metric.delta_pp > -R03_POLICY_DROP_PP_MIN:
            return []

        affected = _rate_drop_cases(ctx, lambda m: m.policy_accuracy, R03_POLICY_DROP_PP_MIN)
        if not affected:
            return []

        return [
            Finding(
                finding_id=f"F-{self.rule_id}",
                type=FindingType.REGRESSION,
                severity=self.severity,
                rule_id=self.rule_id,
                title="정책 판정 정확도 하락",
                affected_testcases=affected,
                evidence=Evidence(
                    metric="policy_accuracy",
                    v0=metric.v0,
                    v1=metric.v1,
                    delta_pp=metric.delta_pp,
                    threshold=f"{metric.delta_pp:+.1f}pp <= 임계 -{R03_POLICY_DROP_PP_MIN:.1f}pp",
                ),
            )
        ]


def _non_ok_rate(m: VersionMetrics) -> float:
    if m.trial_count == 0:
        return 0.0
    ok = m.stop_reason_distribution.get("OK", 0)
    return 1.0 - (ok / m.trial_count)


@register
class R04StopReasonRegression(Rule):
    rule_id = "R-04"
    severity = Severity.P1

    def evaluate(self, ctx: DetectionContext) -> list[Finding]:
        v0m = ctx.agg.overall[ctx.v0_label]
        v1m = ctx.agg.overall[ctx.v1_label]
        v0_rate, v1_rate = _non_ok_rate(v0m), _non_ok_rate(v1m)
        delta_pp = (v1_rate - v0_rate) * 100
        if delta_pp < R04_STOP_REASON_DROP_PP_MIN:
            return []

        affected = _rate_drop_cases(
            ctx, lambda m: 1.0 - _non_ok_rate(m), R04_STOP_REASON_DROP_PP_MIN
        )
        if not affected:
            return []

        return [
            Finding(
                finding_id=f"F-{self.rule_id}",
                type=FindingType.REGRESSION,
                severity=self.severity,
                rule_id=self.rule_id,
                title="종료 사유(stop_reason) 분포 악화 — 실패로 끝나는 비율 증가",
                affected_testcases=affected,
                evidence=Evidence(
                    metric="non_ok_stop_reason_rate",
                    v0=v0_rate,
                    v1=v1_rate,
                    delta_pp=delta_pp,
                    threshold=f"{delta_pp:+.1f}pp >= 임계 {R04_STOP_REASON_DROP_PP_MIN:.1f}pp",
                ),
            )
        ]


@register
class R05DifficultyRegression(Rule):
    rule_id = "R-05"
    severity = Severity.P1
    requires = ("difficulty",)

    def evaluate(self, ctx: DetectionContext) -> list[Finding]:
        if len(ctx.agg.by_difficulty) < 2:
            return []  # 난이도가 1개뿐이면 "특정 구간에서만"이라는 말이 성립하지 않는다

        drop_pp_by_difficulty: dict[str, float] = {}
        for difficulty, by_label in ctx.agg.by_difficulty.items():
            v0m = by_label.get(ctx.v0_label)
            v1m = by_label.get(ctx.v1_label)
            if v0m is not None and v1m is not None:
                drop_pp_by_difficulty[difficulty] = (v0m.success_rate - v1m.success_rate) * 100

        findings: list[Finding] = []
        for difficulty, by_label in sorted(ctx.agg.by_difficulty.items()):
            v0m = by_label.get(ctx.v0_label)
            v1m = by_label.get(ctx.v1_label)
            if v0m is None or v1m is None:
                continue
            this_drop_pp = drop_pp_by_difficulty[difficulty]
            delta_pp = -this_drop_pp
            if this_drop_pp < R05_DIFFICULTY_DROP_PP_MIN:
                continue
            other_drops = [d for k, d in drop_pp_by_difficulty.items() if k != difficulty]
            other_avg_drop_pp = sum(other_drops) / len(other_drops) if other_drops else 0.0
            if other_avg_drop_pp >= R05_DIFFICULTY_DROP_PP_MIN / 2:
                continue  # 다른 난이도도 비슷하게 떨어졌다 -> 난이도-특이적 현상이 아니라 전반적 회귀
            affected = sorted(
                tc
                for tc, tca in ctx.agg.by_testcase.items()
                if tca.difficulty == difficulty
                and tca.task_success_by_label.get(ctx.v0_label)
                and not tca.task_success_by_label.get(ctx.v1_label)
            )
            if not affected:
                continue
            findings.append(
                Finding(
                    finding_id=f"F-{self.rule_id}-{difficulty}",
                    type=FindingType.REGRESSION,
                    severity=self.severity,
                    rule_id=self.rule_id,
                    title=f"난이도 '{difficulty}' 구간에서만 성공률 하락",
                    affected_testcases=affected,
                    evidence=Evidence(
                        metric=f"success_rate[{difficulty}]",
                        v0=v0m.success_rate,
                        v1=v1m.success_rate,
                        delta_pp=delta_pp,
                        threshold=f"{delta_pp:+.1f}pp <= 임계 -{R05_DIFFICULTY_DROP_PP_MIN:.1f}pp",
                    ),
                )
            )
        return findings


# ── Efficiency ────────────────────────────────────────────────────────────
def _overall_metric_increase_finding(
    ctx: DetectionContext, *, rule_id: str, severity: Severity, metric_name: str, title: str, threshold_pct: float
) -> list[Finding]:
    """평균 지표(token/latency 등)가 전체적으로 threshold_pct% 이상 늘었으면 Finding 1개."""
    metric = ctx.diff.overall.metrics.get(metric_name)
    if metric is None or metric.delta_pct is None or metric.delta_pct < threshold_pct:
        return []
    return [
        Finding(
            finding_id=f"F-{rule_id}",
            type=FindingType.EFFICIENCY_WARNING,
            severity=severity,
            rule_id=rule_id,
            title=title,
            affected_testcases=sorted(ctx.agg.by_testcase.keys()),
            evidence=Evidence(
                metric=metric_name,
                v0=metric.v0,
                v1=metric.v1,
                delta_pct=metric.delta_pct,
                threshold=f"{metric.delta_pct:+.1f}% >= 임계 {threshold_pct:.1f}%",
            ),
        )
    ]


@register
class E01RetryIncrease(Rule):
    rule_id = "E-01"
    severity = Severity.P1

    def evaluate(self, ctx: DetectionContext) -> list[Finding]:
        metric = ctx.diff.overall.metrics.get("avg_retry")
        if metric is None or metric.delta is None or metric.delta < E01_RETRY_DELTA_MIN:
            return []
        affected = sorted(
            tc
            for tc, tca in ctx.agg.by_testcase.items()
            if (v0m := tca.metrics_by_label.get(ctx.v0_label))
            and (v1m := tca.metrics_by_label.get(ctx.v1_label))
            and (v1m.avg_retry - v0m.avg_retry) >= E01_RETRY_DELTA_MIN
        )
        if not affected:
            return []
        return [
            Finding(
                finding_id=f"F-{self.rule_id}",
                type=FindingType.EFFICIENCY_WARNING,
                severity=self.severity,
                rule_id=self.rule_id,
                title="평균 재시도 횟수 증가",
                affected_testcases=affected,
                evidence=Evidence(
                    metric="avg_retry",
                    v0=metric.v0,
                    v1=metric.v1,
                    delta=metric.delta,
                    threshold=f"{metric.delta:+.2f}회 >= 임계 {E01_RETRY_DELTA_MIN:.2f}회",
                ),
            )
        ]


@register
class E02TokenIncrease(Rule):
    rule_id = "E-02"
    severity = Severity.P2

    def evaluate(self, ctx: DetectionContext) -> list[Finding]:
        return _overall_metric_increase_finding(
            ctx,
            rule_id=self.rule_id,
            severity=self.severity,
            metric_name="avg_tokens",
            title="평균 토큰 사용량 증가",
            threshold_pct=E02_TOKEN_PCT_MIN,
        )


@register
class E03LatencyIncrease(Rule):
    rule_id = "E-03"
    severity = Severity.P2

    def evaluate(self, ctx: DetectionContext) -> list[Finding]:
        return _overall_metric_increase_finding(
            ctx,
            rule_id=self.rule_id,
            severity=self.severity,
            metric_name="avg_latency_ms",
            title="평균 응답 지연 증가",
            threshold_pct=E03_LATENCY_PCT_MIN,
        )


@register
class E04StepCountIncrease(Rule):
    rule_id = "E-04"
    severity = Severity.P2
    requires = ("trace",)

    def evaluate(self, ctx: DetectionContext) -> list[Finding]:
        traces = ctx.load_result.traces or []
        v0_runs = _group_traces_by_run(traces, ctx.v0_label)
        v1_runs = _group_traces_by_run(traces, ctx.v1_label)
        if not v0_runs or not v1_runs:
            return []

        v0_avg = sum(len(steps) for steps in v0_runs.values()) / len(v0_runs)
        v1_avg = sum(len(steps) for steps in v1_runs.values()) / len(v1_runs)
        if v0_avg == 0:
            return []
        delta_pct = (v1_avg - v0_avg) / v0_avg * 100
        if delta_pct < E04_STEP_PCT_MIN:
            return []

        affected = sorted(
            {tc for (tc, _run_id) in v1_runs if len(v1_runs[(tc, _run_id)]) > 0}
        )
        return [
            Finding(
                finding_id=f"F-{self.rule_id}",
                type=FindingType.EFFICIENCY_WARNING,
                severity=self.severity,
                rule_id=self.rule_id,
                title="평균 Trace 단계 수 증가",
                affected_testcases=affected,
                evidence=Evidence(
                    metric="avg_step_count",
                    v0=v0_avg,
                    v1=v1_avg,
                    delta_pct=delta_pct,
                    threshold=f"{delta_pct:+.1f}% >= 임계 {E04_STEP_PCT_MIN:.1f}%",
                ),
            )
        ]


# ── Opportunity ───────────────────────────────────────────────────────────
@register
class O01VerifierNeverChanges(Rule):
    rule_id = "O-01"
    severity = Severity.P1
    requires = ("trace",)

    def evaluate(self, ctx: DetectionContext) -> list[Finding]:
        traces = ctx.load_result.traces or []
        v1_verify_steps = [
            s for s in traces if s.agent_label == ctx.v1_label and s.node_role.value == "VERIFY_REASONING"
        ]
        if len(v1_verify_steps) < O01_MIN_VERIFY_STEPS:
            return []

        intervention_count = sum(1 for s in v1_verify_steps if s.outcome.value == "fail")
        if intervention_count > 0:
            return []  # 최소 한 번은 판정을 바꿨다 -> Opportunity 아님

        v0_verify_steps = [
            s for s in traces if s.agent_label == ctx.v0_label and s.node_role.value == "VERIFY_REASONING"
        ]
        v0_rate = (
            sum(1 for s in v0_verify_steps if s.outcome.value == "fail") / len(v0_verify_steps)
            if v0_verify_steps
            else 0.0
        )

        affected = sorted({s.testcase_id for s in v1_verify_steps})
        title = f"Verifier가 {len(affected)}개 케이스 전체에서 판정을 한 번도 바꾸지 않음"
        llm_calls = ctx.diff.overall.metrics.get("avg_llm_call_count")
        if llm_calls is not None:
            title += f" (조건부로 끄면 케이스당 LLM 호출 약 1회, 현재 평균 {llm_calls.v1:.1f}회 절감 추정)"

        return [
            Finding(
                finding_id=f"F-{self.rule_id}",
                type=FindingType.OPTIMIZATION_OPPORTUNITY,
                severity=self.severity,
                rule_id=self.rule_id,
                title=title,
                affected_testcases=affected,
                evidence=Evidence(
                    metric="verifier_intervention_rate",
                    v0=v0_rate,
                    v1=0.0,
                    threshold=f"intervention_rate == 0.0 (표본 {len(v1_verify_steps)}건)",
                ),
            )
        ]


@register
class O02RetryRecoveryNearZero(Rule):
    rule_id = "O-02"
    severity = Severity.P1
    requires = ("trace",)

    def evaluate(self, ctx: DetectionContext) -> list[Finding]:
        traces = ctx.load_result.traces or []
        v1_runs = _group_traces_by_run(traces, ctx.v1_label)

        retry_run_keys: list[tuple] = []
        for key, steps in v1_runs.items():
            error_types_seen: dict[str, int] = defaultdict(int)
            for s in steps:
                if s.error_type:
                    error_types_seen[s.error_type] += 1
            if any(count >= 2 for count in error_types_seen.values()):
                retry_run_keys.append(key)

        if len(retry_run_keys) < O02_MIN_RETRY_RUNS:
            return []

        # run key = (testcase_id, run_id). trial 번호가 필요하니 trials에서 역참조한다.
        recovered = 0
        affected: list[str] = []
        trial_lookup = {
            (t.testcase_id, t.trial): t.task_success for t in ctx.load_result.trials if t.agent_label == ctx.v1_label
        }
        for testcase_id, _run_id in retry_run_keys:
            steps = v1_runs[(testcase_id, _run_id)]
            trial_no = steps[0].trial
            succeeded = trial_lookup.get((testcase_id, trial_no), False)
            if succeeded:
                recovered += 1
            else:
                affected.append(testcase_id)

        recovery_rate = recovered / len(retry_run_keys)
        if recovery_rate > O02_RECOVERY_RATE_MAX:
            return []

        affected = sorted(set(affected)) or sorted({tc for tc, _ in retry_run_keys})
        return [
            Finding(
                finding_id=f"F-{self.rule_id}",
                type=FindingType.OPTIMIZATION_OPPORTUNITY,
                severity=self.severity,
                rule_id=self.rule_id,
                title="같은 오류로 재시도해도 거의 회복하지 못함 — 재시도 상한을 낮출 여지",
                affected_testcases=affected,
                evidence=Evidence(
                    metric="retry_recovery_rate",
                    v0=0.0,
                    v1=recovery_rate,
                    threshold=f"recovery_rate {recovery_rate:.2f} <= 임계 {O02_RECOVERY_RATE_MAX:.2f} "
                    f"(표본 {len(retry_run_keys)}건)",
                ),
            )
        ]


# ── Safety ────────────────────────────────────────────────────────────────
@register
class SafetyViolation(Rule):
    rule_id = "S-01"
    severity = Severity.P0

    def evaluate(self, ctx: DetectionContext) -> list[Finding]:
        v1_violations = [
            t for t in ctx.load_result.trials if t.agent_label == ctx.v1_label and t.safety_violation
        ]
        if not v1_violations:
            return []

        is_sql_guard = any(t.error_type in SQL_GUARD_ERROR_TYPES for t in v1_violations)
        rule_id = "S-02" if is_sql_guard else "S-01"
        affected = sorted({t.testcase_id for t in v1_violations})

        v0m = ctx.agg.overall[ctx.v0_label]
        v1m = ctx.agg.overall[ctx.v1_label]

        return [
            Finding(
                finding_id=f"F-{rule_id}",
                type=FindingType.SAFETY_ALERT,
                severity=Severity.P0,
                rule_id=rule_id,
                title="안전 위반 발생 — 다른 모든 판정보다 최우선 (BLOCK)",
                affected_testcases=affected,
                evidence=Evidence(
                    metric="safety_violations",
                    v0=float(v0m.safety_violations),
                    v1=float(v1m.safety_violations),
                    delta=float(v1m.safety_violations - v0m.safety_violations),
                ),
            )
        ]


DEFAULT_RULES: list[Rule] = REGISTRY
