#!/usr/bin/env python3
"""Preview or record operator evidence. This tool does not perform qualification."""

import argparse
import hashlib
import json
import time
from pathlib import Path
from uuid import UUID

from academy.companion.config import RobotProfile, read_private
from academy.connections import BINDINGS, QUALIFICATIONS, ConnectionService
from academy.connector_catalog import approved_release
from academy.models import StrictModel
from academy.store import DynamoStore, SQLiteStore, Write
from pydantic import AwareDatetime, Field, model_validator


class QualificationEvidence(StrictModel):
    operator: str = Field(min_length=1, max_length=128)
    checked_at: AwareDatetime
    expires_at: AwareDatetime
    connection_id: UUID
    installation_id: UUID
    profile_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    installed_release_verified: bool
    sila_identity_verified: bool
    calibration_verified: bool
    protocol_engine_verified: bool
    startup_without_motion_verified: bool
    rollback_recovery_verified: bool
    supervised_acceptance_report: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def all_checks(self):
        if not all(
            getattr(self, name)
            for name in (
                "installed_release_verified",
                "sila_identity_verified",
                "calibration_verified",
                "protocol_engine_verified",
                "startup_without_motion_verified",
                "rollback_recovery_verified",
            )
        ):
            raise ValueError("Every independent qualification check must have observed evidence")
        if not self.checked_at.timestamp() <= time.time() < self.expires_at.timestamp():
            raise ValueError("Qualification is not current")
        if self.expires_at.timestamp() - self.checked_at.timestamp() > 30 * 86400:
            raise ValueError("Qualification may cover at most 30 days")
        return self


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--sqlite", type=Path)
    destination.add_argument("--table")
    parser.add_argument("--expected-account")
    parser.add_argument("--owner", required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--expected-version", type=int, default=0)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-supervised-qualification", action="store_true")
    args = parser.parse_args()
    if args.apply and not args.confirm_supervised_qualification:
        parser.error("Recording evidence requires --confirm-supervised-qualification")
    if args.table:
        import boto3

        if (
            not args.expected_account
            or boto3.client("sts").get_caller_identity()["Account"] != args.expected_account
        ):
            parser.error("AWS identity must match the explicitly reviewed expected account")
    profile = RobotProfile.model_validate_json(read_private(args.profile))
    profile.assert_current()
    evidence_bytes = read_private(args.evidence)
    evidence = QualificationEvidence.model_validate_json(evidence_bytes)
    if evidence.profile_sha256 != profile.sha256 or evidence.expires_at > profile.qualified_until:
        parser.error("Evidence must match the exact current local profile and its validity")
    store = DynamoStore(args.table) if args.table else SQLiteStore(str(args.sqlite))
    service = ConnectionService(store, approved_release=approved_release)
    connection = service.raw(args.owner, evidence.connection_id)
    probe = connection.get("probe") or {}
    release = service.release(connection)
    if not release or connection.get("installation_id") != str(evidence.installation_id):
        parser.error("Connection needs its paired installation and an approved release")
    expected = {**profile.model_dump(mode="json"), "profile_sha256": profile.sha256}
    if any(probe.get(key) != expected.get(key) for key in BINDINGS):
        parser.error("Current read-only probe does not match the qualified profile")
    if any(
        probe.get(key) != release.get(key)
        for key in (
            "instrument",
            "release_id",
            "artifact_sha256",
            "source_commit",
            "runtime_contract_id",
            "runtime_release_id",
            "runtime_bundle_sha256",
        )
    ) or probe.get("firmware") not in release.get("supported_firmware", []):
        parser.error("Observed installation does not match the currently approved release/firmware")
    if not probe.get("reachable") or time.time() - probe.get("observed_at", 0) > 300:
        parser.error("A fresh read-only probe is required")
    record = {
        "version": args.expected_version + 1,
        "owner": args.owner,
        "connection_id": str(evidence.connection_id),
        "installation_id": str(evidence.installation_id),
        "revoked": False,
        "expires_at": evidence.expires_at.timestamp(),
        "capabilities": ["protocol-engine"],
        **{key: probe[key] for key in BINDINGS},
        "operator": evidence.operator,
        "evidence_sha256": hashlib.sha256(evidence_bytes).hexdigest(),
    }
    if args.apply:
        store.transact(
            [
                Write(
                    args.owner,
                    f"connection#{evidence.connection_id}",
                    connection,
                    connection["version"],
                ),
                Write(
                    QUALIFICATIONS,
                    str(evidence.connection_id),
                    record,
                    args.expected_version or None,
                ),
            ]
        )
    print(
        json.dumps(
            {"applied": args.apply, "qualification": record, "hardware_commands_executed": False},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
