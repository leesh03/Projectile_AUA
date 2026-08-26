"""L2 — Metric Aggregator. testcase별 -> 버전별 -> 전체 순으로 집계한다.

LLM 호출 0회. 여기서 계산한 숫자가 보고서에 나오는 모든 수치의 유일한 출처다 (P5에서도 안 바뀐다).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.schemas.loader import LoadResult
from core.schemas.trial import TrialResult


def _rate(flags: list[bool]) -> float:
    """빈 목록 방어: 표본이 없으면 0.0 (규칙 단에서 표본 수를 따로 확인해야 함)."""
    return sum(flags) / len(flags) if flags else 0.0


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


@dataclass
class VersionMetrics:
    """testcase 1개(또는 전체) × 버전 1개의 집계값. 필드 이름이 UpgradeReport.summary와 대응한다."""

    label: str
    trial_count: int
    success_rate: float
    policy_accuracy: float
    tool_error_rate: float
    avg_retry: float
    avg_tokens: float
    avg_latency_ms: float
    safety_violations: int
    stop_reason_distribution: dict[str, int]
    # 권장 필드 기반 — 입력에 하나도 없으면 None (그 지표를 쓰는 규칙은 SKIPPED)
    tool_schema_valid_rate: float | None = None
    avg_llm_call_count: float | None = None


def _aggregate_trials(trials: list[TrialResult], label: str) -> VersionMetrics:
    stop_dist: dict[str, int] = {}
    for t in trials:
        key = t.stop_reason.value
        stop_dist[key] = stop_dist.get(key, 0) + 1

    schema_flags = [t.tool_schema_valid for t in trials if t.tool_schema_valid is not None]
    llm_calls = [float(t.llm_call_count) for t in trials if t.llm_call_count is not None]

    return VersionMetrics(
        label=label,
        trial_count=len(trials),
        success_rate=_rate([t.task_success for t in trials]),
        policy_accuracy=_rate([t.policy_correct for t in trials]),
        tool_error_rate=_rate([t.tool_error_count > 0 for t in trials]),
        avg_retry=_mean([float(t.retry_count) for t in trials]),
        avg_tokens=_mean([float(t.total_tokens) for t in trials]),
        avg_latency_ms=_mean([float(t.latency_ms) for t in trials]),
        safety_violations=sum(1 for t in trials if t.safety_violation),
        stop_reason_distribution=stop_dist,
        tool_schema_valid_rate=_rate(schema_flags) if schema_flags else None,
        avg_llm_call_count=_mean(llm_calls) if llm_calls else None,
    )


@dataclass
class TestCaseAggregate:
    testcase_id: str
    difficulty: str | None
    metrics_by_label: dict[str, VersionMetrics]
    # testcase 하나의 "성공 여부"는 보수적으로 정의한다: 그 버전의 trial 전부가 성공해야 PASS.
    # trial 하나만 실패해도 재현 안정성이 없다는 뜻이라 PASS로 치지 않는다.
    task_success_by_label: dict[str, bool]


@dataclass
class AggregateResult:
    overall: dict[str, VersionMetrics]  # label -> 전체 testcase 통합 집계
    by_testcase: dict[str, TestCaseAggregate]
    by_difficulty: dict[str, dict[str, VersionMetrics]] = field(default_factory=dict)
    labels: tuple[str, str] = ("V0", "V1")  # (baseline_label, candidate_label)


def aggregate(load_result: LoadResult) -> AggregateResult:
    baseline_label = load_result.baseline.label
    candidate_label = load_result.candidate.label

    trials_by_case: dict[str, list[TrialResult]] = {}
    for t in load_result.trials:
        trials_by_case.setdefault(t.testcase_id, []).append(t)

    by_testcase: dict[str, TestCaseAggregate] = {}
    for tc, trials in trials_by_case.items():
        by_label: dict[str, list[TrialResult]] = {}
        for t in trials:
            by_label.setdefault(t.agent_label, []).append(t)

        by_testcase[tc] = TestCaseAggregate(
            testcase_id=tc,
            difficulty=trials[0].difficulty,
            metrics_by_label={label: _aggregate_trials(lst, label) for label, lst in by_label.items()},
            task_success_by_label={
                label: all(t.task_success for t in lst) for label, lst in by_label.items()
            },
        )

    overall = {
        baseline_label: _aggregate_trials(
            [t for t in load_result.trials if t.agent_label == baseline_label], baseline_label
        ),
        candidate_label: _aggregate_trials(
            [t for t in load_result.trials if t.agent_label == candidate_label], candidate_label
        ),
    }

    by_difficulty: dict[str, dict[str, VersionMetrics]] = {}
    difficulties = {t.difficulty for t in load_result.trials if t.difficulty}
    for diff_label in difficulties:
        by_difficulty[diff_label] = {
            baseline_label: _aggregate_trials(
                [t for t in load_result.trials if t.agent_label == baseline_label and t.difficulty == diff_label],
                baseline_label,
            ),
            candidate_label: _aggregate_trials(
                [t for t in load_result.trials if t.agent_label == candidate_label and t.difficulty == diff_label],
                candidate_label,
            ),
        }

    return AggregateResult(
        overall=overall,
        by_testcase=by_testcase,
        by_difficulty=by_difficulty,
        labels=(baseline_label, candidate_label),
    )
