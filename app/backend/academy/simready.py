"""Curated NVIDIA SimReady Central assets usable as starting points for teaching twins.

Each entry pins a dataset revision and records the published bounding box. Academy never
downloads or references the third-party USD: a twin keeps one box with that footprint, and
its operations, vessel, volume, slots and limits are Academy teaching defaults, not
manufacturer specifications. All listed datasets are CC-BY-4.0, so attribution travels
with the twin and its exports.
"""

from .decks import deck_sites
from .simple_twins import Consumable, Container, Limits, Part, Resource, TwinSpec

LICENSE = "CC-BY-4.0"


def footprint_spec(size_zup, color, spec, assumptions):
    """One-box twin from the bounding box (x, y, z) of a Z-up asset in metres."""
    x, y, z = size_zup
    size = (x, z, y)  # Academy twins are Y-up
    return TwinSpec(
        name=spec["name"],
        parts=[Part(size=size, position=(0, size[1] / 2, 0), color=color)],
        operations=spec["operations"],
        container=Container(vessel=spec.get("vessel", "none"), max_volume_ul=spec.get("volume", 0)),
        resource=Resource(slots=spec.get("slots", 0)),
        consumables=[Consumable(**c) for c in spec.get("consumables", ())],
        limits=Limits(
            min_temp_c=spec.get("temps", (4, 120))[0],
            max_temp_c=spec.get("temps", (4, 120))[1],
            max_duration_s=600,
        ),
        assumptions=assumptions,
        sites=deck_sites(spec["deck"]) if spec.get("deck") else [],
    ).model_dump(mode="json")


def entry(label, provider, repo, revision, path, size_zup, color, spec):
    """size_zup is the scaled bounding box (x, y, z) of a Z-up SimReady asset in metres."""
    twin = footprint_spec(
        size_zup,
        color,
        spec,
        f"Geometry is one box with the bounding box of the SimReady asset "
        f"'{label}' by {provider} ({LICENSE}). Operations, vessel, volume, slots and limits "
        "are Academy teaching defaults, not manufacturer specifications. Correct them for "
        "your instrument before confirming.",
    )
    return {
        "label": label,
        "provider": provider,
        "license": LICENSE,
        "attribution": f"{label} © {provider}, {LICENSE}, via NVIDIA SimReady Central",
        "repo": repo,
        "revision": revision,
        "path": path,
        "url": f"https://huggingface.co/datasets/{repo}/blob/{revision}/{path}",
        "spec": twin,
    }


SIMREADY = {
    "forgecad-laboratory-incubator": entry(
        "Laboratory incubator",
        "ForgeCAD",
        "ForgeCAD/simready-assets",
        "aaa5a8ddae66537c9135817044b9c78d5b952b44",
        "laboratory_incubator/simready_usd/laboratory_incubator.usda",
        (0.529, 0.633, 0.65),
        "#c9ced1",
        {
            "name": "Incubator",
            "operations": ["load", "heat", "wait"],
            "vessel": "plate",
            "volume": 2000,
            "slots": 4,
            "temps": (20, 60),
        },
    ),
    "forgecad-microplate-reader": entry(
        "Microplate reader",
        "ForgeCAD",
        "ForgeCAD/simready-assets",
        "959549e3f18a6ca6151b08d0b8cfe50a354e3557",
        "microplate_reader/simready_usd/microplate_reader.usda",
        (0.36, 0.387, 0.212),
        "#466e7d",
        {
            "name": "Microplate reader",
            "operations": ["load", "read", "wait"],
            "vessel": "plate",
            "volume": 300,
            "slots": 1,
        },
    ),
    "nvidia-dispensing-system": entry(
        "Dispensing system",
        "NVIDIA",
        "nvidia/simready-assets",
        "653d91e182011f357cf1644013cc94ddf194d349",
        "serviceTool_dispensing_system_a01/simready_usd/sm_serviceTool_dispensing_system_a01_01.usd",
        (0.751, 0.836, 0.742),
        "#365445",
        {
            "name": "Dispensing station",
            "operations": ["load", "mix", "wait"],
            "vessel": "plate",
            "volume": 2000,
            "slots": 2,
            "consumables": [{"name": "Dispense tips", "used_by": "mix", "per_use": 1, "stock": 96}],
        },
    ),
    "nvidia-undercounter-refrigerator": entry(
        "Under-counter refrigerator",
        "NVIDIA",
        "nvidia/simready-assets",
        "653d91e182011f357cf1644013cc94ddf194d349",
        "refrigerator_f01/simready_usd/sm_refrigerator_f01_01.usd",
        (0.685, 0.75, 0.971),
        "#dfe3e6",
        {
            "name": "Sample refrigerator",
            "operations": ["load", "wait"],
            "vessel": "plate",
            "volume": 2000,
            "slots": 8,
            "temps": (4, 8),
        },
    ),
    "franka-fr3": entry(
        "Franka Research 3 arm",
        "Franka Robotics",
        "frankarobotics/simready-assets",
        "b54ce583ec4266d4b980c3bbc55c1019107311af",
        "fr3v2_1/simready_usd/fr3v2_1.usda",
        (0.675, 0.26, 0.779),
        "#e8e8e8",
        {"name": "Collaborative arm (FR3)", "operations": ["transfer", "wait"]},
    ),
    "fanuc-crx-10ia": entry(
        "CRX-10iA collaborative robot",
        "FANUC",
        "FANUC-CORPORATION/SimReady-Assets",
        "449b304714f21f81e552423fd4f6ea3a821c94c2",
        "crx10ia/simready_usd/crx10ia.usd",
        (0.802, 0.393, 0.855),
        "#3c3f42",
        {"name": "Collaborative arm (CRX-10iA)", "operations": ["transfer", "wait"]},
    ),
}


def provenance(asset_id):
    """Attribution stored on a twin; never a reference that exports resolve."""
    asset = SIMREADY[asset_id]
    return {"id": asset_id, **{k: v for k, v in asset.items() if k != "spec"}}
