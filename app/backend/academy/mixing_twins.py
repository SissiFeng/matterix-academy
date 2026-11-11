"""The four-source recipe on a saved teaching twin. Bookkeeping only, never native evidence."""

import re
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field

from .models import StrictModel
from .recipes import MIXING
from .store import Conflict

FLEX = "flex"
VIAL_UL = 1500
WELL_UL = 2000  # opentrons_check.PLATE
MIN_UL = 5  # Flex 1-Channel 1000 µL
TRANSFER = {
    "pickup": "pick up a tip",
    "aspirate": "aspirate",
    "dispense": "dispense",
    "drop": "drop a tip",
}


class TwinRun(StrictModel):
    run_id: UUID
    expected_version: int = Field(ge=1, strict=True)
    twin: str = Field(pattern=r"^(flex|(device|instrument):[0-9a-f-]{36})$")


class Stop(Exception):
    def __init__(self, layer, message):
        self.layer, self.message = layer, message


def _frame(sources, mixture, lid_parked, tips):
    return {
        "source_volumes_ul": list(sources),
        "mixture_components_ul": list(mixture),
        "lid_parked": lid_parked,
        "tips_used": list(tips),
        "tips_discarded": list(tips),
    }


def execute(plan: dict, twin: dict) -> dict:
    """Replay the recipe against one twin's modelled layers, stopping at the first it rejects."""
    sources, mixture, tips, lid = [float(VIAL_UL)] * 8, [0.0] * 8, [], False
    capacity, stock, per_use = WELL_UL, None, 1
    capabilities = None
    if twin["kind"] == "device":
        capabilities = set(twin["capabilities"])
    if twin["kind"] == "instrument":
        spec = twin["spec"]
        capacity = spec["container"]["max_volume_ul"]
        tip = next((c for c in spec["consumables"] if re.search("tip", c["name"], re.I)), None)
        if tip:
            stock, per_use = tip["stock"], tip["per_use"]
    name = twin["name"]
    frames, stop = [_frame(sources, mixture, lid, tips)], None
    for step in plan["actions"]:
        try:
            if step["kind"] == "uncover":
                if capabilities is not None and "move_labware" not in capabilities:
                    raise Stop("state", f"{name} has not declared that it can move labware")
                lid = True
            else:
                volume, source = step["volume_ul"], step["source_index"]
                if capabilities is not None:
                    missing = [text for key, text in TRANSFER.items() if key not in capabilities]
                    if missing:
                        raise Stop("state", f"{name} has not declared that it can {missing[0]}")
                if not lid:
                    raise Stop("state", "The source vials are still covered")
                if stock is not None:
                    if stock < per_use:
                        raise Stop("consumable", f"{name} has no tips left for this transfer")
                    stock -= per_use
                if sum(mixture) + volume > capacity + 1e-6:
                    raise Stop(
                        "volume",
                        f"{name} holds {capacity:g} µL; this transfer needs "
                        f"{sum(mixture) + volume:g} µL",
                    )
                sources[source] -= volume
                mixture[source] += volume
                tips.append(step["tip_id"])
        except Stop as exc:
            stop = {"step": len(frames), "layer": exc.layer, "message": exc.message}
            break
        frames.append(_frame(sources, mixture, lid, tips))
    transfers = [s for s in plan["actions"] if s["kind"] == "transfer"]
    done = stop is None
    checks = [
        {"label": "Every step completed", "passed": done},
        {
            "label": "A fresh tip for every source",
            "passed": len(set(tips)) == len(tips),
        },
        {
            "label": f"Each transfer is at least the {MIN_UL} µL the pipette can measure",
            "passed": all(s["volume_ul"] >= MIN_UL for s in transfers),
        },
        {
            "label": f"The mixture fits its {capacity:g} µL vessel",
            "passed": sum(s["volume_ul"] for s in transfers) <= capacity + 1e-6,
        },
    ]
    return {
        "status": "completed" if done else "stopped",
        "stop": stop,
        "frames": frames,
        "checks": checks,
    }


class MixingTwinService:
    """Saved twins a learner can run the mixing recipe on, and the latest such run."""

    def __init__(self, store, twins):
        self.store, self.twins = store, twins

    def options(self, owner):
        devices = [
            {
                "key": f"device:{d['id']}",
                "kind": "device",
                "name": d["name"],
                "revision": d["version"],
                "capabilities": d["capabilities"],
            }
            for d in self.store.partition(owner, "device#")
            if d.get("twin_session_id")
        ]
        instruments = [
            {
                "key": f"instrument:{t['id']}",
                "kind": "instrument",
                "name": t["spec"]["name"],
                "revision": t["revision"],
                "spec": t["spec"],
            }
            for t in self.twins.get(owner)["twins"]
            if t["confirmed"] and t.get("spec") and "load" in t["spec"]["operations"]
        ]
        return [
            {"key": FLEX, "kind": "builtin", "name": "Flex teaching twin", "revision": 1},
            *devices,
            *instruments,
        ]

    def catalog(self, owner):
        return [{k: o[k] for k in ("key", "kind", "name", "revision")} for o in self.options(owner)]

    def get(self, owner, session_id):
        return self.store.get(owner, f"twin-run#{session_id}")

    def run(self, owner, session_id, data: TwinRun):
        session = self.store.get(owner, f"session#{session_id}")
        if not session or session["experiment"]["course_id"] != MIXING:
            raise HTTPException(404, "Experiment not found")
        key = f"twin-run#{session_id}"
        previous = self.store.get(owner, key)
        if previous and previous["run_id"] == str(data.run_id):
            if previous["twin"]["key"] != data.twin:
                raise Conflict
            return previous
        if session["version"] != data.expected_version:
            raise Conflict
        if session.get("remote_active_run"):
            raise HTTPException(409, "A GPU run still owns this experiment")
        twin = next((o for o in self.options(owner) if o["key"] == data.twin), None)
        if not twin:
            raise HTTPException(404, "Saved twin not found")
        record = {
            "version": (previous["version"] if previous else 0) + 1,
            "run_id": str(data.run_id),
            "session_id": str(session_id),
            "session_version": session["version"],
            "created_at": datetime.now(UTC).isoformat(),
            "engine": "simple_twin" if twin["kind"] == "instrument" else "teaching",
            "evidence": "synthetic",
            "twin": {k: twin[k] for k in ("key", "kind", "name", "revision")},
            **execute(session["experiment"], twin),
        }
        self.store.put(owner, key, record, previous["version"] if previous else None)
        return record
