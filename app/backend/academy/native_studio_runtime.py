"""Saved-plan geometry and finite-volume accounting for the native Studio adapter.

This module never advances the teaching model. Runtime amounts follow changes
measured from Matterix's pipette storage after native simulation ticks. The
geometry is a versioned simulation scene contract, not hardware calibration.
"""

import math
from dataclasses import dataclass
from pathlib import Path

from .models import Experiment
from .native_studio import FLEX_STUDIO_SLOTS

SCENE_VERSION = "academy-flex-studio-v1"
ENGINE_COMMIT = "18a96b78ee989fbf4e480e9db6a588c148c6adbe"
ASSET_COMMIT = "c57f12a04079a5f99405e1fcb818a3b7ccc52e5b"
# CAD anchors from the pinned internal flex_mixing scene. Labware origins are
# front-left, with the 165 mm column and 107 mm row grid preserved.
DECK_Z = 0.1405
RIGHT_HOME = (0.02710801975, 0.23444792551, 0.39054499843)
TIP_LENGTH = 0.0956
TIP_OVERLAP = 0.0105
TIP_CAPACITY = 300.0  # Deliberately below the installed 1000 uL native tip.
WELL_CAPACITY = 1500.0
SLOTS = tuple(sorted(FLEX_STUDIO_SLOTS - {"D3"}))
JOINT_BOUNDS = (
    (-0.2885, 0.299),
    (-0.1429, 0.2642),
    (-0.2136, 0),
    (-0.2136, 0),
    (-0.14, 0),
    (0, 0.0075),
    (0.0075, 0.015),
)
ASSET_FILES = (
    "robots/flex/Opentrons Flex_gripper_final.usd",
    "labware/flex_mixing/rack_1000.usda",
    "labware/flex_mixing/tip_1000.usda",
    "labware/flex_mixing/mix_plate.usda",
    "labware/flex_mixing/reservoir.usda",
    "labware/flex_mixing/trash_collision.usda",
)


def flex_capability():
    """Declare only geometry/actions implemented here; this is not qualification."""
    return {
        "scene": "workflow-studio-flex",
        "instrument": "flex",
        "slots": {"stock": list(SLOTS), "plate": list(SLOTS), "tips": list(SLOTS), "waste": ["D3"]},
        "wells": ["A1", "A2", "A3"],
        "volume_ul": {"min": 1, "max": TIP_CAPACITY},
        "max_initial_ul": WELL_CAPACITY,
        "pipette_capacity_ul": TIP_CAPACITY,
        "max_steps": 64,
        "max_tips": 64,
        "observed": ["tip_state", "liquid_volume"],
        "viewport": True,
    }


def validate_assets(plan, config):
    """Fail before allocation, never fall back to a different robot or recipe."""
    if plan.instrument != "flex":
        raise ValueError(
            "OT-2 Studio needs a qualified OT-2 asset and deck mapping; this image contains only the approved Flex scene"
        )
    if config.engine_version != ENGINE_COMMIT or config.asset_version != ASSET_COMMIT:
        raise ValueError("Studio geometry requires its exact reviewed engine and asset revisions")
    root = Path(config.assets_data_dir)
    for relative in ASSET_FILES:
        path = root / relative
        if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Studio native asset is unavailable: {relative}")
        with path.open("rb") as stream:
            if stream.read(100).startswith(b"version https://git-lfs.github.com/spec/"):
                raise ValueError(f"Studio native asset is an LFS pointer: {relative}")


def slot_origin(slot):
    if slot not in (*SLOTS, "D3"):
        raise ValueError(f"Slot {slot} is unavailable in this native Flex scene")
    row, column = slot[0], int(slot[1])
    return (-0.2238 + (column - 1) * 0.165, 0.08544 + "DCBA".index(row) * 0.107, DECK_Z)


def point(origin, offset):
    return tuple(a + b for a, b in zip(origin, offset, strict=True))


def joint_target(xyz):
    target = (
        xyz[0] - RIGHT_HOME[0],
        xyz[1] - RIGHT_HOME[1],
        0.0,
        xyz[2] - RIGHT_HOME[2],
        0.0,
        0.0,
        0.0075,
    )
    if any(
        not math.isfinite(v) or v < lo - 1e-6 or v > hi + 1e-6
        for v, (lo, hi) in zip(target, JOINT_BOUNDS, strict=True)
    ):
        raise ValueError("Saved layout contains an unreachable native waypoint")
    return target


@dataclass(frozen=True)
class NativeStep:
    index: int
    kind: str
    well: str
    volume: float
    target: tuple[float, float, float]
    tip_id: str | None


