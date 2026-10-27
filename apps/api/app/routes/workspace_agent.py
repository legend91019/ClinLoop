from fastapi import APIRouter

from apps.api.app.dependencies import SessionDep
from apps.api.app.routes.patient_workspace import WorkspaceActor
from apps.api.app.services import workspace_agent_service as service
from packages.contracts.workspace_agent import CandidateReview, LabInput, ResultAcknowledgement

router = APIRouter(tags=["patient agent"])


@router.get("/patients/{patient_id}/agent-workspace")
def workspace(patient_id: str, encounter_id: str, session: SessionDep):
    return service.snapshot(session, patient_id, encounter_id)


@router.post("/patients/{patient_id}/documents/{document_id}/analyze")
def analyze(patient_id: str, document_id: str, session: SessionDep, actor: WorkspaceActor):
    result = service.request_analysis(session, patient_id, document_id, actor)
    session.commit()
    return result


@router.post("/patients/{patient_id}/documents/{document_id}/candidates/{candidate_id}/review")
def review(
    patient_id: str,
    document_id: str,
    candidate_id: str,
    body: CandidateReview,
    session: SessionDep,
    actor: WorkspaceActor,
):
    result = service.review_candidate(session, patient_id, document_id, candidate_id, body, actor)
    session.commit()
    return result


@router.post("/patients/{patient_id}/agent-labs", status_code=202)
def lab(patient_id: str, body: LabInput, session: SessionDep, actor: WorkspaceActor):
    event_id = service.add_lab(session, patient_id, body, actor)
    session.commit()
    return {"event_id": event_id, "accepted": True}


@router.post("/patients/{patient_id}/agent-tasks/{loop_id}/acknowledge", status_code=202)
def acknowledge(
    patient_id: str,
    loop_id: str,
    body: ResultAcknowledgement,
    session: SessionDep,
    actor: WorkspaceActor,
):
    event_id = service.acknowledge_result(session, patient_id, loop_id, body, actor)
    session.commit()
    return {"event_id": event_id, "accepted": True}
