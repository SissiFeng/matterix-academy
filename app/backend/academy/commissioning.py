"""Operator-only, bounded browser commissioning; never grants worker qualification.

No resources are created. Cloud authorization is an explicit administrative write.
"""

import argparse
import json
import time
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, model_serializer, model_validator

from .models import Experiment, StrictModel
from .native_studio import STUDIO, StudioCapability, studio_preflight, studio_scene
from .recipes import MixingPlan, parse_plan
from .remote_run import workflow_digest
from .runtime_inventory import PROFILE
from .store import Conflict, Write

PARTITION = "system#commissioning"
KEY = "active"


class ApprovedStudioPlan(StrictModel):
    experiment: Experiment
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def exact_saved_plan(self):
        if self.experiment.course_id != STUDIO:
            raise ValueError("Studio commissioning requires saved Workflow Studio plans")
        if workflow_digest(self.experiment) != self.plan_hash:
            raise ValueError("Approved Studio hash must bind the complete normalized plan")
        return self


class StudioCommissioningScope(StrictModel):
    """Two reviewed plans, not a general scene permission or qualification."""

    scene: Literal["workflow-studio-flex", "workflow-studio-ot2"]
    instrument: Literal["flex", "ot2"]
    capability: StudioCapability
    plans: list[ApprovedStudioPlan] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def bounded_scene(self):
        if (
            self.scene != f"workflow-studio-{self.instrument}"
            or self.capability.scene != self.scene
            or self.capability.instrument != self.instrument
        ):
            raise ValueError("Commissioning scene, instrument and capability must agree")
        if not self.capability.viewport or not {"liquid_volume", "tip_state"} <= set(
            self.capability.observed
        ):
            raise ValueError("Studio commissioning requires a viewport and native observations")
        if len({plan.plan_hash for plan in self.plans}) != 2:
            raise ValueError("Approve two distinct Studio plans in execution order")
        for approved in self.plans:
            if studio_scene(approved.experiment) != self.scene:
                raise ValueError("Both approved plans must use the selected instrument and scene")
            if studio_preflight(approved.experiment, self.capability):
                raise ValueError("Each exact approved plan must pass the declared scene preflight")
        return self


class CommissioningRequest(StrictModel):
    grant_id: UUID
    subject: str = Field(min_length=1, max_length=128)
    worker_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    engine_version: str = Field(pattern=r"^[a-f0-9]{40}$")
    asset_version: str = Field(pattern=r"^[a-f0-9]{40}$")
    duration_seconds: int = Field(default=1800, ge=300, le=3600, strict=True)
    max_runs: int = Field(default=2, ge=1, le=2, strict=True)
    studio: StudioCommissioningScope | None = None

    @model_serializer(mode="wrap")
    def preserve_existing_grants(self, handler):
        scope = handler(self)
        if self.studio is None:
            scope.pop("studio", None)
        return scope

    @model_validator(mode="after")
    def bind_studio_runtime(self):
        if self.studio is not None and (
            self.max_runs != 2
            or (self.engine_version, self.asset_version)
            != (PROFILE["engine_commit"], PROFILE["asset_commit"])
        ):
            raise ValueError("Studio commissioning requires two runs and the reviewed source pins")
        return self


def permits_plan(grant, plan, *, next_only=False):
    """Check exact plan authority; time, owner and worker checks belong to active_grant."""
    try:
        request = CommissioningRequest.model_validate(grant["request"])
        plan = parse_plan(plan.model_dump(mode="json"))
        if request.studio is None:
            return plan == MixingPlan()
        approved = request.studio.plans
        if next_only:
            index = len(grant["run_ids"])
            if index >= len(approved):
                return False
            approved = [approved[index]]
        return any(
            plan == entry.experiment and workflow_digest(plan) == entry.plan_hash
            for entry in approved
        )
    except (ValueError, KeyError, TypeError, AttributeError):
        return False


def active_grant(store, now, *, subject=None, worker=None, run=None):
    grant = store.get(PARTITION, KEY)
    if not grant or grant.get("expires", 0) <= now:
        return None
    if subject is not None and grant["request"]["subject"] != subject:
        return None
    scope = grant["request"]
    worker = worker or store.get("system#workers", scope["worker_id"])
    if not worker or (
        worker["worker_id"] != scope["worker_id"]
        or worker["engine_version"] != scope["engine_version"]
        or worker["asset_version"] != scope["asset_version"]
        or worker.get("revoked", True)
        or worker.get("credential_expires", 0) <= now
    ):
        return None
    if run is not None and (
        run.get("commissioning_id") != scope["grant_id"]
        or run["owner"] != scope["subject"]
        or run["run_id"] not in grant["run_ids"]
    ):
        return None
    if run is not None and scope.get("studio") is not None:
        try:
            plan = parse_plan(run["plan"])
            index = grant["run_ids"].index(run["run_id"])
            approved = scope["studio"]["plans"][index]
            if (
                not permits_plan(grant, plan)
                or run.get("scene") != scope["studio"]["scene"]
                or run.get("plan_hash") != approved["plan_hash"]
                or workflow_digest(plan) != approved["plan_hash"]
                or grant.get("run_plan_hashes", {}).get(run["run_id"]) != approved["plan_hash"]
            ):
                return None
        except (ValueError, KeyError, TypeError, IndexError):
            return None
    return grant


