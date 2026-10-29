"""Compile a saved Studio plan to a closed, deterministic Protocol API template."""

import json
from dataclasses import dataclass

from academy.models import Experiment
from academy.remote_run import workflow_digest

from .config import RobotProfile, canonical


@dataclass(frozen=True)
class CompiledProtocol:
    source: bytes
    action_count: int
    plan_hash: str
    expected_actions: tuple[str, ...]


def compile_plan(plan: Experiment, plan_hash: str, profile: RobotProfile) -> CompiledProtocol:
    profile.assert_current()
    if plan.course_id != "workflow-sandbox" or plan.instrument != profile.instrument:
        raise ValueError("Only a matching saved Studio instrument plan is supported")
    if workflow_digest(plan) != plan_hash:
        raise ValueError("Saved plan hash mismatch")
    if not plan.actions or len(plan.actions) > 64:
        raise ValueError("Use 1–64 supported actions")
    if plan.layout["waste"] != ("D3" if profile.instrument == "flex" else "12"):
        raise ValueError("The saved waste position differs from the instrument fixed waste")
    for name, labware in profile.labware.items():
        if plan.layout[name] != labware.slot:
            raise ValueError("Saved slots differ from the locally qualified physical deck")
    volumes = {
        "stock": plan.source_volume,
        **dict.fromkeys(("A1", "A2", "A3"), plan.diluent_volume),
    }
    for name, amount in volumes.items():
        if amount > profile.capacity_ul[name]:
            raise ValueError("Starting liquid exceeds a qualified well capacity")
    attached, tip_volume, used = False, 0.0, 0
    steps = []
    for action in plan.actions:
        if action.kind == "pickup":
            if attached or used >= len(profile.tip_wells):
                raise ValueError("Pickup needs an empty pipette and a fresh qualified tip")
            attached = True
            steps.append({"kind": "pickup", "well": profile.tip_wells[used]})
            used += 1
        elif action.kind == "drop":
            if not attached or tip_volume > 1e-6:
                raise ValueError(
                    "Drop requires an attached empty tip; liquid disposal is unsupported"
                )
            attached = False
            steps.append({"kind": "drop"})
        else:
            if not attached or not profile.min_volume_ul <= action.volume <= profile.max_volume_ul:
                raise ValueError("Transfer requires a tip and qualified volume")
            if action.kind == "aspirate":
                if volumes[action.well] < action.volume - 1e-6:
                    raise ValueError("Insufficient source liquid")
                if tip_volume + action.volume > profile.max_volume_ul + 1e-6:
                    raise ValueError("Pipette capacity exceeded")
                volumes[action.well] -= action.volume
                tip_volume += action.volume
            else:
                if tip_volume < action.volume - 1e-6:
                    raise ValueError("Insufficient liquid in tip")
                volumes[action.well] += action.volume
                tip_volume -= action.volume
                if volumes[action.well] > profile.capacity_ul[action.well] + 1e-6:
                    raise ValueError("Destination well capacity exceeded")
            steps.append({"kind": action.kind, "well": action.well, "volume": action.volume})
    if attached or abs(tip_volume) > 1e-6:
        raise ValueError("Workflow must end with an empty pipette and discarded tip")
    payload = {
        "labware": {
            name: {"definition": item.definition, "slot": item.slot}
            for name, item in profile.labware.items()
        },
        "steps": steps,
        "stock_well": profile.stock_well,
        "pipette": profile.pipette_model,
        "mount": profile.pipette_mount,
    }
    # All browser/local data are one escaped JSON string literal, never executable syntax.
    encoded = json.dumps(canonical(payload).decode(), ensure_ascii=True)
    requirements = json.dumps(
        {
            "robotType": "Flex" if plan.instrument == "flex" else "OT-2",
            "apiLevel": profile.protocol_api,
        }
    )
    source = f'''import json
requirements = {requirements}
metadata = {{"protocolName": "Academy qualified Studio transfer", "description": "{plan_hash}"}}
DATA = json.loads({encoded})

def run(ctx):
    labware = {{name: ctx.load_labware_from_definition(item["definition"], item["slot"])
               for name, item in DATA["labware"].items()}}
    pipette = ctx.load_instrument(DATA["pipette"], DATA["mount"], tip_racks=[labware["tips"]])
    waste = {"ctx.load_waste_chute()" if plan.instrument == "flex" else "ctx.fixed_trash"}
    for step in DATA["steps"]:
        if step["kind"] == "pickup":
            pipette.pick_up_tip(labware["tips"][step["well"]])
        elif step["kind"] == "drop":
            pipette.drop_tip(waste)
        else:
            target = (labware["stock"][DATA["stock_well"]] if step["well"] == "stock"
                      else labware["plate"][step["well"]])
            if step["kind"] == "aspirate":
                pipette.aspirate(step["volume"], target)
            else:
                pipette.dispense(step["volume"], target)
'''
    compile(source, "academy_protocol.py", "exec")
    names = {
        "pickup": "pickUpTip",
        "aspirate": "aspirate",
        "dispense": "dispense",
        "drop": "dropTip",
    }
    return CompiledProtocol(
        source.encode(), len(steps), plan_hash, tuple(names[action.kind] for action in plan.actions)
    )
