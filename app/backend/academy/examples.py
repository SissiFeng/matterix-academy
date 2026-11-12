"""Example workcells a learner can open in the planner: instruments, workflow and layout.

Each layout is one the layout search found for that workflow on this bench; the tests
plan every one again, so an example never opens on a layout the arm cannot run. An
example without a layout is one the search finds none for, kept to show why.
"""

C, S, W = "chemlab", "simready", "workcell"
ARM = (W, "ur5e-2f140")
FLEX = (C, "opentrons_flex_single_5_1000ul")
OT2 = (W, "opentrons-ot2")
READER = (C, "bmg_clariostarplus")
BENCH = {"width": 2.4, "depth": 1.6}


def _move(source, target):
    return ("transfer", source, target)


# Instruments are numbered in order, the arm last; a step is (operation, instrument, value)
# or a transfer between two instruments; a placement is (instrument, x, z, yaw).
EXAMPLES = {
    "flex-reader": {
        "name": "Flex to plate reader",
        "summary": "A plate is mixed on the Flex and read.",
        "instruments": [FLEX, READER],
        "steps": [("load", 0, 150), ("mix", 0, 5), _move(0, 1), ("read", 1, 1)],
        "placements": [(2, 0.0, 0.0, 0), (0, 0.79, 0.21, -90), (1, -0.7, 0.21, 90)],
    },
    "ot2-flex": {
        "name": "OT-2 to Flex",
        "summary": "A plate prepared on the OT-2 is handed to the Flex.",
        "instruments": [OT2, FLEX],
        "steps": [("load", 0, 200), ("mix", 0, 5), _move(0, 1), ("mix", 1, 5)],
        "placements": [(2, 0.0, 0.0, 0), (0, 0.73, 0.21, -90), (1, -0.79, 0.21, 90)],
    },
    "flex-sealer-reader": {
        "name": "Flex, plate sealer, plate reader",
        "summary": "A plate is mixed, heat-sealed and read.",
        "instruments": [FLEX, (C, "azenta_automated_roll_heat_sealer_a4s"), READER],
        "steps": [
            ("load", 0, 150),
            ("mix", 0, 5),
            _move(0, 1),
            ("heat", 1, 100),
            _move(1, 2),
            ("read", 2, 1),
        ],
        "placements": [
            (3, 0.0, 0.0, 0),
            (1, 0.27, 0.48, 180),
            (0, 0.79, 0.21, -90),
            (2, -0.81, 0.28, 90),
        ],
    },
    "flex-shaker-reader": {
        "name": "Flex, incubated shaker, plate reader",
        "summary": "No layout yet: the shaker is loaded from above at 0.52 m, out of this "
        "arm's reach from the bench.",
        "instruments": [FLEX, (C, "ika_ks4000"), (S, "forgecad-microplate-reader")],
        "steps": [
            ("load", 0, 150),
            _move(0, 1),
            ("heat", 1, 37),
            ("mix", 1, 60),
            _move(1, 2),
            ("read", 2, 1),
        ],
        "placements": None,
    },
    "ot2-incubator-fridge": {
        "name": "OT-2, incubator, refrigerator",
        "summary": "A plate is prepared, incubated and stored cold.",
        "instruments": [
            OT2,
            (S, "forgecad-laboratory-incubator"),
            (S, "nvidia-undercounter-refrigerator"),
        ],
        "steps": [
            ("load", 0, 200),
            ("mix", 0, 5),
            _move(0, 1),
            ("heat", 1, 37),
            _move(1, 2),
            ("wait", 2, 60),
        ],
        "placements": [
            (3, 0.0, -0.4, 0),
            (1, 0.0, 0.42, 180),
            (0, 0.73, -0.19, -90),
            (2, -0.82, -0.19, 90),
        ],
    },
    "balance-oven": {
        "name": "Analytical balance to drying oven",
        "summary": "A vial is weighed and dried.",
        "instruments": [(C, "mt_xpr204e"), (C, "binder_fd056")],
        "steps": [("load", 0, 1000), ("read", 0, 1), _move(0, 1), ("heat", 1, 80)],
        "placements": [(2, 0.0, 0.0, 0), (0, 0.0, 0.42, 180), (1, 0.76, 0.21, -90)],
    },
    "balance-flex-reader": {
        "name": "Precision balance, Flex, plate reader",
        "summary": "A plate is weighed, mixed on the Flex and read.",
        "instruments": [(W, "precision-balance"), FLEX, READER],
        "steps": [
            ("load", 0, 150),
            ("read", 0, 1),
            _move(0, 1),
            ("mix", 1, 5),
            _move(1, 2),
            ("read", 2, 1),
        ],
        "placements": [
            (3, 0.0, 0.0, 0),
            (1, 0.79, 0.21, -90),
            (0, 0.21, 0.36, 180),
            (2, -0.7, 0.21, 90),
        ],
    },
}


def listing():
    from .library import COLLECTIONS

    return [
        {
            "id": key,
            "name": case["name"],
            "summary": case["summary"],
            "instruments": [
                COLLECTIONS[c][i]["spec"]["name"] for c, i in [*case["instruments"], ARM]
            ],
            "placed": case["placements"] is not None,
        }
        for key, case in EXAMPLES.items()
    ]


def build(case, new_id):
    """(twins, steps, layout) of an example, every twin confirmed as its entry describes it."""
    from copy import deepcopy

    from . import chemlab, simready, workcell_models
    from .library import COLLECTIONS
    from .simple_twins import new_twin

    provenance = {C: chemlab.provenance, S: simready.provenance, W: workcell_models.provenance}
    twins = []
    for collection, key in [*case["instruments"], ARM]:
        spec = deepcopy(COLLECTIONS[collection][key]["spec"])
        twin = new_twin(new_id(), f"{collection}_asset", spec, provenance[collection](key))
        twins.append({**twin, "confirmed": True, "status": "ready", "revision": 1})
    ids = [t["id"] for t in twins]
    steps = [
        {
            "device_id": ids[-1] if op == "transfer" else ids[a],
            "operation": op,
            "source_id": ids[a] if op == "transfer" else None,
            "target_id": ids[b] if op == "transfer" else None,
            "value": 1 if op == "transfer" else b,
        }
        for op, a, b in case["steps"]
    ]
    layout = case["placements"] and {
        "bench": dict(BENCH),
        "placements": [
            {"twin_id": ids[i], "x": x, "z": z, "yaw": yaw, "access": "top", "kept": False}
            for i, x, z, yaw in case["placements"]
        ],
    }
    return twins, steps, layout
