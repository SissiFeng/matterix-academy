#!/usr/bin/env python3
"""Offline operator reconciliation. Preserves unknown evidence and never replays."""

import argparse
import json
from pathlib import Path
from uuid import UUID

from academy.companion.config import read_private
from academy.connections import ConnectionService, ConnectorResolution
from academy.store import DynamoStore, SQLiteStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--sqlite", type=Path)
    target.add_argument("--table")
    parser.add_argument("--expected-account")
    parser.add_argument("--run-id", type=UUID, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-physically-stopped-and-released", action="store_true")
    args = parser.parse_args()
    if args.apply and not args.confirm_physically_stopped_and_released:
        parser.error("Verify the exact device is stopped and released before applying a resolution")
    evidence = ConnectorResolution.model_validate_json(read_private(args.evidence))
    if args.table:
        import boto3

        if (
            not args.expected_account
            or boto3.client("sts").get_caller_identity()["Account"] != args.expected_account
        ):
            parser.error("AWS account must match the explicitly reviewed expected account")
    store = DynamoStore(args.table) if args.table else SQLiteStore(str(args.sqlite))
    service = ConnectionService(store)
    run = service.run_raw(str(args.run_id))
    if args.apply:
        result = service.resolve_unknown(str(args.run_id), evidence)
    else:
        result = {
            "run_id": run["run_id"],
            "current_version": run["version"],
            "status": run["status"],
            "proposed_resolution": evidence.model_dump(mode="json"),
        }
    print(
        json.dumps(
            {"applied": args.apply, "result": result, "hardware_commands_executed": False}, indent=2
        )
    )


if __name__ == "__main__":
    main()
