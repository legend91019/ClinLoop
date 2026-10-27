"""Endpoints for the synthetic patient workspace."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from apps.api.app.dependencies import SessionDep
from apps.api.app.services import patient_workspace_service as service
from packages.contracts import ActorRef
from packages.contracts.workspace import (
    DocumentCreate,
    DocumentEdit,
    DocumentResponse,
    DocumentSubmit,
    PatientCreate,
    PatientSummary,
    TaskCreate,
    TaskResponse,
    TaskUpdate,
)

router = APIRouter(tags=["patient workspace"])


def workspace_actor(
    actor_id: Annotated[str | None, Header(alias="X-Actor-Id")] = None,
    role: Annotated[str | None, Header(alias="X-Actor-Role")] = None,
) -> ActorRef:
    if not actor_id or not actor_id.strip() or role not in {"PHYSICIAN", "CLINICIAN"}:
        raise HTTPException(403, "请先填写医生 ID 并选择临床角色")
    if len(actor_id.strip()) > 64:
        raise HTTPException(422, "医生 ID 不能超过 64 个字符")
    return ActorRef(actor_id=actor_id.strip(), role=role)


WorkspaceActor = Annotated[ActorRef, Depends(workspace_actor)]


@router.get("/patients", response_model=list[PatientSummary])
def patients(session: SessionDep):
    return service.list_patients(session)


@router.post("/demo/patients")
def seed_patients(session: SessionDep, actor: WorkspaceActor):
    from packages.fixtures.patient_workspace import seed_workspace_patients

    created = seed_workspace_patients(session)
    session.commit()
    return {"created": created}


@router.post("/patients", response_model=PatientSummary, status_code=201)
def create_patient(body: PatientCreate, session: SessionDep, actor: WorkspaceActor):
    patient_id = service.create_patient(session, body, actor)
    session.commit()
    return next(
        patient for patient in service.list_patients(session) if patient.patient_id == patient_id
    )


@router.get("/patients/{patient_id}/documents", response_model=list[DocumentResponse])
def documents(patient_id: str, encounter_id: str, session: SessionDep):
    return service.list_documents(session, patient_id, encounter_id)


@router.post("/patients/{patient_id}/documents", response_model=DocumentResponse, status_code=201)
def create_document(
    patient_id: str, body: DocumentCreate, session: SessionDep, actor: WorkspaceActor
):
    result = service.create_document(session, patient_id, body, actor)
    session.commit()
    return result


@router.patch("/patients/{patient_id}/documents/{document_id}", response_model=DocumentResponse)
def edit_document(
    patient_id: str,
    document_id: str,
    body: DocumentEdit,
    session: SessionDep,
    actor: WorkspaceActor,
):
    result = service.edit_document(session, patient_id, document_id, body, actor)
    session.commit()
    return result


@router.post(
    "/patients/{patient_id}/documents/{document_id}/submit", response_model=DocumentResponse
)
def submit_document(
    patient_id: str,
    document_id: str,
    body: DocumentSubmit,
    session: SessionDep,
    actor: WorkspaceActor,
):
    result = service.submit_document(
        session,
        patient_id,
        document_id,
        body.revision,
        actor,
        signature_name=body.signature_name,
        confirmed=body.confirmed,
    )
    session.commit()
    return result


@router.get("/patients/{patient_id}/tasks", response_model=list[TaskResponse])
def tasks(patient_id: str, encounter_id: str, session: SessionDep):
    return service.list_tasks(session, patient_id, encounter_id)


@router.post("/patients/{patient_id}/tasks", response_model=TaskResponse, status_code=201)
def create_task(patient_id: str, body: TaskCreate, session: SessionDep, actor: WorkspaceActor):
    result = service.create_task(session, patient_id, body, actor)
    session.commit()
    return result


@router.patch("/patients/{patient_id}/tasks/{loop_id}", response_model=TaskResponse)
def update_task(
    patient_id: str, loop_id: str, body: TaskUpdate, session: SessionDep, actor: WorkspaceActor
):
    result = service.update_task(session, patient_id, loop_id, body, actor)
    session.commit()
    return result
