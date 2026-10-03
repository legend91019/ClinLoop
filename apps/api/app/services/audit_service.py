from __future__ import annotations

from apps.api.app.repositories import AuditRepository


def patient_audit(session, patient_id: str):
    return AuditRepository(session).list_for_patient(patient_id)
