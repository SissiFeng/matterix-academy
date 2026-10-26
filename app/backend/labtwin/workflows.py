"""Registered instrument workflows shared by every runner, gateway and control plane.

A plan is accepted only when it is byte-identical (by canonical fingerprint) to
the plan this module generates for its profile and run ID. Any change to these
functions changes what a gateway will execute, so they are versioned with the
contract and must be identical on the control plane, simulation and device side.
"""

from __future__ import annotations

import copy
import math

from .models import Operation
from .network import sila_tunnel_host
from .wire import fingerprint, plain

# ---------------------------------------------------------------- OT-2 home/readback

OT2_SCHEMA = "ot2.home-check/1"
OT2_MATTERIX_REVISION = "f38d10d86a91c86ddc0e21db1927b68565d8378f"
OT2_ASSETS_REVISION = "98da840f8bb2770ac5ec82a483dca3c4cf635206"


def ot2_profile_template():
    return {
        "schema": "ot2.profile/1",
        "device_id": "ot2-lab",
        "task": "Matterix-OT2-DualMulti-Home-v1",
        "workflow": "move_home",
        "matterix_revision": OT2_MATTERIX_REVISION,
        "assets_revision": OT2_ASSETS_REVISION,
        "pipettes": {
            "left": {"model": "p10_multi_v1.6", "channels": 8},
            "right": {"model": "p300_multi_v2.0", "channels": 8},
            "identity_source": "operator_reported",
        },
        "real": {"backend": "ot2-sila", "host": "127.0.0.1", "port": 50051, "server_uuid": ""},
    }


def ot2_validate_profile(profile, *, hardware=False):
    template = ot2_profile_template()
    if not isinstance(profile, dict) or set(profile) != set(template):
        raise ValueError("Expected the OT-2 profile fields")
    for key in ("schema", "task", "workflow", "matterix_revision", "assets_revision", "pipettes"):
        if profile[key] != template[key]:
            raise ValueError(f"Unsupported OT-2 {key}")
    if not isinstance(profile["device_id"], str) or not profile["device_id"].strip():
        raise ValueError("OT-2 device_id is required")
    real = profile["real"]
    if not isinstance(real, dict) or set(real) != set(template["real"]) or real["backend"] != "ot2-sila":
        raise ValueError("Invalid OT-2 connector binding")
    sila_tunnel_host(real["host"])
    if type(real["port"]) is not int or not 1 <= real["port"] <= 65535:
        raise ValueError("Invalid SiLA port")
    if not isinstance(real["server_uuid"], str) or (hardware and not real["server_uuid"].strip()):
        raise ValueError("Check the connector and bind its server UUID before real execution")
    return profile


def ot2_make_plan(profile, run_id):
    ot2_validate_profile(profile)
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id is required")
    ops = [
        Operation(run_id, "01-home", profile["device_id"], "home", {"axes": "XYZABC"}, OT2_SCHEMA),
        Operation(run_id, "02-readback", profile["device_id"], "read_position", {}, OT2_SCHEMA),
    ]
    return {
        "binding": {
            "schema": OT2_SCHEMA,
            "run_id": run_id,
            "device_id": profile["device_id"],
            "profile_sha256": fingerprint(profile),
        },
        "profile": copy.deepcopy(profile),
        "operations": plain(ops),
    }


def ot2_validate_plan(plan):
    if not isinstance(plan, dict) or set(plan) != {"binding", "profile", "operations"}:
        raise ValueError("Invalid OT-2 plan")
    if fingerprint(plan) != fingerprint(ot2_make_plan(plan["profile"], plan["binding"]["run_id"])):
        raise ValueError("OT-2 plan differs from its reviewed workflow")
    return plan


def ot2_validate_operation(operation, profile):
    if plain(operation) not in ot2_make_plan(profile, operation.run_id)["operations"]:
        raise ValueError("Operation is not part of the OT-2 home/readback workflow")


# ---------------------------------------------------------------- Flex single-tip cycle

