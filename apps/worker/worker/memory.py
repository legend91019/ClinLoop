from __future__ import annotations

from dataclasses import dataclass, field
from packages.contracts import ClinicalEvent, ClinicalIntent, EvidenceNode, OpenLoop


@dataclass
class WorkflowContext:
    patient_id: str
    loop_id: str | None
    snapshot: dict = field(default_factory=dict)
    intents: list[ClinicalIntent] = field(default_factory=list)
    loops: list[OpenLoop] = field(default_factory=list)
    recent_events: list[ClinicalEvent] = field(default_factory=list)
    evidence: list[EvidenceNode] = field(default_factory=list)
    scratchpad: dict = field(default_factory=dict)


class WorkflowMemory:
    def __init__(self) -> None:
        self.events: list[ClinicalEvent] = []
        self.intents: dict[str, ClinicalIntent] = {}
        self.loops: dict[str, OpenLoop] = {}
        self.evidence: dict[str, EvidenceNode] = {}

    def record_event(self, event: ClinicalEvent) -> None:
        if not any(item.event_id == event.event_id for item in self.events):
            self.events.append(event)

    def save_intent(self, intent: ClinicalIntent) -> None:
        self.intents[intent.intent_id] = intent

    def save_loop(self, loop: OpenLoop) -> None:
        self.loops[loop.loop_id] = loop

    def append_evidence(self, evidence: EvidenceNode) -> None:
        self.evidence[evidence.evidence_id] = evidence

    def get_context(self, patient_id: str, loop_id: str | None = None, *, recent_limit: int = 20) -> WorkflowContext:
        loops = [loop for loop in self.loops.values() if loop.patient_id == patient_id and (loop_id is None or loop.loop_id == loop_id)]
        intent_ids = {loop.intent_id for loop in loops}
        loop_ids = {loop.loop_id for loop in loops}
        return WorkflowContext(
            patient_id=patient_id,
            loop_id=loop_id,
            snapshot={"patient_id": patient_id},
            intents=[intent for intent in self.intents.values() if intent.patient_id == patient_id and intent.intent_id in intent_ids],
            loops=loops,
            recent_events=[event for event in self.events if event.patient_id == patient_id][-recent_limit:],
            evidence=[node for node in self.evidence.values() if node.patient_id == patient_id and (loop_id is None or node.provenance.get("loop_id") in loop_ids)],
        )
