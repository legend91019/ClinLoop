from fastapi import APIRouter

from apps.api.app.dependencies import SessionDep
from apps.api.app.routes.patient_workspace import WorkspaceActor
from apps.api.app.services import interview_service as service
from packages.contracts.interviews import InterviewCreate, InterviewRedraft

router = APIRouter(tags=["consultation transcription"])


@router.get("/clinical-writing/config")
def writing_config():
    from apps.api.app.settings import get_settings
    from apps.worker.worker.clinical_writing import writing_config

    return writing_config(get_settings())


@router.get("/patients/{patient_id}/first-round")
def first_round(patient_id: str, encounter_id: str, session: SessionDep):
    from apps.api.app.services.round_reminder_service import round_status

    return round_status(session, patient_id, encounter_id)


@router.get("/patients/{patient_id}/interviews")
def interviews(patient_id: str, encounter_id: str, session: SessionDep):
    return service.list_interviews(session, patient_id, encounter_id)


@router.post("/patients/{patient_id}/interviews", status_code=202)
def save(patient_id: str, body: InterviewCreate, session: SessionDep, actor: WorkspaceActor):
    result = service.save_interview(session, patient_id, body, actor)
    session.commit()
    return result


@router.post("/patients/{patient_id}/interviews/{interview_id}/retry", status_code=202)
def retry(patient_id: str, interview_id: str, session: SessionDep, actor: WorkspaceActor):
    result = service.retry_generation(session, patient_id, interview_id, actor)
    session.commit()
    return result


@router.post("/patients/{patient_id}/interviews/{interview_id}/draft", status_code=202)
def redraft(
    patient_id: str,
    interview_id: str,
    body: InterviewRedraft,
    session: SessionDep,
    actor: WorkspaceActor,
):
    result = service.redraft(session, patient_id, interview_id, body, actor)
    session.commit()
    return result
