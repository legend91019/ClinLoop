from typing import Literal

from pydantic import Field, model_validator

from packages.contracts.models import StrictModel

PANELS = {
    "blood_culture_result": "血培养",
    "susceptibility_result": "药敏",
    "blood_count_result": "血常规",
    "renal_function_result": "肾功能",
}


class CandidateReview(StrictModel):
    action: Literal["ACCEPT", "REJECT"]
    reason: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def rejection_reason(self):
        if self.action == "REJECT" and not self.reason.strip():
            raise ValueError("驳回需要填写原因")
        return self


class LabInput(StrictModel):
    encounter_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1, max_length=60)
    panel: Literal[
        "blood_culture_result",
        "susceptibility_result",
        "blood_count_result",
        "renal_function_result",
    ]
    result: str = Field(min_length=1, max_length=5000)


class ResultAcknowledgement(StrictModel):
    reason: str = Field(min_length=1, max_length=2000)
    next_panel: Literal["susceptibility_result"] | None = None
