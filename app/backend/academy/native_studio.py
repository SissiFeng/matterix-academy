"""Saved Studio plans and explicitly qualified native scene capabilities.

Preflight is an input check, never a source of native observations. The runtime
must execute and report this exact plan independently of the teaching runner.
"""

from typing import Literal

from pydantic import Field, model_validator

from .models import OT2_SLOTS, SLOTS, Experiment, StrictModel
from .native_plan import VolumeRange

STUDIO = "workflow-sandbox"
STUDIO_SCENES = {"workflow-studio-flex", "workflow-studio-ot2"}
Labware = Literal["tips", "stock", "plate", "waste"]


def studio_scene(plan: Experiment) -> str:
    if plan.course_id != STUDIO:
        raise ValueError("A Studio scene requires a saved Workflow Studio experiment")
    return f"workflow-studio-{plan.instrument}"


class StudioIssue(StrictModel):
    code: str
    message: str
    step: int | None = None


class StudioCapability(StrictModel):
    scene: Literal["workflow-studio-flex", "workflow-studio-ot2"]
    instrument: Literal["flex", "ot2"]
    slots: dict[Labware, list[str]]
    wells: list[Literal["A1", "A2", "A3"]] = Field(min_length=1)
    volume_ul: VolumeRange
    max_initial_ul: float = Field(gt=0, le=1500)
    pipette_capacity_ul: float = Field(gt=0, le=300)
    max_steps: int = Field(ge=1, le=64)
    max_tips: int = Field(ge=1, le=64)
    observed: list[Literal["liquid_volume", "tip_state"]] = Field(default_factory=list)
    viewport: bool = False

    @model_validator(mode="after")
    def exact_scene(self):
        if self.scene != f"workflow-studio-{self.instrument}":
            raise ValueError("Studio scene and instrument must agree")
        slots = SLOTS if self.instrument == "flex" else OT2_SLOTS
        waste = "D3" if self.instrument == "flex" else "12"
        if set(self.slots) != {"tips", "stock", "plate", "waste"}:
            raise ValueError("Declare every Studio labware slot")
        if any(not allowed or not set(allowed) <= slots for allowed in self.slots.values()):
            raise ValueError("Capability slots must belong to the declared instrument")
        if self.slots["waste"] != [waste]:
            raise ValueError("Declare the instrument's fixed waste position")
        if any(waste in self.slots[name] for name in ("tips", "stock", "plate")):
            raise ValueError("The fixed waste position cannot hold labware")
        if self.volume_ul.max > self.pipette_capacity_ul:
            raise ValueError("Transfer range exceeds pipette capacity")
        return self


def studio_preflight(plan: Experiment, capability: StudioCapability) -> list[StudioIssue]:
    """Check layout, amounts and complete action order without adjusting any input."""
    issues = []

    def issue(code, message, step=None):
        issues.append(StudioIssue(code=code, message=message, step=step))

    if studio_scene(plan) != capability.scene:
        return [StudioIssue(code="instrument", message="This host supports a different instrument")]
    for name, slot in plan.layout.items():
        if slot not in capability.slots[name]:
            issue("slot", f"The qualified scene cannot place {name} in slot {slot}")
    if not plan.actions or len(plan.actions) > capability.max_steps:
        issue("length", f"Use 1–{capability.max_steps} actions for this native scene")
    volumes = {
        "stock": plan.source_volume,
        **dict.fromkeys(("A1", "A2", "A3"), plan.diluent_volume),
    }
    for well, volume in volumes.items():
        if volume > capability.max_initial_ul:
            issue("source", f"Starting {well} volume exceeds {capability.max_initial_ul:g} µL")
    attached, tip, used = False, 0.0, 0
    for index, action in enumerate(plan.actions):
        if action.kind == "pickup":
            if attached:
                issue("sequence", "Discard the attached tip before picking up another", index)
            attached = True
            used += 1
            if used > capability.max_tips:
                issue("tips", "The workflow exceeds this scene's fresh-tip supply", index)
        elif action.kind == "drop":
            if not attached:
                issue("sequence", "There is no attached tip to discard", index)
            attached, tip = False, 0.0
        else:
            if not attached:
                issue("sequence", "Pick up a tip before transferring liquid", index)
            if action.well != "stock" and action.well not in capability.wells:
                issue("well", f"Well {action.well} is not supported by this scene", index)
            if not capability.volume_ul.min <= action.volume <= capability.volume_ul.max:
                issue(
                    "volume",
                    f"Use {capability.volume_ul.min:g}–{capability.volume_ul.max:g} µL per action",
                    index,
                )
            if action.kind == "aspirate":
                if volumes[action.well] + 1e-6 < action.volume:
                    issue("source", f"{action.well} has insufficient liquid at this step", index)
                if tip + action.volume > capability.pipette_capacity_ul + 1e-6:
                    issue("capacity", "This aspiration exceeds the pipette capacity", index)
                volumes[action.well] -= action.volume
                tip += action.volume
            else:
                if tip + 1e-6 < action.volume:
                    issue(
                        "sequence", "The tip does not contain the requested dispense volume", index
                    )
                volumes[action.well] += action.volume
                tip -= action.volume
                if volumes[action.well] > capability.max_initial_ul + 1e-6:
                    issue("capacity", f"This dispense exceeds {action.well}'s capacity", index)
    return issues
