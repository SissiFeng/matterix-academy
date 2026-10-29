"""Operator-only instrument administration (IAM identity, never HTTP).

Examples (credentials are written once to a protected file, never printed):

    uv run python -m academy.lab_admin register-instrument --expected-account-id ... \\
        --table ... --instrument-id flex-lab --name "Flex A" --profile reviewed-profile.json
    uv run python -m academy.lab_admin issue-gateway --expected-account-id ... --table ... \\
        --instrument-id flex-lab --gateway-id flex-lab-mac --credential-file ~/flex-gateway.token
    uv run python -m academy.lab_admin link-device --expected-account-id ... --table ... \\
        --instrument-id flex-lab --owner <cognito-sub> --device-id <uuid>
    uv run python -m academy.lab_admin issue-orchestrator --expected-account-id ... --table ... \\
        --client-id lab-orchestrator --instrument-id flex-lab --credential-file ~/orc.token
"""

import argparse
import json
import os
import time
from pathlib import Path
from uuid import UUID

import boto3

from .external import issue_orchestrator
from .instruments import InstrumentService
from .store import Conflict, DynamoStore
from .worker_admin import operator_identity


def write_secret(path, token):
    """Exclusive 0600 publication; an existing file is never overwritten."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write(token + "\n")
        file.flush()
        os.fsync(file.fileno())


def link_device(store, owner, device_id, instrument_id, clock=time.time):
    """Server-owned link from a learner's device declaration to a physical instrument."""
    InstrumentService(store, clock=clock).get(instrument_id)
    key = f"device#{UUID(str(device_id))}"
    record = store.get(owner, key)
    if record is None:
        raise ValueError("Device declaration not found for that owner")
    expected_model = InstrumentService(store).get(instrument_id)["model"]
    if record.get("model") != expected_model:
        raise ValueError("Declared model differs from the instrument model")
    changed = {**record, "instrument_id": instrument_id, "version": record["version"] + 1}
    store.put(owner, key, changed, record["version"])
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "action",
        choices=["register-instrument", "issue-gateway", "link-device", "issue-orchestrator"],
    )
    parser.add_argument("--expected-account-id", required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--instrument-id", required=True)
    parser.add_argument("--name")
    parser.add_argument("--profile")
    parser.add_argument("--gateway-id")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--confirm-old-gateway-stopped", action="store_true")
    parser.add_argument("--credential-file")
    parser.add_argument("--owner")
    parser.add_argument("--device-id")
    parser.add_argument("--client-id")
    args = parser.parse_args()
    try:
        operator_identity(boto3.client("sts").get_caller_identity(), args.expected_account_id)
    except ValueError as exc:
        parser.error(str(exc))
    store = DynamoStore(args.table)
    service = InstrumentService(store)
    try:
        if args.action == "register-instrument":
            profile = json.loads(Path(args.profile).read_text())
            record = service.register(args.instrument_id, args.name or args.instrument_id, profile)
            print(
                f"Instrument {record['instrument_id']} registered ({record['qualified_profile_sha256'][:12]})."
            )
        elif args.action == "issue-gateway":
            if args.replace and not args.confirm_old_gateway_stopped:
                parser.error("Stop the old gateway first, then pass --confirm-old-gateway-stopped")
            if Path(args.credential_file).exists():
                parser.error("Credential file exists; choose a new path")
            token, record = service.issue_gateway(
                args.instrument_id, args.gateway_id, replace=args.replace
            )
            write_secret(args.credential_file, token)
            print(
                f"Gateway {record['gateway_id']} issued; credential written to the protected file."
            )
        elif args.action == "link-device":
            link_device(store, args.owner, args.device_id, args.instrument_id)
            print("Device declaration linked; it now shows this instrument's physical evidence.")
        else:
            if Path(args.credential_file).exists():
                parser.error("Credential file exists; choose a new path")
            token, record = issue_orchestrator(
                store, args.client_id, instruments=[args.instrument_id]
            )
            write_secret(args.credential_file, token)
            print(
                f"Orchestrator {record['client_id']} issued; credential written to the protected file."
            )
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    except Conflict:
        parser.error("Records changed concurrently; inspect and retry")


if __name__ == "__main__":
    main()
