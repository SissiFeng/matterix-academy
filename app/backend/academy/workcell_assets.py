"""Registered 3D assets and multi-device onboarding cases. Files are served with the web app.

A case's hand-designed arm path can be run in the MuJoCo arm simulation.
"""

import math
from functools import cache
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, model_validator

from . import arm_simulation
from .auth import identify
from .models import StrictModel

ROOT = Path(__file__).with_name("workcell_assets.json")
SHA = r"^[a-f0-9]{64}$"
COMMIT = r"^[a-f0-9]{40}$"


class Source(StrictModel):
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    commit: str | None = Field(default=None, pattern=COMMIT)
    paths: list[str] = Field(min_length=1, max_length=8)


class Asset(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9-]{3,64}$")
    kind: Literal["robot", "instrument", "labware", "deck", "fixture", "metadata"]
    name: str = Field(min_length=1, max_length=120)
    media_type: Literal["model/gltf-binary", "application/json", "application/x-academy-procedural"]
    file: str | None = Field(default=None, pattern=r"^[a-z0-9_.-]{1,64}$")
    sha256: str | None = Field(default=None, pattern=SHA)
    size_bytes: int | None = Field(default=None, gt=0, le=20_000_000)
    license: Literal["BSD-3-Clause", "MIT", "Apache-2.0", "Project"]
    sources: list[Source] = Field(min_length=1, max_length=4)
    frame: str = Field(min_length=1, max_length=300)
    notes: str = Field(min_length=1, max_length=1200)

    @model_validator(mode="after")
    def file_fields(self):
        procedural = self.media_type == "application/x-academy-procedural"
        if procedural != (self.file is None) or (self.file is None) != (self.sha256 is None):
            raise ValueError(
                "A file asset needs a file name and digest; a procedural one has neither"
            )
        if (self.file is None) != (self.size_bytes is None):
            raise ValueError("A file asset needs its size")
        return self


class CaseDevice(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9-]{2,32}$")
    name: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=80)
    asset: str


class Case(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9-]{3,64}$")
    name: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=400)
    devices: list[CaseDevice] = Field(min_length=1, max_length=12)
    assets: list[str] = Field(min_length=1, max_length=32)
    evidence: Literal["synthetic"]


class Registry(StrictModel):
    schema_version: Literal["academy.workcell-assets/1"]
    base_path: Literal["/workcell-assets/"]
    assets: list[Asset] = Field(min_length=1, max_length=64)
    cases: list[Case] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def references(self):
        ids = [a.id for a in self.assets]
        if len(set(ids)) != len(ids) or len({c.id for c in self.cases}) != len(self.cases):
            raise ValueError("Asset and case identifiers must be unique")
        for case in self.cases:
            missing = {*case.assets, *(d.asset for d in case.devices)} - set(ids)
            if missing:
                raise ValueError(
                    f"Case {case.id} references unregistered assets: {sorted(missing)}"
                )
            if not {d.asset for d in case.devices} <= set(case.assets):
                raise ValueError(f"Case {case.id} must list every device asset")
        return self


@cache
def registry() -> Registry:
    return Registry.model_validate_json(ROOT.read_text(encoding="utf-8"))


router = APIRouter(prefix="/api/workcell")


@router.get("/assets")
def list_assets(owner: str = Depends(identify)):
    return registry().model_dump(mode="json")


@router.get("/cases/{case_id}")
def get_case(case_id: str, owner: str = Depends(identify)):
    reg = registry()
    case = next((c for c in reg.cases if c.id == case_id), None)
    if case is None:
        raise HTTPException(404, "This workcell case is not registered.")
    assets = {a.id: a for a in reg.assets}
    return {
        **case.model_dump(mode="json"),
        "base_path": reg.base_path,
        "assets": [assets[i].model_dump(mode="json") for i in case.assets],
    }


Metres = Annotated[float, Field(ge=-5, le=5)]
Radians = Annotated[float, Field(ge=-2 * math.pi, le=2 * math.pi)]
PATH_SECONDS = 180  # longer than the connector's 120 s action, so every valid chain fits


class Keepout(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    min: tuple[Metres, Metres, Metres]
    max: tuple[Metres, Metres, Metres]
    # The arm's base links may touch what the arm stands on.
    stand: bool = False

    @model_validator(mode="after")
    def ordered(self):
        if any(hi <= lo for lo, hi in zip(self.min, self.max, strict=True)):
            raise ValueError("A keep-out needs max above min on every axis")
        return self


class ArmPath(StrictModel):
    """A timed joint trajectory in the arm's base frame: one joint vector every `dt`."""

    arm: Literal["ur3e", "ur5e", "ur10e"] = "ur5e"
    dt: float = Field(ge=0.008, le=0.1)
    joints: list[tuple[Radians, Radians, Radians, Radians, Radians, Radians]] = Field(
        min_length=2, max_length=6000
    )
    boxes: list[Keepout] = Field(max_length=400)
    tool_m: float = Field(ge=0.05, le=0.4)

    @model_validator(mode="after")
    def bounded(self):
        if (len(self.joints) - 1) * self.dt > PATH_SECONDS:
            raise ValueError(f"An arm path may last at most {PATH_SECONDS} s")
        return self


@router.post("/arm-path/simulate")
def simulate_arm_path(data: ArmPath, owner: str = Depends(identify)):
    """Read-only: nothing is stored and no robot moves."""
    if not arm_simulation.available():
        raise HTTPException(503, "The arm simulation is not installed on this server")
    return arm_simulation.play(
        data.arm, data.joints, data.dt, [b.model_dump() for b in data.boxes], data.tool_m
    )
