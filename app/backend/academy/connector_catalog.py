"""Reviewed connector artifacts; intake candidates never authorize installation."""

import base64
import json
import os
from pathlib import Path
from typing import Literal

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, model_validator

from .auth import identify
from .models import StrictModel

REPOSITORIES = {
    "ot2": "AccelerationConsortium/opentrons-ot2",
    "flex": "AccelerationConsortium/opentrons-flex",
}
ROOT = Path(__file__).with_name("connector_releases.json")


class ConnectorArtifact(StrictModel):
    schema_version: Literal["academy.connector-artifact/1"]
    instrument: Literal["ot2", "flex"]
    repository: str
    source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    artifact_source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:[.a-z0-9-]+)?$")
    filename: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(gt=0, le=2_000_000_000)
    build_run_id: int = Field(gt=0)
    github_artifact_id: int = Field(gt=0)
    artifact_kind: Literal["actions", "release"]
    build_succeeded: bool
    tests_passed: bool
    status: Literal["candidate", "approved"] = "candidate"
    platforms: list[Literal["macos", "linux"]] = Field(min_length=1, max_length=2)
    robot_arch: Literal["armv7l", "aarch64"]
    supported_firmware: list[str] = Field(min_length=1, max_length=12)
    execution_transport: Literal["opentrons-protocol-engine"]
    rollback_test_passed: bool = False
    no_motion_startup_passed: bool = False
    qualification_report_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    installer_recipe_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    runtime_contract_id: str | None = Field(default=None, min_length=1, max_length=128)
    runtime_release_id: str | None = Field(default=None, min_length=1, max_length=128)
    runtime_bundle_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def provenance(self):
        if self.repository != REPOSITORIES[self.instrument]:
            raise ValueError("Connector repository is not allowlisted")
        if self.robot_arch != {"ot2": "armv7l", "flex": "aarch64"}[self.instrument]:
            raise ValueError("Robot architecture does not match the instrument")
        if len(set(self.platforms)) != len(self.platforms):
            raise ValueError("Duplicate platforms")
        if any(not value.strip() or len(value) > 64 for value in self.supported_firmware):
            raise ValueError("Declare exact qualified firmware versions")
        if self.status == "approved" and not (
            self.source_commit == self.artifact_source_commit
            and self.artifact_kind == "actions"
            and self.build_succeeded
            and self.tests_passed
            and self.rollback_test_passed
            and self.no_motion_startup_passed
            and self.qualification_report_sha256
            and self.runtime_contract_id
            and self.runtime_release_id
            and self.runtime_bundle_sha256
        ):
            raise ValueError(
                "Approval requires exact source, passing checks and qualification evidence"
            )
        return self

    @property
    def release_id(self):
        return f"{self.instrument}-{self.source_commit[:12]}-{self.artifact_sha256[:12]}"

    @property
    def object_key(self):
        return (
            f"connectors/{self.status}/{self.instrument}/{self.source_commit}/"
            f"{self.artifact_sha256}/{self.filename}"
        )


class CompanionPackage(StrictModel):
    platform: Literal["macos"]
    architecture: Literal["arm64", "x86_64"]
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    source_tree_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(gt=0, le=500_000_000)
    filename: str = Field(pattern=r"^academy-bridge-macos-[a-z0-9-]+\.zip$")
    notarized: Literal[True]
    tests_passed: Literal[True]
    status: Literal["approved"]

    @property
    def object_key(self):
        return f"connectors/approved/desktop/{self.source_commit}/{self.artifact_sha256}/{self.filename}"


def matches_object(head, artifact):
    checksum = base64.b64encode(bytes.fromhex(artifact.artifact_sha256)).decode("ascii")
    return (
        head.get("ChecksumSHA256") == checksum
        and head.get("Metadata", {}).get("sha256") == artifact.artifact_sha256
        and head.get("ContentLength") == artifact.size_bytes
    )


def companion_download(data, platform, architecture):
    packages = [CompanionPackage.model_validate(p) for p in data.get("companion_packages", [])]
    matching = [p for p in packages if p.platform == platform and p.architecture == architecture]
    if len(matching) > 1:
        raise ValueError("Only one published desktop package per platform and architecture")
    bucket = os.getenv("ACADEMY_CONNECTOR_BUCKET", "")
    if not matching or not bucket:
        return None
    package = matching[0]
    client = boto3.client("s3")
    head = client.head_object(Bucket=bucket, Key=package.object_key, ChecksumMode="ENABLED")
    if not matches_object(head, package):
        raise ValueError("Desktop package does not match its approved manifest")
    return {
        **package.model_dump(),
        "status": "available",
        "platforms": [platform],
        "reason": "Download the reviewed Mac companion, then open its launcher and approve installation on this computer.",
        "download_url": client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": package.object_key}, ExpiresIn=300
        ),
    }


