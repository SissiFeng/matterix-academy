#!/usr/bin/env python3
"""Inspect AC sources or mirror one reviewed, immutable package. Never installs."""

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app/backend"))

import boto3  # noqa: E402
from academy.connector_catalog import REPOSITORIES, ConnectorArtifact  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402


def github(path):
    return json.loads(
        subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True).stdout
    )


def inspect_sources():
    result = {"schema": "academy.connector-intake/1", "activation_allowed": False, "sources": []}
    for instrument, repository in REPOSITORIES.items():
        head = github(f"repos/{repository}/commits/main")["sha"]
        runs = github(f"repos/{repository}/actions/runs?head_sha={head}&per_page=30")[
            "workflow_runs"
        ]
        artifacts = github(f"repos/{repository}/actions/artifacts?per_page=30")["artifacts"]
        result["sources"].append(
            {
                "instrument": instrument,
                "repository": repository,
                "source_commit": head,
                "checks": [
                    {
                        "run_id": r["id"],
                        "name": r["name"],
                        "status": r["status"],
                        "conclusion": r["conclusion"],
                    }
                    for r in runs
                ],
                "artifacts": [
                    {
                        "id": a["id"],
                        "name": a["name"],
                        "expired": a["expired"],
                        "size_bytes": a["size_in_bytes"],
                        "source_commit": a.get("workflow_run", {}).get("head_sha"),
                        "expires_at": a["expires_at"],
                    }
                    for a in artifacts
                ],
            }
        )
    return result


