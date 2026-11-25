from fastapi import APIRouter
from sqlalchemy import select

from apps.api.app.db_models import CareAssistanceRow
from apps.api.app.dependencies import SessionDep
from apps.api.app.routes.patient_workspace import WorkspaceActor
from apps.api.app.services import care_assistance_service as service
from packages.contracts.care_assistance import CareDecision, CareRequest

router = APIRouter(tags=["care assistance"])


@router.get("/patients/{patient_id}/round-preparation")
def preparation(patient_id: str, encounter_id: str, session: SessionDep):
    bundle = service.evidence_tools(session, patient_id, encounter_id)
    notes = [
        d for d in bundle["read_documents"] if d["kind"] == "ROUND" and d["status"] == "SUBMITTED"
    ]
    latest = max(notes, key=lambda d: d["time"], default=None)
    return {
        "last_round_at": bundle["profile"][0]["last_round_at"],
        "new_labs": [e for e in bundle["read_labs"] if e["since_last_round"]],
        "open_tasks": [
            t for t in bundle["read_tasks"] if t["state"] not in {"RESOLVED", "CANCELLED"}
        ],
        "last_round": latest,
        "limits": bundle["limits"],
    }


@router.get("/patients/{patient_id}/care-assistance")
def listing(patient_id: str, encounter_id: str, session: SessionDep):
    bundle = service.evidence_tools(session, patient_id, encounter_id)
    rows = session.scalars(
        select(CareAssistanceRow)
        .where(
            CareAssistanceRow.patient_id == patient_id,
            CareAssistanceRow.encounter_id == encounter_id,
        )
        .order_by(CareAssistanceRow.created_at.desc())
        .limit(30)
    ).all()
    digest = service.fingerprint(bundle)
    return [service.response(session, row, digest) for row in rows]


@router.post("/patients/{patient_id}/care-assistance", status_code=202)
def request(patient_id: str, body: CareRequest, session: SessionDep, actor: WorkspaceActor):
    result = service.request(session, patient_id, body, actor)
    session.commit()
    return result


@router.post("/patients/{patient_id}/care-assistance/{run_id}/decision")
def decide(
    patient_id: str, run_id: str, body: CareDecision, session: SessionDep, actor: WorkspaceActor
):
    result = service.decide(session, patient_id, run_id, body, actor)
    session.commit()
    return result
