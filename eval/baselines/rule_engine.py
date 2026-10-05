from __future__ import annotations

from datetime import datetime

from eval.models import FindingPrediction, HandlerResult, HandoffPrediction, VisibleContext
from packages.contracts import ClinicalEvent, EventType, FindingType


class RuleEngine:
    """Finite synthetic-record rules. Absence is evaluated only at handoff.

    A missing intermediate record can be identified even if a later stage exists.
    Rules never import generation annotations or injection labels.
    """

    provider_kind = "rules"
    limitations = [
        "Finite rules for structured synthetic workflow records; not clinical validation.",
        "Checks gaps at HANDOFF_STARTED after the documented deadline; no timer events.",
    ]

    def __init__(self):
        self.states = {}

    def handle_event(self, event: ClinicalEvent, context: VisibleContext) -> HandlerResult:
        if event.event_type != EventType.HANDOFF_STARTED:
            return HandlerResult()
        records = {}
        for record in context.events:
            records.setdefault(record.payload.get("item_id"), {})[record.payload.get("stage")] = (
                record
            )
        findings, items, refs = [], [], []
        handoff_items = set(event.payload.get("item_ids", []))
        for item, stages in records.items():
            plan = stages.get("PLAN")
            if not plan or not plan.payload.get("handoff_required"):
                continue
            items.append(item)
            refs.append(plan.payload_ref)
            deadline = datetime.fromisoformat(plan.payload["deadline"])
            if deadline > context.as_of:
                continue
            tests = [
                (FindingType.PLAN_WITHOUT_ORDER, "ORDER" not in stages, "PLAN"),
                (
                    FindingType.ORDER_WITHOUT_EXECUTION,
                    "ORDER" in stages and "EXECUTION" not in stages,
                    "ORDER",
                ),
                (
                    FindingType.RESULT_WITHOUT_ACKNOWLEDGEMENT,
                    "RESULT" in stages and not stages.get("RESPONSE"),
                    "RESULT",
                ),
                (
                    FindingType.LOOP_MISSING_FROM_HANDOFF,
                    item not in handoff_items,
                    "RESPONSE" if "RESPONSE" in stages else "PLAN",
                ),
            ]
            for kind, missing, supporting in tests:
                if missing:
                    findings.append(
                        FindingPrediction(
                            patient_id=event.patient_id,
                            item_id=item,
                            finding_type=kind,
                            evidence_ids=[stages[supporting].payload_ref],
                            detected_at=context.as_of,
                            claim=f"{kind.value}: target record not found in searched synthetic records.",
                            searched_sources=[
                                "NOTES",
                                "ORDERS",
                                "LABS",
                                "PROGRESS_NOTES",
                                "HANDOFF",
                            ],
                        )
                    )
            self.states[item] = (
                "PENDING_REVIEW"
                if any(f.item_id == item for f in findings)
                else "ACKNOWLEDGED_PENDING_FOLLOWUP"
            )
        return HandlerResult(
            findings=findings,
            handoff=HandoffPrediction(
                patient_id=event.patient_id,
                item_ids=sorted(items),
                evidence_ids=sorted(refs),
                generated_at=context.as_of,
            ),
        )

    def final_states(self):
        return {"evaluated_items": self.states}