def verify_file(manifest, path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Artifact must be a regular, non-symlink file")
    if path.stat().st_size != manifest.size_bytes:
        raise ValueError("Artifact size does not match the manifest")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != manifest.artifact_sha256:
        raise ValueError("Artifact SHA256 does not match the manifest")
    return digest


def verify_build(manifest):
    run = github(f"repos/{manifest.repository}/actions/runs/{manifest.build_run_id}")
    if not (
        run.get("repository", {}).get("full_name") == manifest.repository
        and run.get("head_sha") == manifest.artifact_source_commit
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
    ):
        raise ValueError("GitHub build provenance does not match the package")
    if manifest.status == "approved":
        artifact = github(
            f"repos/{manifest.repository}/actions/artifacts/{manifest.github_artifact_id}"
        )
        if (
            artifact.get("expired")
            or artifact.get("workflow_run", {}).get("id") != manifest.build_run_id
            or artifact.get("workflow_run", {}).get("head_sha") != manifest.source_commit
        ):
            raise ValueError("Approved package must be bound to its exact Actions build and source")
        if artifact.get("digest") and artifact["digest"] != f"sha256:{manifest.artifact_sha256}":
            raise ValueError("Actions artifact digest differs from the reviewed package")
        runs = github(
            f"repos/{manifest.repository}/actions/runs?head_sha={manifest.source_commit}&per_page=100"
        )["workflow_runs"]
        tests = [r for r in runs if r.get("name", "").lower() in {"test", "tests", "ci"}]
        if not tests or any(r.get("conclusion") != "success" for r in tests):
            raise ValueError(
                "Approved publication requires passing test workflows at the exact source"
            )


def fetch_bundle(manifest, artifact_id, kind, output):
    """Download only a GitHub artifact from the manifest's fixed AC repository."""
    if output.exists() or output.is_symlink():
        raise ValueError("Use a new package output path")
    if artifact_id != manifest.github_artifact_id or kind != manifest.artifact_kind:
        raise ValueError("Artifact ID and kind must match the reviewed manifest")
    verify_build(manifest)
    if kind == "actions":
        path = f"repos/{manifest.repository}/actions/artifacts/{artifact_id}"
        record = github(path)
        run = record.get("workflow_run", {})
        if (
            record.get("expired")
            or run.get("head_sha") != manifest.artifact_source_commit
            or run.get("id") != manifest.build_run_id
        ):
            raise ValueError("Actions artifact does not belong to the reviewed build")
        download_path = path + "/zip"
    else:
        path = f"repos/{manifest.repository}/releases/assets/{artifact_id}"
        record = github(path)
        if (
            record.get("name") != manifest.filename
            or record.get("digest") != f"sha256:{manifest.artifact_sha256}"
        ):
            raise ValueError("Release asset does not match the pinned name and GitHub digest")
        releases = github(f"repos/{manifest.repository}/releases?per_page=100")
        release = next(
            (r for r in releases if any(a.get("id") == artifact_id for a in r.get("assets", []))),
            None,
        )
        source = re.search(r"\bBuilt from ([a-f0-9]{40})\.", (release or {}).get("body") or "")
        if not source or source.group(1) != manifest.artifact_source_commit:
            raise ValueError("Release asset has no exact-source provenance in its owning release")
        download_path = path
    if record.get("size", record.get("size_in_bytes")) != manifest.size_bytes:
        raise ValueError("GitHub artifact size does not match the reviewed manifest")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        subprocess.run(
            ["gh", "api", download_path, "-H", "Accept: application/octet-stream"],
            stdout=stream,
            check=True,
        )
    return {"downloaded": True, "sha256": verify_file(manifest, output), "installed": False}


def immutable_put(s3, bucket, key, payload, digest, content_type):
    try:
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=payload,
            IfNoneMatch="*",
            ContentType=content_type,
            ServerSideEncryption="AES256",
            Metadata={"sha256": digest},
            ChecksumSHA256=base64.b64encode(bytes.fromhex(digest)).decode(),
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in {"PreconditionFailed", "412"}:
            raise
        # Lost upload replies and exact duplicate uploads are reconciled by hash.
        head = s3.head_object(Bucket=bucket, Key=key, ChecksumMode="ENABLED")
        expected = base64.b64encode(bytes.fromhex(digest)).decode()
        if head.get("ChecksumSHA256") != expected:
            raise ValueError("An immutable key already contains different bytes") from exc


def mirror(manifest, path, bucket, expected_account, session=None):
    digest = verify_file(manifest, path)
    verify_build(manifest)
    session = session or boto3.Session()
    identity = session.client("sts").get_caller_identity()
    if identity["Account"] != expected_account:
        raise ValueError("AWS account mismatch; nothing was published")
    s3 = session.client("s3")
    s3.head_bucket(Bucket=bucket, ExpectedBucketOwner=expected_account)
    block = s3.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"]
    if not all(
        block.get(k)
        for k in (
            "BlockPublicAcls",
            "IgnorePublicAcls",
            "BlockPublicPolicy",
            "RestrictPublicBuckets",
        )
    ):
        raise ValueError("Use a private artifact bucket, not the public web asset bucket")
    try:
        policy = json.loads(s3.get_bucket_policy(Bucket=bucket)["Policy"])
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchBucketPolicy":
            raise
        policy = {"Statement": []}
    for statement in policy.get("Statement", []):
        principal = statement.get("Principal")
        principal_text = json.dumps(principal)
        if statement.get("Effect") == "Allow" and (
            '"*"' in principal_text
            or "cloudfront.amazonaws.com" in principal_text
            or ":iam::cloudfront:user/CloudFront Origin Access Identity " in principal_text
        ):
            raise ValueError("Artifact bucket must not allow public or website distribution reads")
    if s3.get_bucket_versioning(Bucket=bucket).get("Status") != "Enabled":
        raise ValueError("Artifact bucket versioning must be enabled")
    with path.open("rb") as payload:
        immutable_put(s3, bucket, manifest.object_key, payload, digest, "application/octet-stream")
    content = (json.dumps(manifest.model_dump(), sort_keys=True, indent=2) + "\n").encode()
    key = manifest.object_key + ".manifest.json"
    immutable_put(s3, bucket, key, content, hashlib.sha256(content).hexdigest(), "application/json")
    head = s3.head_object(Bucket=bucket, Key=manifest.object_key, ChecksumMode="ENABLED")
    if (
        head.get("ChecksumSHA256") != base64.b64encode(bytes.fromhex(digest)).decode()
        or head["ContentLength"] != manifest.size_bytes
    ):
        raise ValueError("Published package could not be verified; reconcile before retrying")
    return {
        "published": True,
        "installed": False,
        "activated": False,
        "status": manifest.status,
        "bucket": bucket,
        "key": manifest.object_key,
        "sha256": digest,
        "account": expected_account,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--output", type=Path, required=True)
    fetch = commands.add_parser("fetch")
    fetch.add_argument("--manifest", type=Path, required=True)
    fetch.add_argument("--artifact-id", type=int, required=True)
    fetch.add_argument("--kind", choices=["actions", "release"], required=True)
    fetch.add_argument("--output", type=Path, required=True)
    for name in ("verify", "mirror"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--manifest", type=Path, required=True)
        cmd.add_argument("--bundle", type=Path, required=True)
        if name == "mirror":
            cmd.add_argument("--bucket", required=True)
            cmd.add_argument("--expected-account", required=True)
            cmd.add_argument("--confirm-publish", action="store_true", required=True)
    args = parser.parse_args()
    if args.command == "inspect":
        if args.output.exists():
            parser.error("Use a new intake output path")
        result = inspect_sources()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    else:
        manifest = ConnectorArtifact.model_validate_json(args.manifest.read_text())
        if args.command == "fetch":
            if args.artifact_id <= 0:
                parser.error("Artifact ID must be positive")
            result = fetch_bundle(manifest, args.artifact_id, args.kind, args.output)
        elif args.command == "verify":
            result = {
                "sha256": verify_file(manifest, args.bundle),
                "status": manifest.status,
                "installed": False,
            }
        else:
            if not args.expected_account.isdigit() or len(args.expected_account) != 12:
                parser.error("Expected account must be an explicitly reviewed 12-digit account ID")
            result = mirror(manifest, args.bundle, args.bucket, args.expected_account)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
