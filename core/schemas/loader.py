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

    paired_trials, unpaired = _pair(good_trials, baseline.label, candidate.label)
    paired_ids = {t.testcase_id for t in paired_trials}
    paired_traces: list[TraceStep] | None = (
        [t for t in good_traces if t.testcase_id in paired_ids] if raw_traces else None
    )

    warnings: list[str] = []
    if unpaired:
        warnings.append(
            f"{len(unpaired)}개 testcase가 baseline/candidate 한쪽에만 있어 비교에서 제외됨: {sorted(unpaired)}"
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


def _pair(trials: list[TrialResult], baseline_label: str, candidate_label: str) -> tuple[list[TrialResult], set[str]]:
    labels_by_case: dict[str, set[str]] = {}
    for t in trials:
        labels_by_case.setdefault(t.testcase_id, set()).add(t.agent_label)

    required = {baseline_label, candidate_label}
    unpaired = {tc for tc, labels in labels_by_case.items() if not required <= labels}
    paired = [t for t in trials if t.testcase_id not in unpaired]
    return paired, unpaired


def _trial_counts(trials: list[TrialResult]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for t in trials:
        key = (t.testcase_id, t.agent_label)
        counts[key] = counts.get(key, 0) + 1
    return counts
