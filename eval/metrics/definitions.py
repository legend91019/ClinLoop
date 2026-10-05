from __future__ import annotations

from collections.abc import Sequence

from pydantic import Field

from eval.models import CasePrediction, ReplayResult, SyntheticCase
from eval.replay.records import SOURCES
from packages.contracts import EventType, FindingType, TrustLevel
from packages.contracts.models import StrictModel


class MetricsReport(StrictModel):
    gap_recall: float = Field(ge=0, le=1)
    false_alarm_rate: float = Field(ge=0, le=1)
    evidence_coverage: float = Field(ge=0, le=1)
    finding_evidence_coverage: float = Field(ge=0, le=1)
    handoff_evidence_coverage: float = Field(ge=0, le=1)
    handoff_omission_rate: float = Field(ge=0, le=1)
    gaps: int
    true_positives: int
    normal_opportunities: int
    false_alarms: int
    predicted_findings: int
    evidence_backed_findings: int
    predicted_handoff_items: int
    evidence_backed_handoff_items: int
    unmatched_handoff_items: int
    eligible_handoff_items: int
    omitted_handoff_items: int
    unmatched_predictions: int
    temporally_invalid_predictions: int


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _key(value):
    return value.item_id, value.finding_type


def _in_time(case, finding):
    prerequisites = {
        FindingType.PLAN_WITHOUT_ORDER: ("PLAN",),
        FindingType.ORDER_WITHOUT_EXECUTION: ("ORDER",),
        FindingType.RESULT_WITHOUT_ACKNOWLEDGEMENT: ("RESULT",),
        FindingType.LOOP_MISSING_FROM_HANDOFF: ("PLAN", "HANDOFF"),
    }.get(finding.finding_type)
    if not prerequisites or finding.patient_id != case.patient_id or not case.events:
        return False
    for stage in prerequisites:
        sources = [
            e
            for e in case.events
            if e.patient_id == finding.patient_id
            and e.payload.get("stage") == stage
            and (stage == "HANDOFF" or e.payload.get("item_id") == finding.item_id)
        ]
        if not any(max(e.event_time, e.source_time) <= finding.detected_at for e in sources):
            return False
    return finding.detected_at <= max(max(e.event_time, e.source_time) for e in case.events)


def _valid_source(case, node, patient_id, item_id, when):
    event = next((e for e in case.events if e.event_id == node.provenance.get("event_id")), None)
    return not (
        event is None
        or node.patient_id != patient_id
        or event.patient_id != patient_id
        or event.encounter_id != node.encounter_id
        or event.payload_ref != node.source_id
        or node.source_type != SOURCES[event.event_type]
        or node.provenance.get("item_id") != item_id
        or event.payload.get("item_id") != item_id
        or node.provenance.get("stage") != event.payload.get("stage")
        or node.claim != event.payload.get("text")
        or node.observed_at != event.event_time
        or max(node.observed_at, node.created_at, event.event_time, event.source_time) > when
        or node.trust_level not in {TrustLevel.SYSTEM_VERIFIED, TrustLevel.CLINICIAN_CONFIRMED}
        or event.event_type == EventType.PATIENT_EVIDENCE_SUBMITTED
    )


def _backed(case, finding):
    """Require every citation to be visible, trusted and attributable to the item.

    A valid source pointer also needs its event, matching provenance, stage and
    claim. A patient's unverified submission cannot support confirmed gap facts.
    """
    if not finding.evidence_ids or finding.patient_id != case.patient_id:
        return False
    nodes = {n.evidence_id: n for n in case.evidence}
    allowed_stages = {
        FindingType.PLAN_WITHOUT_ORDER: {"PLAN"},
        FindingType.ORDER_WITHOUT_EXECUTION: {"ORDER"},
        FindingType.RESULT_WITHOUT_ACKNOWLEDGEMENT: {"RESULT"},
        FindingType.LOOP_MISSING_FROM_HANDOFF: {"PLAN", "RESPONSE"},
    }.get(finding.finding_type, set())
    for ref in set(finding.evidence_ids):
        node = nodes.get(ref)
        if node is None:
            return False
        if node.provenance.get("stage") not in allowed_stages or not _valid_source(
            case, node, finding.patient_id, finding.item_id, finding.detected_at
        ):
            return False
    return True


def _handoff_backed(case, handoff, item):
    """Resolve flat citations per item via source-record provenance.

    Nonempty citations for another item do not count. Every citation attributed
    to this item must validate; unknown references fail conservatively because
    their attribution cannot be established. The current handoff cannot serve
    as its own supporting source. No predicted text is treated as evidence.
    """
    nodes = {n.evidence_id: n for n in case.evidence}
    if not handoff.evidence_ids or handoff.patient_id != case.patient_id:
        return False
    relevant = []
    for ref in set(handoff.evidence_ids):
        node = nodes.get(ref)
        if node is None:
            return False
        event = next(
            (e for e in case.events if e.event_id == node.provenance.get("event_id")), None
        )
        if node.provenance.get("item_id") == item or (
            event and event.payload.get("item_id") == item
        ):
            relevant.append(node)
    return bool(relevant) and all(
        node.provenance.get("stage") != "HANDOFF"
        and _valid_source(case, node, handoff.patient_id, item, handoff.generated_at)
        for node in relevant
    )


