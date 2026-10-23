"""Operator-only, bounded browser commissioning; never grants worker qualification.

No resources are created. Cloud authorization is an explicit administrative write.
"""

import argparse
import json
import time
from pathlib import Path
from uuid import UUID

from pydantic import Field

from .models import StrictModel
from .store import Conflict, Write

PARTITION = "system#commissioning"
KEY = "active"


class CommissioningRequest(StrictModel):
    grant_id: UUID
    subject: str = Field(min_length=1, max_length=128)
    worker_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    engine_version: str = Field(pattern=r"^[a-f0-9]{40}$")
    asset_version: str = Field(pattern=r"^[a-f0-9]{40}$")
    duration_seconds: int = Field(default=1800, ge=300, le=3600, strict=True)
    max_runs: int = Field(default=2, ge=1, le=2, strict=True)


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
    return grant


def authorize(store, request, *, clock=time.time):
    """CAS authorization separate from qualified flag and global execution gate."""
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


def reserve(grant, run_id):
    if len(grant["run_ids"]) >= grant["request"]["max_runs"]:
        raise ValueError("Commissioning run limit reached")
    updated = {**grant, "version": grant["version"] + 1, "run_ids": [*grant["run_ids"], run_id]}
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
