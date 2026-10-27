"""Patient workspace contracts; all data in this prototype is synthetic."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from packages.contracts.models import StrictModel

ShortText = Annotated[str, Field(min_length=1, max_length=200)]
DocumentKind = Literal["ADMISSION", "ROUND", "PROGRESS"]
Priority = Literal["LOW", "NORMAL", "HIGH", "CRITICAL"]


class PatientCreate(StrictModel):
    display_name: ShortText
    sex: Literal["男", "女", "未说明"] = "未说明"
    age: int = Field(default=40, ge=0, le=120)
    ethnicity: str = Field(default="未记录", max_length=64)
    marital_status: Literal["未记录", "未婚", "已婚", "离异", "丧偶", "其他"] = "未记录"
    birthplace: str = Field(default="未记录", max_length=200)
    occupation: str = Field(default="未记录", max_length=200)
    admitted_at: AwareDatetime | None = None
    ward: ShortText = "模拟病区"
    bed: str = Field(default="", max_length=32)
    chief_complaint: str = Field(default="", max_length=2000)
    history: str = Field(default="", max_length=5000)
    allergies: str = Field(default="未记录", max_length=1000)


class PatientSummary(PatientCreate):
    patient_id: str
    encounter_id: str
    admitted_at: datetime | None
    synthetic: bool
    open_tasks: int


class DocumentCreate(StrictModel):
    encounter_id: ShortText
    kind: DocumentKind
    title: ShortText
    content: str = Field(min_length=1, max_length=30000)


class DocumentEdit(StrictModel):
    revision: int = Field(ge=1)
    title: ShortText
    content: str = Field(min_length=1, max_length=30000)


class DocumentSubmit(StrictModel):
    revision: int = Field(ge=1)
    signature_name: str | None = Field(default=None, min_length=1, max_length=128)
    confirmed: bool = False


class DocumentResponse(DocumentCreate):
    document_id: str
    patient_id: str
    status: str
    revision: int
    author_id: str
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime | None
    event_id: str | None
    generation: dict | None = None
    signature: dict | None = None


class TaskCreate(StrictModel):
    encounter_id: ShortText
    goal: str = Field(min_length=1, max_length=2000)
    priority: Priority = "NORMAL"
    owner: str = Field(min_length=1, max_length=64)
    due_at: AwareDatetime | None = None
    source_document_id: str | None = None


class TaskUpdate(StrictModel):
    expected_state: str
    state: Literal["IN_PROGRESS", "RESOLVED", "CANCELLED"]
    reason: str = Field(min_length=1, max_length=2000)


class TaskHistory(StrictModel):
    action: str
    actor_id: str
    reason: str | None
    created_at: datetime


class TaskResponse(StrictModel):
    loop_id: str
    patient_id: str
    encounter_id: str
    goal: str
    state: str
    priority: str
    owner: str | None
    due_at: datetime | None
    source_document_id: str | None
    system_managed: bool = False
    history: list[TaskHistory]
