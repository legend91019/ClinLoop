"""Encounter ownership for findings whose public contract has no encounter field."""

from sqlalchemy.orm import Session

from apps.api.app.db_models import AgentRunRow, ClinicalIntentRow, OpenLoopRow
from apps.api.app.repositories import ClinicalEventRepository, EvidenceRepository
from apps.api.app.services.evidence_source_service import evidence_encounter_id
from packages.contracts import Finding


def finding_encounter_id(session: Session, finding: Finding) -> str | None:
    anchors = set()
    for model, identity in (
        (OpenLoopRow, finding.loop_id),
        (ClinicalIntentRow, finding.intent_id),
    ):
        if identity is not None:
            row = session.get(model, identity)
            if row is None or row.patient_id != finding.patient_id:
                return None
            anchors.add(row.encounter_id)
    if anchors:
        return next(iter(anchors)) if len(anchors) == 1 else None

    if finding.source_run_id is not None:
        run = session.get(AgentRunRow, finding.source_run_id)
        event = ClinicalEventRepository(session).get(run.trigger_event_id) if run else None
        if event is None or event.patient_id != finding.patient_id:
            return None
        anchors.add(event.encounter_id)
    for evidence_id in finding.supporting_evidence:
        node = EvidenceRepository(session).get(evidence_id)
        if node is None or node.patient_id != finding.patient_id:
            return None
        encounter_id = evidence_encounter_id(session, node)
        if encounter_id is None:
            return None
        anchors.add(encounter_id)
    return next(iter(anchors)) if len(anchors) == 1 else None
