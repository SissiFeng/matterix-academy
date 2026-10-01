"""Learner-owned design briefs, kept separate from executable robot sessions."""

import json
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from .models import StrictModel

WorkflowId = Literal["clio", "ada", "sonication", "rainbow", "mobile", "alab"]
MethodId = Literal["blend", "dilute", "sequence", "mix", "incubate", "wash", "deposit", "powder"]


class DesignBrief(StrictModel):
    id: UUID
    title: str = Field(min_length=1, max_length=100)
    source_id: WorkflowId | None = None
    objective: str = Field(min_length=1, max_length=600)
    variables: str = Field(min_length=1, max_length=600)
    measurement: str = Field(min_length=1, max_length=600)
    decision: str = Field(min_length=1, max_length=600)
    controls: str = Field(min_length=1, max_length=600)
    methods: list[MethodId] = Field(min_length=1, max_length=8)
    gantry: Literal["liquid", "handoff", "scan", "tool"] = "liquid"
    status: Literal["design_only"] = "design_only"

    @model_validator(mode="after")
    def meaningful_brief(self):
        if any(
            not getattr(self, name).strip()
            for name in ("title", "objective", "variables", "measurement", "decision", "controls")
        ):
            raise ValueError("Describe every part of the experiment before saving")
        if len(set(self.methods)) != len(self.methods):
            raise ValueError("Each preparation method can appear once in the design palette")
        return self


class NotebookUpdate(StrictModel):
    expected_version: int = Field(ge=0, strict=True)
    briefs: list[DesignBrief] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({brief.id for brief in self.briefs}) != len(self.briefs):
            raise ValueError("Design identifiers must be unique")
        if len(json.dumps(self.model_dump(mode="json")).encode("utf-8")) > 300_000:
            raise ValueError("Notebook content exceeds the storage limit; shorten the design text")
        return self
