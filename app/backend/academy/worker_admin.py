"""Operator-only worker enrollment. No credentials are printed or put in Terraform.

Example: AWS_PROFILE=... uv run python -m academy.worker_admin enroll \
  --expected-account-id 247893369214 --table matterix-academy-dev \
  --worker-id lab-1 --engine-version PINNED --asset-version PINNED \
  --credential-file /protected/path/worker.token
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import tempfile
import time
from pathlib import Path
from typing import Literal
from uuid import UUID

import boto3
from pydantic import Field, StrictBool, model_validator

from .models import StrictModel
from .runs import RUNS, TERMINAL, WORKERS, RunService, revised
from .store import Conflict, DynamoStore, Write

REGISTRY = "system#registry"
RECONCILIATIONS = "system#reconciliations"
MAX_WORKERS = 100


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def read_credential(path, worker_id):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 256:
            raise ValueError("Enrollment credential must be a protected regular file (0600)")
        token = file.read().strip()
    if not re.fullmatch(re.escape(worker_id) + r"\.[A-Za-z0-9_-]{64}", token):
        raise ValueError(
            "Existing credential does not match this worker; preserve it for inspection"
        )
    return token


def enrollment_credential(path, worker_id):
    """Publish a complete, durable token before registration; retries reuse it."""
    try:
        return read_credential(path, worker_id)
    except FileNotFoundError:
        pass
    fd, temporary = tempfile.mkstemp(prefix=".worker-enrollment-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as file:
            file.write(worker_id + "." + secrets.token_urlsafe(48) + "\n")
            file.flush()
            os.fsync(file.fileno())
        try:
            # Exclusive publication never overwrites a competing enrollment's token.
            os.link(temporary, path)
        except FileExistsError:
            pass
        sync_directory(path.parent)
    finally:
        os.unlink(temporary)
    return read_credential(path, worker_id)


def enroll(store, worker_id, engine_version, asset_version, credential_file, clock=time.time):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", worker_id):
        raise ValueError("Invalid worker ID")
    if not all(
        isinstance(value, str) and 1 <= len(value) <= 100
        for value in (engine_version, asset_version)
    ):
        raise ValueError("Pinned engine and asset versions are required")
    old = store.get(WORKERS, worker_id)
    path = Path(credential_file)
    if old:
        # A retry must prove it has the original token; never generate a replacement.
        token = read_credential(path, worker_id)
        if (
            not secrets.compare_digest(
                old["token_digest"], hashlib.sha256(token.encode()).hexdigest()
            )
            or (old["engine_version"], old["asset_version"]) != (engine_version, asset_version)
            or old["revoked"]
            or old["credential_expires"] <= clock()
        ):
            raise ValueError("Existing worker differs or is inactive; enroll a new identity")
        return old
    registry = store.get(REGISTRY, "workers")
    if registry is None and store.partition(WORKERS, limit=1):
        raise ValueError(
            "Existing workers require an operator registry-count migration before enrollment"
        )
    count = registry["count"] if registry else 0
    if not isinstance(count, int) or isinstance(count, bool) or not 0 <= count < MAX_WORKERS:
        raise ValueError("Worker registry is full or its count needs operator reconciliation")
    token = enrollment_credential(path, worker_id)
    record = dict(
        version=1,
        worker_id=worker_id,
        credential_version=1,
        token_digest=hashlib.sha256(token.encode()).hexdigest(),
        credential_expires=clock() + 90 * 86400,
        revoked=False,
        qualified=False,
        state="quarantined",
        active_run=None,
        controls=[],
        engine_version=engine_version,
        asset_version=asset_version,
    )
    # A timeout may mean this committed. Keep the file so the next invocation can
    # compare its digest with the registry; never compensate by deleting a token.
    store.transact(
        [
            Write(
                REGISTRY,
                "workers",
                {"version": (registry["version"] if registry else 0) + 1, "count": count + 1},
                registry["version"] if registry else None,
            ),
            Write(WORKERS, worker_id, record, None),
        ]
    )
    return record


class Reconciliation(StrictModel):
    reconciliation_id: UUID
    worker_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    run_id: UUID
    expected_run_version: int = Field(ge=1)
    expected_worker_version: int = Field(ge=1)
    native_session_id: UUID | None
    reset_command_id: UUID | None
    release_command_id: UUID | None
    engine_version: str = Field(min_length=1, max_length=100)
    asset_version: str = Field(min_length=1, max_length=100)
    evidence: Literal["native"]
    report_uri: str = Field(min_length=1, max_length=2048)
    reset_verified: StrictBool
    no_allocation: StrictBool = False
    checks: dict[
        Literal[
            "worker_stopped", "objects", "liquids", "tips", "controllers", "stopped", "released"
        ],
        StrictBool,
    ]

    @model_validator(mode="after")
    def verified(self):
        if (
            not self.reset_verified
            or set(self.checks)
            != {
                "worker_stopped",
                "objects",
                "liquids",
                "tips",
                "controllers",
                "stopped",
                "released",
            }
            or not all(self.checks.values())
        ):
            raise ValueError("Operator recovery requires every native stop/reset/release check")
        identities = (self.native_session_id, self.reset_command_id, self.release_command_id)
        if (self.no_allocation and any(identities)) or (
            not self.no_allocation and not all(identities)
        ):
            raise ValueError(
                "Supply native session/reset/release IDs, or explicitly verify no allocation"
            )
        return self


def operator_identity(identity, expected_account):
    if (
        not re.fullmatch(r"[0-9]{12}", expected_account)
        or identity.get("Account") != expected_account
    ):
        raise ValueError("AWS account does not match the selected deployment")
    if (
        not isinstance(identity.get("Arn"), str)
        or not identity["Arn"].startswith("arn:aws:")
        or f":{expected_account}:" not in identity["Arn"]
    ):
        raise ValueError("An authenticated AWS operator identity is required")


def reconcile(store, data: Reconciliation, identity, expected_account, clock=time.time):
    """IAM operator-only database closeout. Never exposed through worker HTTP routes."""
    operator_identity(identity, expected_account)
    payload = data.model_dump(mode="json")
    key = str(data.reconciliation_id)
    existing = store.get(RECONCILIATIONS, key)
    if existing:
        if existing["request"] != payload:
            raise Conflict
        return
    worker = store.get(WORKERS, data.worker_id)
    service = RunService(store, clock=clock)
    run = service.raw(data.run_id)
    if (
        not worker
        or worker["version"] != data.expected_worker_version
        or run["version"] != data.expected_run_version
        or run.get("worker_id") != data.worker_id
        or worker.get("active_run") != str(data.run_id)
        or run["status"] not in TERMINAL
        or (run.get("cleanup") or {}).get("reset_verified")
    ):
        raise Conflict
    manifest = {"engine_version": data.engine_version, "asset_version": data.asset_version}
    if manifest != run.get("runtime_manifest") or any(worker[k] != v for k, v in manifest.items()):
        raise ValueError("Recovery evidence differs from the claimed runtime")
    native_id = (run.get("binding") or {}).get("native_session_id")
    if native_id:
        if data.no_allocation or str(data.native_session_id) != native_id:
            raise ValueError("Recovery evidence belongs to a different native session")
    elif not data.no_allocation:
        raise ValueError("Unbound runs require verified absence of any remaining allocation")
    receipt = {
        "command_id": str(data.reset_command_id or data.reconciliation_id),
        "native_session_id": native_id,
        **manifest,
        "reset_verified": True,
        "checks": {
            k: data.checks[k] for k in ("objects", "liquids", "tips", "controllers", "stopped")
        },
        "release_verified": True,
    }
    # Keep the unknown/known execution outcome immutable. Every recovery retires
    # the old machine credential, even if it was still valid before the incident.
    store.transact(
        [
            Write(
                RUNS,
                run["run_id"],
                revised(run, cleanup=receipt, operator_reconciliation_id=key, updated_at=clock()),
                run["version"],
            ),
            Write(
                WORKERS,
                data.worker_id,
                revised(
                    worker, revoked=True, qualified=False, state="quarantined", active_run=None
                ),
                worker["version"],
            ),
            *service.release_lock(run),
            Write(
                RECONCILIATIONS,
                key,
                {
                    "version": 1,
                    "request": payload,
                    "account_id": expected_account,
                    "operator_arn": identity["Arn"],
                    "recorded_at": clock(),
                },
                None,
            ),
        ]
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["enroll", "qualify", "revoke", "inspect", "reconcile"])
    parser.add_argument("--expected-account-id", required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--engine-version")
    parser.add_argument("--asset-version")
    parser.add_argument("--credential-file")
    parser.add_argument("--qualification-record")
    parser.add_argument("--reconciliation-record")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", args.worker_id):
        parser.error("worker-id must be a short lowercase machine name")
    identity = boto3.client("sts").get_caller_identity()
    try:
        operator_identity(identity, args.expected_account_id)
    except ValueError as exc:
        parser.error(str(exc))
    store = DynamoStore(args.table)
    old = store.get(WORKERS, args.worker_id)
    if args.action == "enroll":
        if not all([args.engine_version, args.asset_version, args.credential_file]):
            parser.error("Pinned engine/assets and credential-file are required")
        try:
            enroll(
                store, args.worker_id, args.engine_version, args.asset_version, args.credential_file
            )
        except (ValueError, OSError) as exc:
            parser.error(str(exc))
        except Conflict:
            parser.error("Registry changed; retry the same enrollment and credential file")
        print(
            "Worker enrollment confirmed; credential preserved. Enrollment does not grant native qualification."
        )
    elif args.action == "revoke":
        if not old:
            parser.error("Worker does not exist")
        store.put(
            WORKERS, args.worker_id, revised(old, revoked=True, state="quarantined"), old["version"]
        )
        # Reaper also runs every minute; direct reconciliation closes this sooner.
        RunService(store).reap()
        print("Worker revoked; active outcomes quarantined.")
    elif args.action == "inspect":
        if not old:
            parser.error("Worker does not exist")
        run = RunService(store).raw(old["active_run"]) if old.get("active_run") else None
        print(
            json.dumps(
                {
                    "worker_id": args.worker_id,
                    "expected_worker_version": old["version"],
                    "revoked": old["revoked"],
                    "credential_expires": old["credential_expires"],
                    "state": old["state"],
                    "run_id": run["run_id"] if run else None,
                    "expected_run_version": run["version"] if run else None,
                    "status": run["status"] if run else None,
                    "native_session_id": (run.get("binding") or {}).get("native_session_id")
                    if run
                    else None,
                    "engine_version": old["engine_version"],
                    "asset_version": old["asset_version"],
                },
                indent=2,
            )
        )
    elif args.action == "reconcile":
        if not args.reconciliation_record:
            parser.error("Native reconciliation evidence file is required")
        try:
            data = Reconciliation.model_validate_json(Path(args.reconciliation_record).read_text())
            if data.worker_id != args.worker_id:
                raise ValueError("Recovery evidence belongs to a different worker")
            reconcile(store, data, identity, args.expected_account_id)
        except ValueError:
            # Pydantic errors can echo the input; do not print an operator's evidence file.
            parser.error(
                "Recovery requires valid, matching native evidence and every verification check"
            )
        except Conflict:
            parser.error("Recovery state changed; inspect the original run before retrying")
        print("Verified recovery recorded; session unlocked and old worker credential retired.")
    else:
        if not old or old.get("revoked") or old.get("active_run"):
            parser.error("Qualification requires an enrolled, idle, nonrevoked worker")
        if not args.qualification_record:
            parser.error("Native qualification evidence file is required")
        evidence = json.loads(Path(args.qualification_record).read_text())
        required = {
            "session_isolation",
            "plan_binding",
            "at_most_once",
            "native_observations",
            "reset_verification",
            "release",
            "restart_recovery",
            "no_hardware",
        }
        if (
            evidence.get("evidence") != "native"
            or set(evidence.get("checks", {})) != required
            or not all(value is True for value in evidence["checks"].values())
        ):
            parser.error("All native acceptance checks must be explicitly verified")
        if any(
            evidence.get(k) != old[k] for k in ("worker_id", "engine_version", "asset_version")
        ) or not evidence.get("report_uri"):
            parser.error(
                "Qualification must bind this worker, installed versions and an evidence report"
            )
        controls = evidence.get("controls", [])
        if not isinstance(controls, list) or not set(controls) <= {"pause", "resume", "cancel"}:
            parser.error("Invalid qualified control list")
        scenes = evidence.get("scenes", ["flex-first-transfer"])
        if (
            not isinstance(scenes, list)
            or not scenes
            or not set(scenes) <= {"flex-first-transfer", "flex-mixing"}
        ):
            parser.error("Invalid qualified scene list")
        if "flex-mixing" in scenes and evidence.get("mixing_and_media_verified") is not True:
            parser.error("Mixing qualification requires a verified native mixing and media report")
        store.put(
            WORKERS,
            args.worker_id,
            revised(
                old,
                qualified=True,
                state="ready",
                controls=controls,
                scenes=scenes,
                qualification=evidence,
            ),
            old["version"],
        )
        print("Worker qualification recorded. The separate deployment feature gate still applies.")


if __name__ == "__main__":
    main()
