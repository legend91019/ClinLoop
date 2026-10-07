"""Score sourced alerts against case labels held outside the Worker."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ObservedCase:
    case_id: str
    provider_kind: str
    alert_count: int
    valid_evidence_count: int
    model_errors: int
    tool_calls: int


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    expected_alert: bool
    alert_count: int
    evidence_valid: bool
    tp: int
    fp: int
    fn: int
    tn: int
    model_errors: int
    tool_calls: int


def score_case(*, expected_alert: bool, observed: ObservedCase) -> CaseScore:
    valid = observed.alert_count == 1 and observed.valid_evidence_count == 1
    tp = int(expected_alert and valid)
    fp = int(observed.alert_count > 0 and (not expected_alert or not valid))
    fn = int(expected_alert and not valid)
    tn = int(not expected_alert and observed.alert_count == 0)
    return CaseScore(
        case_id=observed.case_id,
        expected_alert=expected_alert,
        alert_count=observed.alert_count,
        evidence_valid=valid,
        tp=tp,
        fp=fp,
        fn=fn,
        tn=tn,
        model_errors=observed.model_errors,
        tool_calls=observed.tool_calls,
    )


def summarize(scores: list[CaseScore]) -> dict[str, int | float]:
    tp = sum(score.tp for score in scores)
    fp = sum(score.fp for score in scores)
    fn = sum(score.fn for score in scores)
    return {
        "cases": len(scores),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": sum(score.tn for score in scores),
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "model_errors": sum(score.model_errors for score in scores),
        "tool_calls": sum(score.tool_calls for score in scores),
    }
