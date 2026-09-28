from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SLOTS = {f"{row}{col}" for row in "ABCD" for col in range(1, 4)}
DEFAULT_LAYOUT = {"stock": "D1", "plate": "D2", "tips": "B1", "waste": "A3"}
WELLS = {"stock", "A1", "A2", "A3"}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Action(StrictModel):
    kind: Literal["pickup", "aspirate", "dispense", "drop"]
    well: Literal["stock", "A1", "A2", "A3"] = "stock"
    volume: float = Field(default=100, gt=0, le=1000)


def default_actions() -> list[Action]:
    result = []
    for source, target in [("stock", "A1"), ("A1", "A2"), ("A2", "A3")]:
        result.extend(
            [
                Action(kind="pickup"),
                Action(kind="aspirate", well=source),
                Action(kind="dispense", well=target),
                Action(kind="drop"),
            ]
        )
    return result


class Experiment(StrictModel):
    title: str = Field(default="My serial dilution", min_length=1, max_length=80)
    course_id: Literal["flex-foundations"] = "flex-foundations"
    layout: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_LAYOUT))
    source_volume: float = Field(default=1000, ge=0, le=1500)
    diluent_volume: float = Field(default=100, ge=0, le=1500)
    actions: list[Action] = Field(default_factory=default_actions, min_length=1, max_length=64)

    @model_validator(mode="after")
    def layout_is_valid(self):
        if set(self.layout) != set(DEFAULT_LAYOUT):
            raise ValueError("Use the stock vial, destination plate, tip rack and waste chute")
        if not set(self.layout.values()) <= SLOTS:
            raise ValueError("Labware must occupy a Flex deck slot A1–D3")
        if len(set(self.layout.values())) != len(self.layout):
            raise ValueError("Two pieces of labware cannot occupy the same slot")
        return self


class Revision(StrictModel):
    version: int = Field(ge=1)


class UpdateExperiment(Revision):
    experiment: Experiment


class Guest(StrictModel):
    name: str = Field(min_length=1, max_length=60)


class Profile(StrictModel):
    name: str = Field(min_length=1, max_length=60)
    experience: Literal["new", "some", "experienced"] = "new"
    onboarded: bool = False


COURSES = [
    {
        "id": "flex-foundations",
        "number": "01",
        "title": "A little less, each time.",
        "subtitle": "Learn the Flex through a three-step serial dilution.",
        "duration": "15–20 min",
        "level": "Getting started",
        "objectives": [
            "Arrange a Flex deck",
            "Build a transfer sequence",
            "Diagnose and recover from mistakes",
        ],
        "target_concentrations": {"A1": 50, "A2": 25, "A3": 12.5},
        "model_note": "Teaching model: ideal mixing, volume bookkeeping and fresh-tip rules. No collision physics, fluid dynamics or chemical predictions.",
    }
]
