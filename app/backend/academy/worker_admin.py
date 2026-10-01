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
import time
from pathlib import Path

import boto3

from .runs import WORKERS, revised
from .store import DynamoStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["enroll", "qualify", "revoke"])
    parser.add_argument("--expected-account-id", required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--engine-version")
    parser.add_argument("--asset-version")
    parser.add_argument("--credential-file")
    parser.add_argument("--qualification-record")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", args.worker_id):
        parser.error("worker-id must be a short lowercase machine name")
    if boto3.client("sts").get_caller_identity()["Account"] != args.expected_account_id:
        parser.error("AWS account does not match the selected deployment")
    store = DynamoStore(args.table)
    old = store.get(WORKERS, args.worker_id)
    if args.action == "enroll":
        if old:
            parser.error("Worker already exists; use a new ID or revoke its credential first")
        if not all([args.engine_version, args.asset_version, args.credential_file]):
            parser.error("Pinned engine/assets and credential-file are required")
        if len(store.partition(WORKERS, limit=101)) >= 100:
            parser.error("This initial worker registry is limited to 100 machines")
        token = args.worker_id + "." + secrets.token_urlsafe(48)
        destination = Path(args.credential_file)
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as file:
            file.write(token + "\n")
            file.flush()
            os.fsync(file.fileno())
        record = dict(
            version=1,
            worker_id=args.worker_id,
            credential_version=1,
            token_digest=hashlib.sha256(token.encode()).hexdigest(),
            credential_expires=time.time() + 90 * 86400,
            revoked=False,
            qualified=False,
            state="quarantined",
            active_run=None,
            controls=[],
            engine_version=args.engine_version,
            asset_version=args.asset_version,
        )
        store.put(WORKERS, args.worker_id, record, None)
        print(
            "Enrolled unqualified worker; protected credential file written. Native dispatch remains disabled."
        )
    elif args.action == "revoke":
        if not old:
            parser.error("Worker does not exist")
        store.put(
            WORKERS, args.worker_id, revised(old, revoked=True, state="quarantined"), old["version"]
        )
        # Reaper also runs every minute; direct reconciliation closes this sooner.
        from .runs import RunService

        RunService(store).reap()
        print("Worker revoked; active outcomes quarantined.")
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
        store.put(
            WORKERS,
            args.worker_id,
            revised(old, qualified=True, state="ready", controls=controls, qualification=evidence),
            old["version"],
        )
        print("Worker qualification recorded. The separate deployment feature gate still applies.")


if __name__ == "__main__":
    main()