def compile_plan(value):
    """Keep every saved step/layout/amount; validate the entire plan before motion."""
    plan = value if isinstance(value, Experiment) else Experiment.model_validate(value)
    if plan.course_id != "workflow-sandbox" or plan.instrument != "flex":
        raise ValueError("This native adapter executes saved Flex Studio plans only")
    if not plan.actions:
        raise ValueError("Add a workflow step before native execution")
    for name in ("stock", "plate", "tips"):
        if plan.layout[name] not in SLOTS:
            raise ValueError(
                f"{name}: slot {plan.layout[name]} is unavailable; A3 is occupied by the approved CAD's rear waste geometry"
            )
    origins = {name: slot_origin(slot) for name, slot in plan.layout.items()}
    targets = {"stock": point(origins["stock"], (0.0143, 0.04265, 0.012))}
    targets.update(
        {
            f"A{i}": point(origins["plate"], (0.0143 + (i - 1) * 0.009, 0.07415, 0.012))
            for i in range(1, 4)
        }
    )
    steps, used, active = [], 0, None
    validation = NativeLedger(plan)
    for index, action in enumerate(plan.actions):
        validation.check(action.kind, action.well, action.volume)
        if action.kind == "pickup":
            col, row = divmod(used, 8)
            active = f"Tips__{'ABCDEFGH'[row]}{col + 1}"
            target = point(
                origins["tips"], (0.01438 + col * 0.009, 0.07438 - row * 0.009, 0.099 - TIP_OVERLAP)
            )
            used += 1
        elif action.kind == "drop":
            target = point(origins["waste"], (0.0638, 0.04265, 0.035 + TIP_LENGTH - TIP_OVERLAP))
        else:
            target = point(targets[action.well], (0, 0, TIP_LENGTH - TIP_OVERLAP))
        joint_target(target)
        joint_target((target[0], target[1], RIGHT_HOME[2]))
        steps.append(NativeStep(index, action.kind, action.well, action.volume, target, active))
        # This is compile-time validity only, never published as native evidence.
        validation.preview(action.kind, action.well, action.volume)
        if action.kind == "drop":
            active = None
    return plan, origins, steps


class NativeLedger:
    """Native scene's finite containers, coupled to observed Matterix storage deltas."""

    def __init__(self, plan):
        self.initial = {
            "stock": float(plan.source_volume),
            **{f"A{i}": float(plan.diluent_volume) for i in range(1, 4)},
        }
        self.reset()

    def reset(self):
        self.wells = self.initial.copy()
        self.pipette = 0.0
        self.waste = 0.0
        self.attached = False
        self.used = 0

    def check(self, kind, well, amount):
        if kind == "pickup":
            if self.attached or self.pipette > 0.01 or self.used >= 64:
                raise ValueError("Native pickup requires an empty mount and an unused tip")
        elif not self.attached:
            raise ValueError("Native liquid handling and disposal require an attached tip")
        elif kind in {"aspirate", "dispense"}:
            if not math.isfinite(amount) or not 1 <= amount <= TIP_CAPACITY:
                raise ValueError("Native Studio transfer must be between 1 and 300 uL")
            if kind == "aspirate" and (
                self.wells[well] + 0.01 < amount or self.pipette + amount > TIP_CAPACITY + 0.01
            ):
                raise ValueError("Native aspiration exceeds source liquid or pipette capacity")
            if kind == "dispense" and (
                self.pipette + 0.01 < amount or self.wells[well] + amount > WELL_CAPACITY + 0.01
            ):
                raise ValueError("Native dispensing exceeds pipette liquid or well capacity")

    def preview(self, kind, well, amount):
        if kind == "pickup":
            self.attached, self.used = True, self.used + 1
        elif kind == "drop":
            self.waste += self.pipette
            self.pipette, self.attached = 0.0, False
        else:
            self.observe_volume(
                self.pipette + (amount if kind == "aspirate" else -amount), kind, well
            )

    def observe_volume(self, measured, kind, well):
        if not math.isfinite(measured) or measured < -0.01 or measured > TIP_CAPACITY + 0.01:
            raise RuntimeError("Native pipette reported an invalid volume")
        measured = max(0.0, measured)
        delta = measured - self.pipette
        if (kind == "aspirate" and delta < -0.01) or (kind == "dispense" and delta > 0.01):
            raise RuntimeError("Native flow moved opposite to the saved action")
        if kind not in {"aspirate", "dispense"} and abs(delta) > 0.01:
            raise RuntimeError("Native pipette volume changed outside a liquid action")
        if kind in {"aspirate", "dispense"}:
            self.wells[well] -= delta
            if -0.01 < self.wells[well] < 0:
                self.wells[well] = 0.0
        self.pipette = measured
        self.assert_conserved()

    def assert_conserved(self):
        if any(
            not math.isfinite(v) or v < -0.01 or v > WELL_CAPACITY + 0.01
            for v in self.wells.values()
        ):
            raise RuntimeError("Native container bounds failed")
        if (
            abs(sum(self.wells.values()) + self.pipette + self.waste - sum(self.initial.values()))
            > 0.02
        ):
            raise RuntimeError("Native finite-volume conservation failed")
