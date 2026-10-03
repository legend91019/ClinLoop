from __future__ import annotations

from typing import Any
from apps.api.app.repositories import ClinicalEventRepository, EvidenceRepository, PatientRepository
from apps.mcp_server.mcp_server.tools import PatientNotFound


class RepositoryTools:
    def __init__(self, session) -> None:
        self.session = session

    def _check(self, patient_id: str) -> None:
        if not PatientRepository(self.session).exists(patient_id):
            raise PatientNotFound(patient_id)

    def get_patient_snapshot(self, *, patient_id: str) -> dict[str, Any]:
        self._check(patient_id)
        return {"patient_id": patient_id}

    def get_recent_events(self, *, patient_id: str, hours: int = 24) -> list[dict[str, Any]]:
        self._check(patient_id)
        return [event.model_dump(mode="json") for event in ClinicalEventRepository(self.session).timeline(patient_id, hours=hours)]

    def get_patient_evidence(self, *, patient_id: str) -> list[dict[str, Any]]:
        self._check(patient_id)
        return [node.model_dump(mode="json") for node in EvidenceRepository(self.session).list_for_patient(patient_id)]

    def get_orders(self, **kwargs): return []
    def get_labs(self, **kwargs): return []
    def get_consults(self, **kwargs): return []
    def get_progress_notes(self, **kwargs): return []
    def get_handoff(self, **kwargs): return None

    def record_review_decision(self, **kwargs):
        from apps.api.app.services.review_service import review_finding
        from packages.contracts import ActorRef, ReviewAction
        return review_finding(self.session, kwargs["finding_id"], ReviewAction(kwargs["action"]), ActorRef(actor_id=kwargs.get("reviewer_id", "MCP"), role="PHYSICIAN"), kwargs.get("reason"))

    def seal_handoff_report(self, **kwargs):
        from apps.api.app.services.handoff_service import seal_handoff
        from packages.contracts import ActorRef
        return seal_handoff(self.session, kwargs["handoff_id"], ActorRef(actor_id=kwargs.get("reviewer_id", "MCP"), role="PHYSICIAN"))