def compute_metrics(
    expected: Sequence[SyntheticCase], actual: Sequence[CasePrediction | ReplayResult]
) -> MetricsReport:
    """Final-checkpoint presence metrics, micro-aggregated across opportunities.

    Matching is patient + item + finding type. Duplicate alerts cannot inflate
    recall or false alarms. A normal opportunity is an annotated non-gap edge,
    including unaffected edges of defect cases (325 for this 100-case corpus).
    Unknown items/types are counted separately, never silently discarded.
    Missing case/handoff output omits every eligible item. Extra handoff items
    cannot cancel omissions. All zero denominators have rate 0.0 and raw counts.
    """
    cases = {c.patient_id: c for c in expected}
    if len(cases) != len(expected):
        raise ValueError("duplicate expected patient")
    predictions = {}
    for result in actual:
        prediction = result.prediction if isinstance(result, ReplayResult) else result
        if prediction.patient_id in predictions:
            raise ValueError("duplicate actual patient")
        predictions[prediction.patient_id] = prediction
    counts = dict(
        gaps=0,
        true_positives=0,
        normal_opportunities=0,
        false_alarms=0,
        predicted_findings=0,
        evidence_backed_findings=0,
        predicted_handoff_items=0,
        evidence_backed_handoff_items=0,
        unmatched_handoff_items=0,
        eligible_handoff_items=0,
        omitted_handoff_items=0,
        unmatched_predictions=0,
        temporally_invalid_predictions=0,
    )
    for patient, prediction in predictions.items():
        if patient not in cases:
            count = len({_key(f) for f in prediction.findings})
            counts["unmatched_predictions"] += count
            counts["predicted_findings"] += count
            handoff_count = len(set(prediction.handoff.item_ids)) if prediction.handoff else 0
            counts["predicted_handoff_items"] += handoff_count
            counts["unmatched_handoff_items"] += handoff_count
    for patient, case in cases.items():
        opportunities = {_key(o) for o in case.annotation.opportunities}
        gaps = {_key(g) for g in case.annotation.gaps}
        if not gaps <= opportunities:
            raise ValueError("gold gaps must be eligible opportunities")
        normal = opportunities - gaps
        counts["gaps"] += len(gaps)
        counts["normal_opportunities"] += len(normal)
        prediction = predictions.get(patient)
        grouped = {}
        for finding in prediction.findings if prediction else []:
            grouped.setdefault(_key(finding), []).append(finding)
        # One alert identity is one opportunity. Evidence counts only if some
        # occurrence has a complete valid citation set at its detection time.
        valid_keys = set()
        for key, findings in grouped.items():
            counts["predicted_findings"] += 1
            in_time = [f for f in findings if _in_time(case, f)]
            if key not in opportunities:
                counts["unmatched_predictions"] += 1
            if not in_time:
                counts["temporally_invalid_predictions"] += 1
            else:
                valid_keys.add(key)
            if any(_backed(case, f) and _in_time(case, f) for f in findings):
                counts["evidence_backed_findings"] += 1
        counts["true_positives"] += len(gaps & valid_keys)
        # A future-dated false alert is still a false alert on a normal edge;
        # invalid timestamps must not improve the false alarm score.
        counts["false_alarms"] += len(normal & grouped.keys())
        eligible = set(case.annotation.eligible_handoff_items)
        included = set()
        handoff = prediction.handoff if prediction else None
        if handoff:
            counts["predicted_handoff_items"] += len(set(handoff.item_ids))
            observed_items = {e.payload.get("item_id") for e in case.events}
            counts["unmatched_handoff_items"] += len(set(handoff.item_ids) - observed_items)
        if handoff and case.events:
            cutoff = max(max(e.event_time, e.source_time) for e in case.events)
            handoff_events = [e for e in case.events if e.payload.get("stage") == "HANDOFF"]
            start = min((max(e.event_time, e.source_time) for e in handoff_events), default=cutoff)
            if start <= handoff.generated_at <= cutoff:
                included = set(handoff.item_ids)
                counts["evidence_backed_handoff_items"] += sum(
                    _handoff_backed(case, handoff, item) for item in included
                )
        counts["eligible_handoff_items"] += len(eligible)
        counts["omitted_handoff_items"] += len(eligible - included)
    return MetricsReport(
        gap_recall=_ratio(counts["true_positives"], counts["gaps"]),
        false_alarm_rate=_ratio(counts["false_alarms"], counts["normal_opportunities"]),
        evidence_coverage=_ratio(
            counts["evidence_backed_findings"] + counts["evidence_backed_handoff_items"],
            counts["predicted_findings"] + counts["predicted_handoff_items"],
        ),
        finding_evidence_coverage=_ratio(
            counts["evidence_backed_findings"], counts["predicted_findings"]
        ),
        handoff_evidence_coverage=_ratio(
            counts["evidence_backed_handoff_items"], counts["predicted_handoff_items"]
        ),
        handoff_omission_rate=_ratio(
            counts["omitted_handoff_items"], counts["eligible_handoff_items"]
        ),
        **counts,
    )
