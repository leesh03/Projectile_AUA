"""L1 — Loader & Validator.

AuditBundle을 관대하게 파싱한다: trial/trace 레코드 1건이 깨져도 전체를 죽이지 않는다.
"필수 필드 누락 → 해당 레코드만 SKIPPED, 나머지는 정상 진행" (docs/CONTRACT.md §6)을 구현하는 곳.

bundle_id / suite / baseline / candidate 자체가 깨진 경우는 복구 대상이 아니다 —
그건 애초에 "무엇을 무엇과 비교하는지"조차 알 수 없는 경우라 ContractViolation을 던진다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from core.schemas.agent_version import AgentVersion
from core.schemas.bundle import SuiteInfo
from core.schemas.trace import TraceStep
from core.schemas.trial import TrialResult


class ContractViolation(Exception):
    """구조적으로 복구 불가능한 위반. bundle_id/suite/baseline/candidate가 깨진 경우 여기서 멈춘다."""


@dataclass
class SkippedRecord:
    kind: Literal["trial", "trace"]
    index: int
    testcase_id: str | None
    agent_label: str | None
    reason: str


@dataclass
class LoadResult:
    bundle_id: str
    created_at: str
    suite: SuiteInfo
    baseline: AgentVersion
    candidate: AgentVersion
    change_note: str | None
    trials: list[TrialResult]  # 페어링됐고 파싱에 성공한 trial만
    traces: list[TraceStep] | None  # 위와 같은 기준. traces 자체가 없었으면 None
    unpaired_testcases: list[str]
    unpaired_trials: list[str] = field(default_factory=list)
    skipped_trials: list[SkippedRecord] = field(default_factory=list)
    skipped_traces: list[SkippedRecord] = field(default_factory=list)
    low_confidence: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def testcase_count(self) -> int:
        return len({t.testcase_id for t in self.trials})


def load_bundle(raw: dict[str, Any] | str | Path) -> LoadResult:
    """dict, JSON 문자열, 파일 경로(str/Path) 중 무엇을 넘겨도 동작한다."""
    data = _read_raw(raw)

    try:
        bundle_id = data["bundle_id"]
        created_at = data["created_at"]
        suite = SuiteInfo.model_validate(data["suite"])
        baseline = AgentVersion.model_validate(data["baseline"])
        candidate = AgentVersion.model_validate(data["candidate"])
    except (KeyError, ValidationError) as exc:
        raise ContractViolation(f"AuditBundle 최상위 구조가 깨졌습니다: {exc}") from exc

    if baseline.label == candidate.label:
        raise ContractViolation(f"baseline.label과 candidate.label이 같습니다: {baseline.label!r}")

    change_note = data.get("change_note")
    allowed_labels = {baseline.label, candidate.label}

    good_trials, skipped_trials = _parse_records(
        data.get("trials") or [], TrialResult, kind="trial", allowed_labels=allowed_labels
    )
    raw_traces = data.get("traces")
    if raw_traces:
        good_traces, skipped_traces = _parse_records(
            raw_traces, TraceStep, kind="trace", allowed_labels=allowed_labels
        )
    else:
        good_traces, skipped_traces = [], []

    good_trials, duplicate_trials = _dedupe_trials(good_trials)
    skipped_trials.extend(duplicate_trials)
    paired_trials, unpaired, unpaired_trial_keys = _pair(
        good_trials,
        baseline.label,
        candidate.label,
    )
    paired_traces, invalid_traces = _filter_traces(good_traces, paired_trials)
    skipped_traces.extend(invalid_traces)
    if not raw_traces:
        paired_traces = None

    warnings: list[str] = []
    if unpaired:
        warnings.append(
            f"{len(unpaired)}개 testcase가 baseline/candidate 한쪽에만 있어 비교에서 제외됨: {sorted(unpaired)}"
        )
    if unpaired_trial_keys:
        warnings.append(
            f"{len(unpaired_trial_keys)}개 (testcase_id, trial)이 한쪽 버전에만 있어 비교에서 제외됨"
        )
    if skipped_trials:
        warnings.append(f"trial {len(skipped_trials)}건이 필수 필드 누락/계약 위반으로 제외됨")
    if skipped_traces:
        warnings.append(f"trace {len(skipped_traces)}건이 필수 필드 누락/계약 위반으로 제외됨")

    trial_counts = _trial_counts(paired_trials)
    low_confidence = bool(trial_counts) and min(trial_counts.values()) < 2

    return LoadResult(
        bundle_id=bundle_id,
        created_at=created_at,
        suite=suite,
        baseline=baseline,
        candidate=candidate,
        change_note=change_note,
        trials=paired_trials,
        traces=paired_traces,
        unpaired_testcases=sorted(unpaired),
        unpaired_trials=[f"{testcase_id}:trial-{trial}" for testcase_id, trial in sorted(unpaired_trial_keys)],
        skipped_trials=skipped_trials,
        skipped_traces=skipped_traces,
        low_confidence=low_confidence,
        warnings=warnings,
    )


def _read_raw(raw: dict[str, Any] | str | Path) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, Path):
        return json.loads(raw.read_text(encoding="utf-8"))
    if isinstance(raw, str):
        as_path = Path(raw)
        if as_path.exists():
            return json.loads(as_path.read_text(encoding="utf-8"))
        return json.loads(raw)  # JSON 텍스트 그대로 넘어온 경우 (Timely AI 붙여넣기 입력, P8)
    raise TypeError(f"load_bundle이 지원하지 않는 입력 타입입니다: {type(raw)!r}")


def _parse_records(
    items: list[Any],
    model_cls: type[TrialResult | TraceStep],
    *,
    kind: Literal["trial", "trace"],
    allowed_labels: set[str],
) -> tuple[list[Any], list[SkippedRecord]]:
    good: list[Any] = []
    skipped: list[SkippedRecord] = []
    for i, item in enumerate(items):
        tc_hint = item.get("testcase_id") if isinstance(item, dict) else None
        label_hint = item.get("agent_label") if isinstance(item, dict) else None
        try:
            record = model_cls.model_validate(item)
        except ValidationError as exc:
            skipped.append(
                SkippedRecord(
                    kind=kind, index=i, testcase_id=tc_hint, agent_label=label_hint,
                    reason=_summarize_error(exc),
                )
            )
            continue
        if record.agent_label not in allowed_labels:
            skipped.append(
                SkippedRecord(
                    kind=kind, index=i, testcase_id=record.testcase_id, agent_label=record.agent_label,
                    reason=f"agent_label {record.agent_label!r}이 baseline/candidate 어느 쪽도 아님",
                )
            )
            continue
        good.append(record)
    return good, skipped


def _summarize_error(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(root)"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)


def _dedupe_trials(
    trials: list[TrialResult],
) -> tuple[list[TrialResult], list[SkippedRecord]]:
    seen: set[tuple[str, str, int]] = set()
    good: list[TrialResult] = []
    skipped: list[SkippedRecord] = []
    for trial in trials:
        key = (trial.testcase_id, trial.agent_label, trial.trial)
        if key in seen:
            skipped.append(
                SkippedRecord(
                    kind="trial",
                    index=-1,
                    testcase_id=trial.testcase_id,
                    agent_label=trial.agent_label,
                    reason=f"duplicate TrialResult key: {key}",
                )
            )
            continue
        seen.add(key)
        good.append(trial)
    return good, skipped


def _pair(
    trials: list[TrialResult],
    baseline_label: str,
    candidate_label: str,
) -> tuple[list[TrialResult], set[str], set[tuple[str, int]]]:
    labels_by_key: dict[tuple[str, int], set[str]] = {}
    for t in trials:
        labels_by_key.setdefault((t.testcase_id, t.trial), set()).add(t.agent_label)

    required = {baseline_label, candidate_label}
    unpaired_keys = {key for key, labels in labels_by_key.items() if not required <= labels}
    paired = [t for t in trials if (t.testcase_id, t.trial) not in unpaired_keys]
    paired_cases = {t.testcase_id for t in paired}
    all_cases = {t.testcase_id for t in trials}
    fully_unpaired_cases = all_cases - paired_cases
    return paired, fully_unpaired_cases, unpaired_keys


def _filter_traces(
    traces: list[TraceStep],
    trials: list[TrialResult],
) -> tuple[list[TraceStep], list[SkippedRecord]]:
    trial_keys = {(t.testcase_id, t.agent_label, t.trial) for t in trials}
    seen_steps: set[tuple[str, str, int, str | None, int]] = set()
    run_by_trial: dict[tuple[str, str, int], str | None] = {}
    good: list[TraceStep] = []
    skipped: list[SkippedRecord] = []
    for trace in traces:
        trial_number = trace.trial
        key = (trace.testcase_id, trace.agent_label, trial_number)
        reason: str | None = None
        if trial_number is None or key not in trial_keys:
            reason = "trace references no paired TrialResult"
        else:
            typed_key = (trace.testcase_id, trace.agent_label, trial_number)
            previous_run = run_by_trial.setdefault(typed_key, trace.run_id)
            if previous_run != trace.run_id:
                reason = "trace run_id differs within one TrialResult"
            step_key = (*typed_key, trace.run_id, trace.step_index)
            if reason is None and step_key in seen_steps:
                reason = f"duplicate TraceStep key: {step_key}"
            seen_steps.add(step_key)
        if reason is not None:
            skipped.append(
                SkippedRecord(
                    kind="trace",
                    index=-1,
                    testcase_id=trace.testcase_id,
                    agent_label=trace.agent_label,
                    reason=reason,
                )
            )
            continue
        good.append(trace)
    return good, skipped


def _trial_counts(trials: list[TrialResult]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for t in trials:
        key = (t.testcase_id, t.agent_label)
        counts[key] = counts.get(key, 0) + 1
    return counts