def read_catalog(path: Path | None = None):
    path = path or Path(os.getenv("ACADEMY_CONNECTOR_CATALOG", str(ROOT)))
    data = json.loads(path.read_text())
    if data.get("schema") != "academy.connector-catalog/1":
        raise ValueError("Unsupported connector catalog")
    releases = [ConnectorArtifact.model_validate(item) for item in data.get("artifacts", [])]
    identities = [r.instrument for r in releases if r.status == "approved"]
    if len(identities) != len(set(identities)):
        raise ValueError("Only one active approved release per instrument")
    return data, releases


def approved_release(instrument: str, platform: str):
    try:
        _, releases = read_catalog()
    except (OSError, ValueError):
        return None
    for release in releases:
        if (
            release.instrument == instrument
            and platform in release.platforms
            and release.status == "approved"
        ):
            return {**release.model_dump(), "release_id": release.release_id, "platform": platform}
    return None


def public_catalog(platform="macos", architecture="arm64"):
    try:
        data, releases = read_catalog()
    except (OSError, ValueError):
        raise HTTPException(503, "The reviewed connector catalog is unavailable") from None
    result = []
    for instrument, repository in REPOSITORIES.items():
        approved = next(
            (r for r in releases if r.instrument == instrument and r.status == "approved"), None
        )
        source = data["sources"][instrument]
        result.append(
            {
                "instrument": instrument,
                "name": "Opentrons Flex" if instrument == "flex" else "Opentrons OT-2",
                "repository": repository,
                "source_commit": approved.source_commit if approved else source["commit"],
                "version": approved.version if approved else source["version"],
                "status": "approved" if approved else "candidate",
                "reason": "Reviewed release available for this instrument."
                if approved
                else source["reason"],
                "platforms": approved.platforms if approved else ["macos", "linux"],
                "release_id": approved.release_id if approved else None,
                "artifact_sha256": approved.artifact_sha256 if approved else None,
                "execution_transport": "opentrons-protocol-engine",
                "download_url": f"/api/connectors/{instrument}/download" if approved else None,
            }
        )
    try:
        companion = companion_download(data, platform, architecture)
    except (ValueError, BotoCoreError, ClientError, KeyError):
        raise HTTPException(503, "The reviewed desktop package is unavailable") from None
    return {
        "schema": data["schema"],
        "companion": companion
        or {
            "status": "source-only",
            "version": "0.2.0",
            "platforms": ["macos", "linux"],
            "download_url": None,
            "reason": "The local companion is available from the reviewed Academy source. A published desktop installer is not configured yet.",
        },
        "releases": result,
    }


router = APIRouter(prefix="/api/connectors", dependencies=[Depends(identify)])


@router.get("/catalog")
def catalog(
    platform: Literal["macos", "linux", "windows"] = "macos",
    architecture: Literal["arm64", "x86_64"] = "arm64",
):
    return public_catalog(platform, architecture)


@router.get("/{instrument}/download")
def download(instrument: Literal["ot2", "flex"], platform: Literal["macos", "linux", "windows"]):
    release = approved_release(instrument, platform)
    bucket = os.getenv("ACADEMY_CONNECTOR_BUCKET", "")
    if not release or not bucket:
        raise HTTPException(
            503, "No published, approved connector package is available for this platform"
        )
    artifact = ConnectorArtifact.model_validate(
        {k: v for k, v in release.items() if k not in {"release_id", "platform"}}
    )
    client = boto3.client("s3")
    try:
        head = client.head_object(Bucket=bucket, Key=artifact.object_key, ChecksumMode="ENABLED")
    except (BotoCoreError, ClientError):
        raise HTTPException(503, "The reviewed connector package is unavailable") from None
    if not matches_object(head, artifact):
        raise HTTPException(503, "Published artifact does not match the approved manifest")
    return {
        "url": client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": artifact.object_key}, ExpiresIn=300
        ),
        "expires_in": 300,
        "manifest": artifact.model_dump(),
        "release_id": artifact.release_id,
    }
