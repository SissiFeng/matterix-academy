"""MBZUAI ChemLab-Assets instruments usable as starting points for teaching twins.

`chemlab_catalog.json` is a pinned snapshot of the release catalog (name, maker, model,
domain, dataset path and overall size of all 203 instruments). A twin's footprint is one
box with the catalog size; the 3D view draws the dataset's own model.glb in its place,
and arm paths stay clear of boxes measured from that model (`chemlab_collision.json`).
Those models are pinned by sha256 in `chemlab_models.json` and served from the web app's
origin (`scripts/library-models/chemlab_models.py`); URDF, contracts and behaviour models
are never used. Operations, vessel, volume, slots and limits are Academy teaching
defaults, not manufacturer specifications or ChemLab behaviour.
Featured instruments carry hand-chosen defaults; the rest get defaults from their kind.
ChemLab geometry is reconstructed from public documents and may reuse a stand-in model,
so the box is a reference footprint, not instrument CAD. The assets are CC-BY-NC-4.0:
attribution and the non-commercial term travel with the twin and its exports.
"""

import json
import re
from pathlib import Path

from .collision import _measured
from .simready import footprint_spec

LICENSE = "CC-BY-NC-4.0"
REPO = "MBZUAI/ChemLab-Assets"
REVISION = "3b67020dcccb22e60be3235f32b39d03da5959ab"  # dataset release 1.5.0
SNAPSHOT = json.loads((Path(__file__).parent / "chemlab_catalog.json").read_text())
MODELS = json.loads((Path(__file__).parent / "chemlab_models.json").read_text())
assert MODELS["revision"] == REVISION, "chemlab_models.json is pinned to another revision"


def mesh(slug):
    """The pinned model.glb the 3D view draws for this instrument, if the dataset has one."""
    model = MODELS["models"].get(slug)
    if not model:
        return None
    # Most ChemLab models stand on z = 0 with Z up and the view turns them to Y up; the
    # manifest marks the few that are already Y up.
    return {
        "kind": "glb",
        "url": f"/{model['file']}",
        "sha256": model["sha256"],
        "up": model.get("up", "z"),
    }


FEATURED = {
    "mt_xpr204e": {
        "name": "Analytical balance (XPR204E)",
        "operations": ["load", "read", "wait"],
        "vessel": "vial",
        "volume": 20000,
        "slots": 1,
    },
    "ika_plate_rctdigital": {
        "name": "Hotplate stirrer (RCT digital)",
        "operations": ["load", "heat", "mix", "wait"],
        "vessel": "reservoir",
        "volume": 250000,
        "slots": 1,
        "temps": (20, 120),
    },
    "ika_ks4000": {
        "name": "Incubated shaker (KS 4000 i)",
        "operations": ["load", "heat", "mix", "wait"],
        "vessel": "plate",
        "volume": 2000,
        "slots": 4,
        "temps": (20, 80),
    },
    "eppendorf_5910ri": {
        "name": "Centrifuge (5910 Ri)",
        "operations": ["load", "wait"],
        "vessel": "tube",
        "volume": 50000,
        "slots": 4,
        "temps": (4, 40),
    },
    "binder_fd056": {
        "name": "Drying oven (FD 56)",
        "operations": ["load", "heat", "wait"],
        "vessel": "vial",
        "volume": 20000,
        "slots": 6,
        "temps": (20, 120),
    },
    "bmg_clariostarplus": {
        "name": "Plate reader (CLARIOstar Plus)",
        "operations": ["load", "read", "wait"],
        "vessel": "plate",
        "volume": 300,
        "slots": 1,
        "temps": (20, 45),
    },
    "opentrons_flex_single_5_1000ul": {
        "name": "Liquid handler (Opentrons Flex)",
        "operations": ["load", "mix", "wait"],
        "vessel": "plate",
        "volume": 2000,
        "slots": 11,
        "deck": "flex",
        # The deck sits left of centre in this model: the touchscreen is on its right.
        "deck_at": (-0.06, 0.03),
        "consumables": [{"name": "Pipette tips", "used_by": "mix", "per_use": 1, "stock": 96}],
    },
    "azenta_automated_roll_heat_sealer_a4s": {
        "name": "Plate sealer (a4S)",
        "operations": ["load", "heat", "wait"],
        "vessel": "plate",
        "volume": 300,
        "slots": 1,
        "temps": (20, 120),
        "consumables": [{"name": "Seal film", "used_by": "heat", "per_use": 1, "stock": 100}],
    },
    "brooks_preciseflex_400": {
        "name": "Transfer arm (PreciseFlex 400)",
        "operations": ["transfer", "wait"],
    },
}