FLEX_MATTERIX_REVISION = "18a96b78ee989fbf4e480e9db6a588c148c6adbe"
FLEX_ASSETS_REVISION = "c57f12a04079a5f99405e1fcb818a3b7ccc52e5b"
FLEX_CONNECTOR_REVISION = "2639016ee9f234949aaf596c2ab2b93694eb0e0b"
FLEX_TASK = "Matterix-Flex-Pipetting-v1"
FLEX_WORKFLOW = "tip_pickup_and_release"
FLEX_SCHEMA = "flex.tip-cycle/1"


def flex_profile_template():
    """Return editable configuration with no fabricated hardware coordinates."""
    return {
        "schema": "flex.profile/1",
        "device_id": "flex-lab",
        "mount": "LEFT",
        "task": FLEX_TASK,
        "workflow": FLEX_WORKFLOW,
        "matterix_revision": FLEX_MATTERIX_REVISION,
        "assets_revision": FLEX_ASSETS_REVISION,
        "real": {
            "backend": "flex-sila",
            "host": "127.0.0.1",
            "port": 50051,
            "server_uuid": "",
            "pipette_id": "",
            "pipette_model": "",
            "calibration_revision": "",
            "tiprack": "",
            "tip_length_mm": None,
            "speed_mm_s": 30.0,
            "pickup": None,
            "pickup_clearance": None,
            "drop": None,
            "drop_clearance": None,
            "park": None,
        },
    }


def _number(value, low, high, name):
    if type(value) not in (float, int) or not math.isfinite(value) or not low < value <= high:
        raise ValueError(f"{name} must be greater than {low} and at most {high}")


def flex_validate_profile(profile, *, hardware=False):
    """Reject unsupported profiles and incomplete physical bindings before dispatch."""
    template = flex_profile_template()
    if not isinstance(profile, dict) or set(profile) != set(template):
        raise ValueError("Profile must contain exactly the flex.profile/1 fields")
    for key in ("schema", "mount", "task", "workflow", "matterix_revision", "assets_revision"):
        if profile[key] != template[key]:
            raise ValueError(f"Unsupported {key}: this release binds the pinned left single-tip Flex workflow")
    if not isinstance(profile["device_id"], str) or not profile["device_id"].strip():
        raise ValueError("device_id is required")
    real = profile["real"]
    if not isinstance(real, dict) or set(real) != set(template["real"]):
        raise ValueError("Invalid real backend configuration fields")
    if real["backend"] != "flex-sila":
        raise ValueError("This launcher supports flex-sila; inject another Adapter in the runner API")
    if real["host"] not in ("127.0.0.1", "localhost"):
        raise ValueError("Use a localhost SSH tunnel for the SiLA connection")
    if type(real["port"]) is not int or not 1 <= real["port"] <= 65535:
        raise ValueError("Invalid connector port")
    _number(real["speed_mm_s"], 0, 100, "speed_mm_s")
    for key in ("server_uuid", "pipette_id", "pipette_model", "calibration_revision", "tiprack"):
        if not isinstance(real[key], str) or (hardware and not real[key].strip()):
            raise ValueError(f"Qualified hardware configuration requires {key}")
    if real["tip_length_mm"] is not None:
        _number(real["tip_length_mm"], 0, 100, "tip_length_mm")
    elif hardware:
        raise ValueError("Measured tip_length_mm is required")
    for key in ("pickup", "pickup_clearance", "drop", "drop_clearance", "park"):
        point = real[key]
        if point is None and not hardware:
            continue
        if not isinstance(point, dict) or set(point) != {"x", "y", "z"}:
            raise ValueError(f"{key} requires calibrated x/y/z in deck mm")
        for value in point.values():
            if type(value) not in (float, int) or not math.isfinite(value):
                raise ValueError(f"{key} coordinates must be finite numbers")
    for target, clearance in (("pickup", "pickup_clearance"), ("drop", "drop_clearance")):
        low, high = real[target], real[clearance]
        if low is not None and high is not None:
            if low["x"] != high["x"] or low["y"] != high["y"] or high["z"] <= low["z"]:
                raise ValueError(f"{clearance} must be vertically above {target}")
    clearances = [real[key] for key in ("pickup_clearance", "drop_clearance", "park")]
    if all(point is not None for point in clearances) and len({point["z"] for point in clearances}) != 1:
        raise ValueError("Pickup/drop clearance and park must share a reviewed travel height")
    return profile


