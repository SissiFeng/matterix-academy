"""Instruments with a registered 3D model from the synthesis workcell assets.

A twin started here keeps the usual box footprint for planning, sized to the model's
envelope, and records which registered model the web app draws in its place. The models
and their sources are listed in `workcell_assets.json`; nothing here is manufacturer CAD.
Operations, vessel, volume and slots are Academy teaching defaults.
"""

from functools import cache

from .simready import footprint_spec
from .workcell_assets import registry

GITHUB = "https://github.com"

# Model envelopes in metres, (x, y, z) Z-up, as drawn by the web app. The Opentrons Flex
# comes from ChemLab-Assets, which has its own model.
DEVICES = {
    "opentrons-ot2": (
        "ot2-teaching-model",
        "Opentrons OT-2 liquid-handling robot",
        "Opentrons",
        (0.633, 0.57, 0.66),
        "#3c4046",
        {
            "name": "Opentrons OT-2",
            "operations": ["load", "mix", "wait"],
            "vessel": "plate",
            "volume": 2000,
            "slots": 4,
            "consumables": [{"name": "300 µL tips", "used_by": "mix", "per_use": 1, "stock": 96}],
        },
    ),
    "ur5e-2f140": (
        "ur5e-robotiq-2f140",
        "UR5e arm with Robotiq 2F-140 gripper on a pedestal",
        "Universal Robots, Robotiq",
        # The pedestal the planner mounts the arm on, as in the transfer robot template.
        (0.16, 0.16, 0.5775),
        "#7b8794",
        {"name": "UR5e arm", "operations": ["transfer", "wait"]},
    ),
    "precision-balance": (
        "precision-balance-teaching-model",
        "Top-loading precision balance",
        "Academy",
        (0.21, 0.3, 0.098),
        "#e9ecee",
        {
            "name": "Precision balance",
            "operations": ["load", "read", "wait"],
            "vessel": "plate",
            "volume": 2000,
            "slots": 1,
        },
    ),
}


MESHES = {
    "ot2-teaching-model": {"kind": "ot2"},
    "precision-balance-teaching-model": {"kind": "balance"},
    "ur5e-robotiq-2f140": {"kind": "ur5e"},
}


def _entry(model_id, label, maker, size, color, spec):
    asset = next(a for a in registry().assets if a.id == model_id).model_dump()
    source = asset["sources"][0]
    revision = source["commit"] or "main"
    twin = footprint_spec(
        size,
        color,
        spec,
        f"Planning geometry is one box with the envelope of the registered '{asset['name']}' "
        f"model ({asset['license']}); the 3D view draws the model itself. It is not "
        "manufacturer CAD. Operations, vessel, volume and slots are Academy teaching "
        "defaults; correct them for your instrument before confirming.",
    )
    return {
        "label": label,
        "provider": maker,
        "license": asset["license"],
        "attribution": f"{asset['name']} model, {asset['license']}, from {source['repository']}",
        "repo": source["repository"],
        "revision": revision,
        "path": source["paths"][0],
        "url": f"{GITHUB}/{source['repository']}/tree/{revision}/{source['paths'][0]}",
        "mesh": {**MESHES[model_id], "asset": model_id},
        "featured": True,
        "domain": "Workcell model",
        "spec": twin,
    }


@cache
def catalog():
    return {key: _entry(*row) for key, row in DEVICES.items()}


def provenance(asset_id):
    """Attribution stored on a twin, with the registered model the web app draws."""
    asset = catalog()[asset_id]
    return {"id": asset_id, **{k: v for k, v in asset.items() if k not in {"spec", "featured"}}}