# First matching kind wins; an instrument matching none is treated as an analyser.
KINDS = [
    (r"robot arm|transfer arm|sample-transfer", {"operations": ["transfer", "wait"]}),
    (
        r"liquid-handl|pipett|dispens",
        {
            "operations": ["load", "mix", "wait"],
            "vessel": "plate",
            "volume": 2000,
            "slots": 4,
            "consumables": [{"name": "Pipette tips", "used_by": "mix", "per_use": 1, "stock": 96}],
        },
    ),
    (
        r"microplate|plate reader|plate washer",
        {"operations": ["load", "read", "wait"], "vessel": "plate", "volume": 300, "slots": 1},
    ),
    (
        r"centrifuge",
        {"operations": ["load", "wait"], "vessel": "tube", "volume": 50000, "slots": 4},
    ),
    (
        r"hotplate|heated stirr|incubated shak|stirred reactor",
        {
            "operations": ["load", "heat", "mix", "wait"],
            "vessel": "vial",
            "volume": 20000,
            "slots": 1,
            "temps": (20, 120),
        },
    ),
    (
        r"oven|furnace|incubator|heater|heating|dryer|digest|reactor|synthesi|sealer|"
        r"circulator|thermostat|bath|evaporator",
        {
            "operations": ["load", "heat", "wait"],
            "vessel": "vial",
            "volume": 20000,
            "slots": 1,
            "temps": (20, 120),
        },
    ),
    (
        r"shaker|stirrer|mixer|mill|homogeni|vortex|sonicat|ultrasonic|blender",
        {"operations": ["load", "mix", "wait"], "vessel": "vial", "volume": 20000, "slots": 1},
    ),
    (
        r"refrigerator|freezer|cabinet|desiccator|glovebox|hood|storage",
        {"operations": ["load", "wait"], "vessel": "vial", "volume": 20000, "slots": 8},
    ),
]
ANALYSER = {"operations": ["load", "read", "wait"], "vessel": "vial", "volume": 2000, "slots": 1}
COLORS = ["#d9dcde", "#c9ced1", "#466e7d", "#365445", "#b78047", "#5a6470"]


def defaults(row):
    name = f"{row['name']} ({row['model']})"
    if len(name) > 80:
        name = row["name"][:80]
    kind = next(
        (spec for pattern, spec in KINDS if re.search(pattern, row["name"], re.I)), ANALYSER
    )
    return {**kind, "name": name}


def entry(row):
    name = row["name"]
    if name[1:2].islower():  # keep acronyms such as HPLC
        name = name[0].lower() + name[1:]
    title = f"{row['maker']} {row['model']} {name}"
    spec = FEATURED.get(row["slug"]) or defaults(row)
    twin = footprint_spec(
        row["size_m"],
        COLORS[sum(map(ord, row["slug"])) % len(COLORS)],
        spec,
        f"The footprint is one box with the overall size of the ChemLab-Assets model of the "
        f"{title[:200]} ({LICENSE}, non-commercial use only)"
        + (
            "; arm paths stay clear of boxes measured from that model. It is reconstructed "
            if row["slug"] in _measured()
            else ". That model is reconstructed "
        )
        + "from public documents, not manufacturer CAD. Operations, vessel, volume, slots "
        "and limits are Academy teaching defaults, not manufacturer specifications or "
        "ChemLab behaviour. Correct them for your instrument before confirming.",
    )
    return {
        "label": title,
        "provider": "MBZUAI ChemLab-Assets",
        "maker": row["maker"],
        "model": row["model"],
        "domain": row["domain_name"],
        "featured": row["slug"] in FEATURED,
        "license": LICENSE,
        "attribution": f"{title} model © MBZUAI, {LICENSE}, via ChemLab-Assets",
        "repo": REPO,
        "revision": REVISION,
        "path": row["path"],
        "url": f"https://huggingface.co/datasets/{REPO}/tree/{REVISION}/{row['path']}",
        "mesh": mesh(row["slug"]),
        "spec": twin,
    }


CHEMLAB = {row["slug"]: entry(row) for row in SNAPSHOT["instruments"]}


def provenance(asset_id):
    """Attribution and the drawn model stored on a twin; exports never resolve them."""
    asset = CHEMLAB[asset_id]
    return {"id": asset_id, **{k: v for k, v in asset.items() if k != "spec"}}
