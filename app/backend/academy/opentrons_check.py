"""What the Opentrons simulator would say about a Studio plan, and the protocol to try it.

The rules mirror what `opentrons_simulate` did with the same mistakes (Flex on
opentrons 10.1.0, OT-2 on 8.3.0, API 2.20). It stops a run for tip and pipette
volume errors; it runs low volumes, overfilled wells and dry sources without
complaint, so those are reported separately. Nothing here is a run on a robot.
"""

import json

API_LEVEL = "2.20"
PLATE = {"load_name": "nest_96_wellplate_2ml_deep", "capacity_ul": 2000}
STOCK = {"load_name": "nest_12_reservoir_15ml", "capacity_ul": 15000}
PROFILES = {
    "flex": {
        "robot": "Flex",
        "pipette": "flex_1channel_1000",
        "pipette_name": "Flex 1-Channel 1000 µL",
        "tips": "opentrons_flex_96_tiprack_1000ul",
        "min_ul": 5,
        "max_ul": 1000,
        "waste": "ctx.load_waste_chute()",
    },
    "ot2": {
        "robot": "OT-2",
        "pipette": "p300_single_gen2",
        "pipette_name": "P300 Single-Channel GEN2",
        "tips": "opentrons_96_tiprack_300ul",
        "min_ul": 20,
        "max_ul": 300,
        "waste": "ctx.fixed_trash",
    },
}


def _ul(value):
    return f"{value:g} µL"


def check(experiment: dict) -> dict:
    profile = PROFILES[experiment.get("instrument", "flex")]
    wells = {
        "stock": experiment["source_volume"],
        **dict.fromkeys(("A1", "A2", "A3"), experiment["diluent_volume"]),
    }
    capacity = {
        "stock": STOCK["capacity_ul"],
        **dict.fromkeys(("A1", "A2", "A3"), PLATE["capacity_ul"]),
    }
    stops, unnoticed = [], []
    tip, held = False, 0.0

    def stop(step, message):
        stops.append({"step": step, "message": message})

    def note(step, message):
        unnoticed.append({"step": step, "message": message})

    for name, amount in wells.items():
        if amount > capacity[name]:
            note(None, f"{name} starts with {_ul(amount)}, more than its labware holds")
    for step, action in enumerate(experiment["actions"], 1):
        kind, well, volume = action["kind"], action["well"], action["volume"]
        if kind == "pickup":
            if tip:
                stop(step, "Picks up a tip while one is still attached")
            tip = True
            continue
        if not tip:
            verb = "Drops a tip" if kind == "drop" else f"{kind.capitalize()}s"
            stop(step, f"{verb} with no tip attached")
            continue
        if kind == "drop":
            if held > 1e-6:
                note(step, f"Drops the tip with {_ul(held)} still in it")
            tip, held = False, 0.0
            continue
        if volume < profile["min_ul"]:
            low = _ul(profile["min_ul"])
            note(
                step, f"{_ul(volume)} is below the {low} the {profile['pipette_name']} can measure"
            )
        if kind == "aspirate":
            room = profile["max_ul"] - held
            if volume > room + 1e-6:
                stop(step, f"Aspirates {_ul(volume)} when the tip has room for {_ul(room)}")
                continue
            if wells[well] < volume - 1e-6:
                note(step, f"Aspirates {_ul(volume)} from {well}, which holds {_ul(wells[well])}")
            wells[well] = max(0.0, wells[well] - volume)
            held += volume
        else:
            if volume > held + 1e-6:
                stop(step, f"Dispenses {_ul(volume)} when the tip holds {_ul(held)}")
                continue
            held -= volume
            wells[well] += volume
            if wells[well] > capacity[well] + 1e-6:
                note(step, f"Fills {well} to {_ul(wells[well])}, past its {_ul(capacity[well])}")
    if tip:
        note(None, "Ends with a tip still on the pipette")
    return {
        "robot": profile["robot"],
        "pipette": profile["pipette_name"],
        "tips": profile["tips"],
        "plate": PLATE["load_name"],
        "stock": STOCK["load_name"],
        "api_level": API_LEVEL,
        "evidence": "synthetic",
        "stops": stops,
        "unnoticed": unnoticed,
    }


def protocol(experiment: dict) -> str:
    """A readable Protocol API file for the plan; the caller checks nothing stops it first."""
    profile = PROFILES[experiment.get("instrument", "flex")]
    layout = experiment["layout"]
    lines = [
        f"requirements = {json.dumps({'robotType': profile['robot'], 'apiLevel': API_LEVEL})}",
        f"metadata = {json.dumps({'protocolName': experiment['title']}, ensure_ascii=True)}",
        "",
        "",
        "def run(ctx):",
        f'    tips = ctx.load_labware("{profile["tips"]}", "{layout["tips"]}")',
        f'    plate = ctx.load_labware("{PLATE["load_name"]}", "{layout["plate"]}")',
        f'    stock = ctx.load_labware("{STOCK["load_name"]}", "{layout["stock"]}")',
        f'    pipette = ctx.load_instrument("{profile["pipette"]}", "left", tip_racks=[tips])',
        f"    waste = {profile['waste']}",
    ]
    for action in experiment["actions"]:
        target = 'stock["A1"]' if action["well"] == "stock" else f'plate["{action["well"]}"]'
        lines.append(
            {
                "pickup": "    pipette.pick_up_tip()",
                "drop": "    pipette.drop_tip(waste)",
                "aspirate": f"    pipette.aspirate({action['volume']:g}, {target})",
                "dispense": f"    pipette.dispense({action['volume']:g}, {target})",
            }[action["kind"]]
        )
    source = "\n".join(lines) + "\n"
    compile(source, "academy_protocol.py", "exec")
    return source
