"""Bounded outputs and clinician decisions for the care assistant."""

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from packages.contracts.models import StrictModel


class CareRequest(StrictModel):
    encounter_id: str = Field(min_length=1, max_length=64)
    mode: Literal["PREPARE", "QUALITY", "PLAN"]
    document_id: str | None = Field(default=None, max_length=64)
    clarification: str = Field(default="", max_length=2000)


class CareFinding(StrictModel):
    category: Literal["CHANGE", "GAP", "CONFLICT", "OMISSION", "UNSUPPORTED", "QUESTION"]
    text: str = Field(min_length=1, max_length=1200)
    source_ids: list[str] = Field(min_length=1, max_length=10)


class CareTask(StrictModel):
    key: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,32}$")
    goal: str = Field(min_length=1, max_length=500)
    source_quote: str = Field(min_length=2, max_length=1000)
    source_ids: list[str] = Field(min_length=1, max_length=10)
    depends_on: list[str] = Field(default_factory=list, max_length=10)
    condition: Literal["NONE", "RESULT", "CLARIFY"] = "NONE"
    panel: Literal[
        "",
        "blood_culture_result",
        "susceptibility_result",
        "blood_count_result",
        "renal_function_result",
    ] = ""
    question: str = Field(default="", max_length=500)
    due_at: AwareDatetime | None = None
    existing_loop_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def valid_condition(self):
        if self.condition == "RESULT" and not self.panel:
            raise ValueError("结果条件必须指定检查项目")
        if self.condition == "CLARIFY" and not self.question.strip():
            raise ValueError("待澄清任务必须提供问题")
        return self


class CareOutput(StrictModel):
    summary: str = Field(min_length=1, max_length=2000)
    findings: list[CareFinding] = Field(default_factory=list, max_length=20)
    tasks: list[CareTask] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def graph(self):
        keys = [task.key for task in self.tasks]
        if len(set(keys)) != len(keys):
            raise ValueError("任务标识重复")
        done = set()
        for _ in self.tasks:
            for task in self.tasks:
                if set(task.depends_on) <= done:
                    done.add(task.key)
        if done != set(keys):
            raise ValueError("任务依赖存在循环或缺失")
        return self


class CareDecision(StrictModel):
    revision: int = Field(ge=1)
    action: Literal["ACCEPT", "UPDATE", "RESOLVE", "DISMISS"]
    item_key: str = Field(default="", max_length=32)
    reason: str = Field(min_length=1, max_length=2000)
    tasks: list[CareTask] | None = Field(default=None, max_length=10)
