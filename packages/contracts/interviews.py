"""Immutable consultation transcripts and source-grounded note generation."""

from typing import Literal

from pydantic import Field

from packages.contracts.models import StrictModel
from packages.contracts.workspace import DocumentKind


class InterviewCreate(StrictModel):
    encounter_id: str = Field(min_length=1, max_length=64)
    request_id: str = Field(min_length=1, max_length=48, pattern=r"^[A-Za-z0-9-]+$")
    transcript: str = Field(min_length=5, max_length=25000)
    kind: DocumentKind = "ADMISSION"
    draft_mode: Literal["CLINICAL", "DEMO"] = "CLINICAL"


class InterviewRedraft(StrictModel):
    request_id: str = Field(min_length=1, max_length=48, pattern=r"^[A-Za-z0-9-]+$")
    draft_mode: Literal["CLINICAL", "DEMO"] = "CLINICAL"


class ClinicalSentence(StrictModel):
    text: str = Field(min_length=1, max_length=4000)
    source_ids: list[str] = Field(min_length=1, max_length=20)


class ClinicalSection(StrictModel):
    heading: str = Field(min_length=1, max_length=40)
    sentences: list[ClinicalSentence] = Field(max_length=30)


class ClinicalNoteDraft(StrictModel):
    sections: list[ClinicalSection] = Field(min_length=1, max_length=16)
    missing_information: list[str] = Field(default_factory=list, max_length=20)
    conflicts: list[ClinicalSentence] = Field(default_factory=list, max_length=20)
