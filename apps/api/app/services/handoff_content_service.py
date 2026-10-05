"""Current encounter facts used to derive handoff links and review-labelled collections."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from apps.api.app.repositories import EvidenceRepository, FindingRepository, LoopRepository
from apps.api.app.services.evidence_source_service import evidence_encounter_id
from apps.api.app.services.finding_scope_service import finding_encounter_id


@dataclass(frozen=True)
class HandoffContent:
    loop_ids: list[str]
    evidence_ids: list[str]
    pending_items: list[str]
    confirmed_items: list[str]
    loop_goals: list[str]
    requires_review: bool

    def protected_fields(self) -> dict[str, list[str]]:
        return {
            "loop_ids": self.loop_ids,
            "evidence_ids": self.evidence_ids,
            "pending_items": self.pending_items,
            "confirmed_items": self.confirmed_items,
        }


def derive_handoff_content(session: Session, patient_id: str, encounter_id: str) -> HandoffContent:
    loops = [
        loop
        for loop in LoopRepository(session).list_high_priority_open(patient_id)
        if loop.encounter_id == encounter_id
    ]
    confirmed = [
        node
        for node in EvidenceRepository(session).list_for_patient(patient_id)
        if evidence_encounter_id(session, node) == encounter_id
        and node.trust_level.value in {"SYSTEM_VERIFIED", "CLINICIAN_CONFIRMED"}
    ]
    pending = []
    requires_review = False
    for finding in FindingRepository(session).list_for_patient(patient_id):
        if finding.review_status != "PENDING_REVIEW":
            continue
        scope = finding_encounter_id(session, finding)
        if scope == encounter_id:
            pending.append(finding)
        # Unknown ownership must not weaken the old patient-wide high-risk review guard.
        if scope in {None, encounter_id} and finding.requires_review:
            requires_review = True
    return HandoffContent(
        loop_ids=[loop.loop_id for loop in loops],
        evidence_ids=[node.evidence_id for node in confirmed],
        loop_goals=[loop.goal for loop in loops],
        pending_items=[
            *[loop.goal for loop in loops],
            *[f"[PENDING_REVIEW] {finding.claim}" for finding in pending],
        ],
        # Accepting a finding acknowledges a workflow gap; it is never a clinical fact.
        confirmed_items=[node.claim for node in confirmed],
        requires_review=requires_review,
    )