def flex_make_plan(profile, run_id):
    """Bind preview and both adapters to the same immutable semantic operations."""
    flex_validate_profile(profile)
    operations = [
        Operation(
            run_id, "01-pickup", profile["device_id"], "pick_up_tip", {"mount": "LEFT", "tip": "Tips__A1"}, FLEX_SCHEMA
        ),
        Operation(
            run_id, "02-drop", profile["device_id"], "drop_tip", {"mount": "LEFT", "tip": "Tips__A1"}, FLEX_SCHEMA
        ),
        Operation(run_id, "03-park", profile["device_id"], "park", {"mount": "LEFT"}, FLEX_SCHEMA),
    ]
    return {
        "binding": {
            "schema": FLEX_SCHEMA,
            "run_id": run_id,
            "device_id": profile["device_id"],
            "profile_sha256": fingerprint(profile),
        },
        "profile": copy.deepcopy(profile),
        "operations": plain(operations),
    }


def flex_validate_plan(plan):
    """Require the exact registered workflow, including order, identities and profile hash."""
    if not isinstance(plan, dict) or set(plan) != {"binding", "profile", "operations"}:
        raise ValueError("Invalid Flex plan envelope")
    expected = flex_make_plan(plan["profile"], plan["binding"]["run_id"])
    if fingerprint(plan) != fingerprint(expected):
        raise ValueError("Plan differs from its registered workflow or reviewed binding")
    return plan


def flex_validate_operation(operation, profile):
    candidates = flex_make_plan(profile, operation.run_id)["operations"]
    if plain(operation) not in candidates:
        raise ValueError("Operation is not an exact member of the registered Flex workflow")


# ---------------------------------------------------------------- registry

REGISTRY = {
    "ot2.profile/1": {
        "model": "opentrons_ot2",
        "workflow_schema": OT2_SCHEMA,
        "template": ot2_profile_template,
        "validate_profile": ot2_validate_profile,
        "make_plan": ot2_make_plan,
        "validate_plan": ot2_validate_plan,
        "validate_operation": ot2_validate_operation,
    },
    "flex.profile/1": {
        "model": "opentrons_flex",
        "workflow_schema": FLEX_SCHEMA,
        "template": flex_profile_template,
        "validate_profile": flex_validate_profile,
        "make_plan": flex_make_plan,
        "validate_plan": flex_validate_plan,
        "validate_operation": flex_validate_operation,
    },
}
MODELS = {entry["model"]: schema for schema, entry in REGISTRY.items()}


def entry(profile):
    schema = profile.get("schema") if isinstance(profile, dict) else None
    if schema not in REGISTRY:
        raise ValueError("Choose a supported OT-2 or Flex profile")
    return REGISTRY[schema]


def model(profile):
    return entry(profile)["model"]


def profile_template(instrument_model):
    if instrument_model not in MODELS:
        raise ValueError("Unknown instrument model")
    return REGISTRY[MODELS[instrument_model]]["template"]()


def validate_profile(profile, *, hardware=False):
    return entry(profile)["validate_profile"](profile, hardware=hardware)


def make_plan(profile, run_id):
    return entry(profile)["make_plan"](profile, run_id)


def validate_plan(plan):
    if not isinstance(plan, dict) or "profile" not in plan:
        raise ValueError("Plan must include an instrument profile")
    return entry(plan["profile"])["validate_plan"](plan)


def validate_operation(operation, profile):
    return entry(profile)["validate_operation"](operation, profile)


def qualified_profile(profile):
    """Device/model/calibration identity, excluding only gateway-local routing."""
    value = copy.deepcopy(profile)
    value["real"].pop("host", None)
    value["real"].pop("port", None)
    return value


def plan_identity(plan):
    """Stable workflow/profile identities; the full plan hash also binds its run ID."""
    operations = [{k: v for k, v in op.items() if k != "run_id"} for op in plan["operations"]]
    return {
        "workflow_sha256": fingerprint({"schema": plan["binding"]["schema"], "operations": operations}),
        "qualified_profile_sha256": fingerprint(qualified_profile(plan["profile"])),
        "plan_sha256": fingerprint(plan),
    }