def authorize(store, request, *, clock=time.time):
    """CAS authorization separate from qualified flag and global execution gate."""
    # Revalidate operator input even when a caller constructed it using model_copy.
    request = CommissioningRequest.model_validate(request.model_dump(mode="json"))
    scope = request.model_dump(mode="json")
    old = store.get(PARTITION, KEY)
    if old and old["request"]["grant_id"] == scope["grant_id"]:
        if old["request"] != scope:
            raise Conflict
        return old  # Lost acknowledgement never extends the window or resets its quota.
    if old:
        for run_id in old["run_ids"]:
            run = store.get("system#runs", run_id)
            if run and not (run.get("cleanup") or {}).get("reset_verified"):
                raise ValueError(
                    "Reconcile every previous commissioning run before replacing its grant"
                )
        if old["expires"] > clock():
            raise ValueError("A commissioning grant is already active")
    worker = store.get("system#workers", request.worker_id)
    if not worker or worker.get("revoked", True) or worker.get("active_run"):
        raise ValueError("Commissioning requires an enrolled, idle, nonrevoked worker")
    if worker.get("credential_expires", 0) <= clock() or (
        worker["engine_version"],
        worker["asset_version"],
    ) != (request.engine_version, request.asset_version):
        raise ValueError("Worker versions/credential do not match the requested host")
    grant = {
        "version": (old["version"] if old else 0) + 1,
        "request": scope,
        "created_at": clock(),
        "expires": clock() + request.duration_seconds,
        "run_ids": [],
    }
    if request.studio is not None:
        grant["run_plan_hashes"] = {}
    # Verify the worker revision in the same transaction; do not promote its authority.
    store.transact(
        [
            Write(PARTITION, KEY, grant, old["version"] if old else None),
            Write(
                "system#workers",
                request.worker_id,
                {**worker, "version": worker["version"] + 1},
                worker["version"],
            ),
        ]
    )
    return grant


def reserve(grant, run_id, plan=None):
    if len(grant["run_ids"]) >= grant["request"]["max_runs"]:
        raise ValueError("Commissioning run limit reached")
    if run_id in grant["run_ids"]:
        raise ValueError("Commissioning run is already reserved")
    studio = grant["request"].get("studio") is not None
    if (studio or plan is not None) and not permits_plan(grant, plan, next_only=True):
        raise ValueError("Commissioning permits only the next exact operator-approved plan")
    updated = {**grant, "version": grant["version"] + 1, "run_ids": [*grant["run_ids"], run_id]}
    if studio:
        updated["run_plan_hashes"] = {
            **grant.get("run_plan_hashes", {}),
            run_id: workflow_digest(plan),
        }
    return Write(PARTITION, KEY, updated, grant["version"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["authorize", "inspect"])
    parser.add_argument("--expected-account-id", required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--runtime-report", type=Path)
    args = parser.parse_args()
    import boto3

    from .store import DynamoStore
    from .worker_admin import operator_identity

    if args.action == "authorize":
        if not args.request:
            parser.error("--request with the exact learner JWT subject and host pins is required")
        if not args.runtime_report:
            parser.error("--runtime-report from the prepared GPU host is required")
        inventory = json.loads(args.runtime_report.read_text())
        from .runtime_inventory import PROFILE, REQUIRED_CHECKS

        if (
            inventory.get("ready_for_commissioning") is not True
            or inventory.get("profile") != PROFILE
            or not REQUIRED_CHECKS <= inventory.get("checks", {}).keys()
            or not all(inventory["checks"][key] is True for key in REQUIRED_CHECKS)
        ):
            parser.error("Host fingerprint must pass the pinned internal Flex profile first")
        request = CommissioningRequest.model_validate_json(args.request.read_text())
        if (request.engine_version, request.asset_version) != (
            PROFILE["engine_commit"],
            PROFILE["asset_commit"],
        ):
            parser.error("Commissioning request must bind the reviewed internal Flex source pins")
        operator_identity(boto3.client("sts").get_caller_identity(), args.expected_account_id)
        store = DynamoStore(args.table)
        grant = authorize(store, request)
        print(
            json.dumps(
                {"grant_id": str(request.grant_id), "expires": grant["expires"], "qualified": False}
            )
        )
    else:
        operator_identity(boto3.client("sts").get_caller_identity(), args.expected_account_id)
        store = DynamoStore(args.table)
        grant = store.get(PARTITION, KEY)
        # Do not expose learner identity or machine credentials in ordinary CLI output.
        print(
            json.dumps(
                {
                    "active": bool(grant and grant["expires"] > time.time()),
                    "run_ids": grant["run_ids"] if grant else [],
                }
            )
        )


if __name__ == "__main__":
    main()
