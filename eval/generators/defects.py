from __future__ import annotations

import random

from eval.generators.cases import validate_integer
from eval.models import GAP_TYPES, ExpectedGap, SyntheticCase
from packages.contracts import FindingType


def inject_defect(case: SyntheticCase, defect_type: FindingType, seed: int) -> SyntheticCase:
    validate_integer(seed, "seed")
    try:
        defect_type = FindingType(defect_type)
    except (ValueError, TypeError) as exc:
        raise ValueError("unsupported defect type") from exc
    if defect_type not in GAP_TYPES:
        raise ValueError("unsupported defect type")
    if case.annotation.defect_type or case.annotation.gaps:
        raise ValueError("inject into a normal case only")
    eligible = case.annotation.eligible_handoff_items
    if not eligible:
        raise ValueError("no eligible workflow item to perturb")
    item = random.Random(seed).choice(sorted(eligible))
    removed_stage = {
        FindingType.PLAN_WITHOUT_ORDER: "ORDER",
        FindingType.ORDER_WITHOUT_EXECUTION: "EXECUTION",
        FindingType.RESULT_WITHOUT_ACKNOWLEDGEMENT: "RESPONSE",
    }.get(defect_type)
    broken = case.model_copy(deep=True)
    if removed_stage:
        removed = [
            e
            for e in broken.events
            if e.payload.get("item_id") == item and e.payload.get("stage") == removed_stage
        ]
        if not removed:
            raise ValueError("required stage is absent")
        removed_ids = {e.event_id for e in removed}
        broken.events = [e for e in broken.events if e.event_id not in removed_ids]
        broken.evidence = [
            e for e in broken.evidence if e.provenance.get("event_id") not in removed_ids
        ]
    else:
        handoffs = [
            e
            for e in broken.events
            if e.payload.get("stage") == "HANDOFF" and item in e.payload.get("item_ids", [])
        ]
        if not handoffs:
            raise ValueError("item was not present in any handoff")
        for event in handoffs:
            event.payload["item_ids"] = [i for i in event.payload["item_ids"] if i != item]
    supporting_stage = {
        FindingType.PLAN_WITHOUT_ORDER: "PLAN",
        FindingType.ORDER_WITHOUT_EXECUTION: "ORDER",
        FindingType.RESULT_WITHOUT_ACKNOWLEDGEMENT: "RESULT",
        FindingType.LOOP_MISSING_FROM_HANDOFF: "RESPONSE",
    }[defect_type]
    refs = [
        n.evidence_id
        for n in broken.evidence
        if n.provenance.get("item_id") == item and n.provenance.get("stage") == supporting_stage
    ]
    if not refs:
        raise ValueError("defect has no attributable supporting evidence")
    broken.annotation.defect_type = defect_type
    broken.annotation.gaps = [
        ExpectedGap(item_id=item, finding_type=defect_type, evidence_ids=refs)
    ]
    return broken
