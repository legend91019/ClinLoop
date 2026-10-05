from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from eval.models import GAP_TYPES, Annotation, Opportunity, SyntheticCase
from packages.contracts import ActorRef, ClinicalEvent, EventType, EvidenceNode, TrustLevel


def validate_integer(value: int, name: str, *, nonnegative: bool = False) -> None:
    if type(value) is not int or (nonnegative and value < 0):
        raise ValueError(f"{name} must be {'a nonnegative' if nonnegative else 'an'} integer")


def _normal_case(index: int, rng: random.Random) -> SyntheticCase:
    patient = f"SYN-P-{index:05d}"
    encounter = f"SYN-ENC-{index:05d}"
    item = f"SYN-WORK-{index:05d}"
    base = datetime(2026, 9, 28, 9, tzinfo=UTC) + timedelta(minutes=rng.randrange(30))
    deadline = base + timedelta(hours=9)
    stages = [
        ("PLAN", EventType.NOTE_CREATED, "NOTES", 0),
        ("ORDER", EventType.ORDER_UPDATED, "ORDERS", 1),
        ("EXECUTION", EventType.ORDER_UPDATED, "ORDERS", 2),
        ("RESULT", EventType.LAB_RESULT_CREATED, "LABS", 5),
        ("RESPONSE", EventType.PROGRESS_NOTE_CREATED, "PROGRESS_NOTES", 8),
        ("CONSULT", EventType.CONSULT_NOTE_CREATED, "CONSULTS", 9),
        ("PATIENT", EventType.PATIENT_EVIDENCE_SUBMITTED, "PATIENT", 10),
        ("HANDOFF", EventType.HANDOFF_STARTED, "HANDOFF", 11),
    ]
    events, evidence = [], []
    for n, (stage, kind, source, hours) in enumerate(stages):
        when = base + timedelta(hours=hours)
        ref = f"SYN-RECORD-{index:05d}-{n}"
        event_id = f"SYN-EVENT-{index:05d}-{n}"
        record_item = f"SYN-OTHER-{index:05d}" if stage in {"CONSULT", "PATIENT"} else item
        payload = {
            "stage": stage,
            "item_id": record_item,
            "text": f"Synthetic {stage.lower()} record: {rng.choice(['blood culture', 'follow-up laboratory test'])}.",
            "priority": "LOW" if record_item != item else "HIGH",
        }
        if stage == "PLAN":
            payload.update(deadline=deadline.isoformat(), handoff_required=True)
        if stage == "RESPONSE":
            payload.update(acknowledged=True, pending_followup="Await susceptibility record")
        if stage == "HANDOFF":
            payload["item_ids"] = [item]
        event = ClinicalEvent(
            event_id=event_id,
            patient_id=patient,
            encounter_id=encounter,
            event_type=kind,
            event_time=when,
            source_time=when,
            payload_ref=ref,
            actor=ActorRef(actor_id="SYN-CLINICIAN", role="CLINICIAN"),
            payload=payload,
            ingested_at=when,
        )
        events.append(event)
        evidence.append(
            EvidenceNode(
                evidence_id=ref,
                patient_id=patient,
                encounter_id=encounter,
                source_type=source,
                source_id=ref,
                observed_at=when,
                claim=payload["text"],
                provenance={"event_id": event_id, "item_id": record_item, "stage": stage},
                trust_level=TrustLevel.PATIENT_REPORTED
                if stage == "PATIENT"
                else TrustLevel.SYSTEM_VERIFIED,
                created_at=when,
            )
        )
    return SyntheticCase(
        case_id=f"SYN-CASE-{index:05d}",
        patient_id=patient,
        events=events,
        evidence=evidence,
        annotation=Annotation(
            opportunities=[Opportunity(item_id=item, finding_type=t) for t in GAP_TYPES],
            eligible_handoff_items=[item],
        ),
    )


def generate_cases(count: int, seed: int) -> list[SyntheticCase]:
    """Largest-remainder allocation: exact 25/20/20/20/15 for every 100 cases.

    A local RNG does not disturb caller random state. Neutral identifiers do
    not encode cohort labels. Smaller counts may omit some cohorts.
    """
    from eval.generators.defects import inject_defect

    validate_integer(count, "count", nonnegative=True)
    validate_integer(seed, "seed")
    weights = (25, 20, 20, 20, 15)
    sizes = [count * weight // 100 for weight in weights]
    ranked = sorted(range(5), key=lambda n: (-(count * weights[n] % 100), n))
    for n in ranked[: count - sum(sizes)]:
        sizes[n] += 1
    labels = [
        label for label, size in zip((None, *GAP_TYPES), sizes, strict=True) for _ in range(size)
    ]
    rng = random.Random(seed)
    rng.shuffle(labels)
    cases = []
    for index, label in enumerate(labels):
        case = _normal_case(index, rng)
        cases.append(inject_defect(case, label, rng.getrandbits(64)) if label else case)
    return cases
