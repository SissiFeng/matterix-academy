"""Versioned native recipes. These describe intent, never observed simulator state."""

import random
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, TypeAdapter, model_validator

from .models import Experiment, StrictModel

MIXING = "flex-mixing"
MIXING_TASK = "Matterix-Flex-Mixing-v1"
MIXING_WORKFLOW = "mix_four_vials"


class MixingStep(StrictModel):
    kind: Literal["uncover", "transfer"]
    source_index: int | None = Field(default=None, ge=0, le=7)
    tip_id: str | None = None
    volume_ul: Literal[10] | None = None


def mixing_steps(seed: int) -> list[MixingStep]:
    sources = random.Random(seed).sample(range(8), 4)
    return [MixingStep(kind="uncover")] + [
        MixingStep(kind="transfer", source_index=source, tip_id=f"Tips__A{i + 1}", volume_ul=10)
        for i, source in enumerate(sources)
    ]


class MixingPlan(StrictModel):
    course_id: Literal["flex-mixing"] = MIXING
    title: Literal["Four-source mixing"] = "Four-source mixing"
    recipe_version: Literal[1] = 1
    task: Literal["Matterix-Flex-Mixing-v1"] = MIXING_TASK
    workflow: Literal["mix_four_vials"] = MIXING_WORKFLOW
    seed: int = Field(default=42, ge=0, le=2**31 - 1, strict=True)
    num_envs: Literal[1] = 1
    actions: list[MixingStep] = Field(default_factory=lambda: mixing_steps(42))

    @model_validator(mode="after")
    def fixed_recipe(self):
        if self.actions != mixing_steps(self.seed):
            raise ValueError("Mixing actions must match the pinned recipe and selected seed")
        return self


ExecutionPlan = Experiment | MixingPlan
_plan_adapter = TypeAdapter(ExecutionPlan)


def parse_plan(value: dict) -> ExecutionPlan:
    return _plan_adapter.validate_python(value)


class CreateMixing(StrictModel):
    session_id: UUID
    seed: int = Field(default=42, ge=0, le=2**31 - 1, strict=True)


def mixing_session(data: CreateMixing) -> dict:
    plan = MixingPlan(seed=data.seed, actions=mixing_steps(data.seed))
    return {
        "id": str(data.session_id),
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "experiment": plan.model_dump(mode="json"),
        "status": "draft",
        "state": None,
        "remote_active_run": None,
        "evidence": "pending",
    }
