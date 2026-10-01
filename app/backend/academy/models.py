from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SLOTS = {f"{row}{col}" for row in "ABCD" for col in range(1, 4)}
DEFAULT_LAYOUT = {"stock": "D1", "plate": "D2", "tips": "B1", "waste": "D3"}
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
    course_id: Literal["flex-foundations", "flex-first-transfer"] = "flex-foundations"
    transfer_volume: float = Field(default=100, ge=1, le=300)
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
        if self.layout["waste"] != "D3":
            raise ValueError("The Flex waste chute is fixed at D3. It is not a movable trash bin.")
        if self.course_id == "flex-first-transfer":
            expected = [
                ("pickup", "stock"),
                ("aspirate", "stock"),
                ("dispense", "A1"),
                ("drop", "stock"),
            ]
            if [(a.kind, a.well) for a in self.actions] != expected:
                raise ValueError(
                    "The first-transfer lesson uses pick up, aspirate stock, dispense A1, discard"
                )
            if any(
                a.volume != self.transfer_volume
                for a in self.actions
                if a.kind in {"aspirate", "dispense"}
            ):
                raise ValueError("Transfer actions must match the lesson volume")
            if self.diluent_volume != 0 or self.source_volume < self.transfer_volume:
                raise ValueError("Start with empty destination wells and enough source liquid")
        return self


class Prediction(StrictModel):
    source: float = Field(ge=0, le=1500)
    tip: float = Field(ge=0, le=300)
    target: float = Field(ge=0, le=1500)


class LearningProgress(StrictModel):
    phase: Literal["orient", "prepare", "predict", "run", "reflect"] = "orient"
    visited: list[Literal["pipette", "tips", "stock", "plate", "waste"]] = Field(
        default_factory=list, max_length=5
    )
    checks: list[Literal["instrument", "labware", "liquids", "simulation"]] = Field(
        default_factory=list, max_length=4
    )
    location_answer: Literal["", "slot", "well"] = ""
    prediction: Prediction | None = None
    reflection: Literal["", "source_to_tip", "source_to_target", "target_to_tip"] = ""


class UpdateLearning(StrictModel):
    version: int = Field(ge=1)
    learning: LearningProgress


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
        "id": "flex-first-transfer",
        "number": "01",
        "title": "From manual pipetting to your first automated transfer",
        "subtitle": "Meet the Flex, predict liquid volumes and complete a 100 µL transfer step by step.",
        "duration": "20–30 min",
        "level": "First steps",
        "objectives": [
            "Identify equipment and wells",
            "Check the deck and liquids",
            "Explain a liquid transfer",
        ],
        "model_note": "Practice uses a teaching model. Live 3D and remote execution require a qualified Ubuntu gateway.",
    },
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
    },
]
