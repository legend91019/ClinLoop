"""Restricted doctor-console write contract; clinical links remain immutable."""

from pydantic import Field, model_validator

from packages.contracts.models import StrictModel


class HandoffDraftUpdate(StrictModel):
    situation: str = Field(default="", max_length=20000)
    background: str = Field(default="", max_length=20000)
    assessment: str = Field(default="", max_length=20000)
    recommendation: str = Field(default="", max_length=20000)

    @model_validator(mode="after")
    def require_changes(self):
        if not self.model_fields_set:
            raise ValueError("provide at least one draft text field")
        return self
