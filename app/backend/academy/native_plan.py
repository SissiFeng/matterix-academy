"""Translate a learner's saved first-transfer experiment into a native intent and preflight it.

The intent is a deterministic, logical description of what the learner asked for. It is
derived from the hashed ``Experiment`` and never edited to fit a scene. A simulation host
declares what its qualified scene supports; any mismatch is an explicit preflight issue, never
a silent substitution of a preset workflow or different values.
"""

from typing import Literal

from pydantic import Field, model_validator

from .models import SLOTS, Experiment, StrictModel

FIRST_TRANSFER = "flex-first-transfer"
LogicalLabware = Literal["tips", "stock", "plate", "waste"]


class NativeStep(StrictModel):
    index: int = Field(ge=0)
    kind: Literal["pickup", "aspirate", "dispense", "drop"]
    labware: LogicalLabware
    well: str | None = None
    volume_ul: float | None = None


class NativeTransferIntent(StrictModel):
    scene: Literal["flex-first-transfer"] = FIRST_TRANSFER
    labware: dict[LogicalLabware, str]
    initial_volume_ul: dict[str, float]
    steps: list[NativeStep]


class VolumeRange(StrictModel):
    min: float = Field(gt=0)
    max: float = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self):
        if self.min > self.max:
            raise ValueError("Volume range minimum exceeds maximum")
        return self


class TransferCapability(StrictModel):
    """What a qualified host's first-transfer scene can execute and observe."""

    scene: Literal["flex-first-transfer"] = FIRST_TRANSFER
    slots: dict[LogicalLabware, list[str]]
    wells: list[str] = Field(min_length=1)
    volume_ul: VolumeRange
    max_source_ul: float = Field(gt=0)
    max_steps: int = Field(ge=4, le=64)
    observed: list[Literal["liquid_volume", "tip_state"]] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_slots(self):
        if set(self.slots) != {"tips", "stock", "plate", "waste"}:
            raise ValueError("Declare allowed slots for tips, stock, plate and waste")
        for allowed in self.slots.values():
            if not allowed or not set(allowed) <= SLOTS:
                raise ValueError("Capability slots must be Flex deck slots A1–D3")
        return self


class PreflightIssue(StrictModel):
    code: Literal["slot", "well", "volume", "source", "length"]
    message: str
    step: int | None = None


def intent_for(experiment: Experiment) -> NativeTransferIntent:
    if experiment.course_id != FIRST_TRANSFER:
        raise ValueError("Only the first-transfer lesson has a native transfer intent")
    steps = []
    for index, action in enumerate(experiment.actions):
        if action.kind == "pickup":
            step = NativeStep(index=index, kind="pickup", labware="tips")
        elif action.kind == "drop":
            step = NativeStep(index=index, kind="drop", labware="waste")
        else:
            on_stock = action.well == "stock"
            step = NativeStep(
                index=index,
                kind=action.kind,
                labware="stock" if on_stock else "plate",
                well=None if on_stock else action.well,
                volume_ul=action.volume,
            )
        steps.append(step)
    initial = {"stock": experiment.source_volume}
    initial.update({well: experiment.diluent_volume for well in ("A1", "A2", "A3")})
    return NativeTransferIntent(
        labware=dict(experiment.layout), initial_volume_ul=initial, steps=steps
    )


def preflight(intent: NativeTransferIntent, capability: TransferCapability) -> list[PreflightIssue]:
    issues = []
    for name, slot in intent.labware.items():
        if slot not in capability.slots[name]:
            allowed = ", ".join(capability.slots[name])
            issues.append(
                PreflightIssue(
                    code="slot",
                    message=f"The simulation scene supports {name} only in {allowed}, not {slot}",
                )
            )
    if len(intent.steps) > capability.max_steps:
        issues.append(
            PreflightIssue(
                code="length",
                message=f"The scene accepts at most {capability.max_steps} actions",
            )
        )
    if intent.initial_volume_ul["stock"] > capability.max_source_ul:
        issues.append(
            PreflightIssue(
                code="source",
                message=f"Starting stock above {capability.max_source_ul:g} µL is not supported",
            )
        )
    span = capability.volume_ul
    for step in intent.steps:
        if step.well is not None and step.well not in capability.wells:
            issues.append(
                PreflightIssue(
                    code="well",
                    step=step.index,
                    message=f"Well {step.well} is not available in the simulation scene",
                )
            )
        if step.volume_ul is not None and not span.min <= step.volume_ul <= span.max:
            issues.append(
                PreflightIssue(
                    code="volume",
                    step=step.index,
                    message=(
                        f"{step.volume_ul:g} µL is outside the scene's qualified "
                        f"{span.min:g}–{span.max:g} µL range"
                    ),
                )
            )
    return issues
