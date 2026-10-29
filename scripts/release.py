#!/usr/bin/env python3
"""Publish exactly the tested release artifact. Infrastructure stays in Terraform."""

import argparse
import ast
import base64
import hashlib
import json
import mimetypes
import os
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import boto3
import httpx
from academy._version import __version__

MANIFEST = Path("build/release.json")
LAMBDA = Path("build/lambda.zip")
WEB = Path("app/frontend/dist")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def revision():
    value = os.environ["GITHUB_SHA"]
    if not re.fullmatch(r"[a-f0-9]{40}", value):
        raise ValueError("A full Git commit SHA is required")
    return value


def verify_package_version():
    """Read the Lambda's durable version without importing its Linux dependencies."""
    try:
        with zipfile.ZipFile(LAMBDA) as archive:
            module = ast.parse(archive.read("academy/_version.py"))
        versions = [
            ast.literal_eval(node.value)
            for node in module.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__version__"
                for target in node.targets
            )
        ]
    except (KeyError, ValueError, SyntaxError, zipfile.BadZipFile) as exc:
        raise ValueError("Lambda package has no valid application version") from exc
    if versions != [__version__]:
        raise ValueError("Lambda package version differs from the release source")


def manifest():
    verify_package_version()
    release = {
        "version": __version__,
        "commit": revision(),
        "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "built_at": datetime.now(UTC).isoformat(),
        "lambda_sha256": digest(LAMBDA),
        "files": {
            str(path.relative_to(WEB)): digest(path)
            for path in sorted(WEB.rglob("*"))
            if path.is_file()
        },
    }
    if "index.html" not in release["files"]:
        raise ValueError("Release must contain the frontend entry page")
    MANIFEST.write_text(json.dumps(release, indent=2) + "\n")
    print(f"Bound {len(release['files'])} frontend files and Lambda to {release['commit']}")


def verify():
    release = json.loads(MANIFEST.read_text())
    if release.get("version") != __version__:
        raise ValueError("Release version does not match the packaged application")
    if release["commit"] != revision() or release["lambda_sha256"] != digest(LAMBDA):
        raise ValueError("Commit or Lambda artifact does not match the tested release")
    verify_package_version()
    actual = {str(path.relative_to(WEB)) for path in WEB.rglob("*") if path.is_file()}
    if set(release["files"]) != actual or "index.html" not in actual:
        raise ValueError("Frontend files differ from the tested manifest")
    for name, expected in release["files"].items():
        path = WEB / name
        if path.is_symlink() or not path.resolve().is_relative_to(WEB.resolve()):
            raise ValueError("Invalid release path")
        if digest(path) != expected:
            raise ValueError(f"Frontend artifact changed: {name}")
    print("Release checksums verified")
    return release


def expected_native_gate() -> str:
    """The deployment environment must state the gate it expects; default is disabled.

    Enabling native execution is a reviewed Terraform change plus this explicit
    declaration. Per-worker qualification still decides whether any run is dispatched.
    """
    value = os.environ.get("NATIVE_EXECUTION_EXPECTED", "false")
    if value not in {"true", "false"}:
        raise ValueError("NATIVE_EXECUTION_EXPECTED must be 'true' or 'false'")
    return value


def verify_live_release(http, app_url, release):
    http.get(app_url + "/").raise_for_status()
    response = http.get(app_url + "/api/health")
    response.raise_for_status()
    if response.json() != {"status": "ok", "version": release["version"]}:
        raise RuntimeError("Live API version does not match this build")
    response = http.get(app_url + "/version.json")
    response.raise_for_status()
    if response.json() != release:
        raise RuntimeError("Live release manifest does not match this build")
    if http.get(app_url + "/api/me").status_code != 401:
        raise RuntimeError("Unauthenticated learner request was not rejected")


def publish():
    release = verify()
    workers = json.loads(os.environ["WORKER_LAMBDA_FUNCTIONS"])
    if not isinstance(workers, list):
        raise ValueError("WORKER_LAMBDA_FUNCTIONS must be a JSON array")
    # Sim-to-real authorizers are optional until their Terraform is applied.
    extra = json.loads(os.environ.get("SIM2REAL_LAMBDA_FUNCTIONS") or "[]")
    if not isinstance(extra, list):
        raise ValueError("SIM2REAL_LAMBDA_FUNCTIONS must be a JSON array")
    names = [os.environ["LAMBDA_FUNCTION"], *workers, *extra]
    if (
        len(names) != 4 + len(extra)
        or not all(
            isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_-]+", name) for name in names
        )
        or len(set(names)) != len(names)
    ):
        raise ValueError("Exactly four distinct Lambda names are required")
    native = expected_native_gate()
    real = os.environ.get("REAL_EXECUTION_EXPECTED", "false")
    if real not in {"true", "false"}:
        raise ValueError("REAL_EXECUTION_EXPECTED must be 'true' or 'false'")
    expected_account = os.environ["AWS_ACCOUNT_ID"]
    if not re.fullmatch(r"[0-9]{12}", expected_account):
        raise ValueError("A pinned AWS account is required")
    session = boto3.Session(region_name=os.environ["AWS_REGION"])
    if session.client("sts").get_caller_identity()["Account"] != expected_account:
        raise ValueError("AWS deployment account mismatch")
    bucket, distribution = os.environ["WEB_BUCKET"], os.environ["DISTRIBUTION_ID"]
    app_url = os.environ["APP_URL"].rstrip("/")
    if not re.fullmatch(r"https://[a-z0-9]+\.cloudfront\.net", app_url):
        raise ValueError("Expected the configured CloudFront application URL")
    lambda_client = session.client("lambda")
    expected_code = base64.b64encode(bytes.fromhex(release["lambda_sha256"])).decode()
    # Preflight all functions before the first update, including the native gate.
    # Terraform owns the gate; a release only proceeds when it matches the declared state.
    for name in names:
        current = lambda_client.get_function_configuration(FunctionName=name)
        variables = current["Environment"]["Variables"]
        if variables.get("ACADEMY_REMOTE_ENABLED") != native:
            raise ValueError(
                "Native execution gate differs from NATIVE_EXECUTION_EXPECTED; "
                "reconcile Terraform and the deployment environment first"
            )
        if variables.get("ACADEMY_REAL_ENABLED", "false") != real:
            raise ValueError(
                "Physical execution gate differs from REAL_EXECUTION_EXPECTED; "
                "reconcile Terraform and the deployment environment first"
            )
    for name in names:
        lambda_client.update_function_code(FunctionName=name, ZipFile=LAMBDA.read_bytes())
        lambda_client.get_waiter("function_updated_v2").wait(
            FunctionName=name, WaiterConfig={"Delay": 2, "MaxAttempts": 90}
        )
        current = lambda_client.get_function_configuration(FunctionName=name)
        if current["CodeSha256"] != expected_code or current["LastUpdateStatus"] != "Successful":
            raise RuntimeError("Lambda code verification failed")
        print(f"Published and verified {name}")
    s3 = session.client("s3")
    for name in sorted(release["files"], key=lambda name: name == "index.html"):
        s3.put_object(
            Bucket=bucket,
            Key=name,
            Body=(WEB / name).read_bytes(),
            ContentType=mimetypes.guess_type(name)[0] or "application/octet-stream",
            CacheControl="no-cache"
            if name == "index.html"
            else "public,max-age=31536000,immutable",
        )
    s3.put_object(
        Bucket=bucket,
        Key="version.json",
        Body=json.dumps(release).encode(),
        ContentType="application/json",
        CacheControl="no-cache",
    )
    cloudfront = session.client("cloudfront")
    invalidation = cloudfront.create_invalidation(
        DistributionId=distribution,
        InvalidationBatch={
            "Paths": {
                "Quantity": 4,
                "Items": ["/", "/index.html", "/auth/callback", "/version.json"],
            },
            "CallerReference": f"academy-{release['commit']}-{os.environ.get('GITHUB_RUN_ID', 'local')}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}",
        },
    )["Invalidation"]["Id"]
    cloudfront.get_waiter("invalidation_completed").wait(
        DistributionId=distribution,
        Id=invalidation,
        WaiterConfig={"Delay": 5, "MaxAttempts": 90},
    )
    with httpx.Client(timeout=30) as http:
        verify_live_release(http, app_url, release)
    result = (
        f"Published {release['commit']} to {app_url}; four Lambda hashes and live version verified."
    )
    print(result)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a") as file:
            file.write(result + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("manifest", "verify", "publish"))
    {"manifest": manifest, "verify": verify, "publish": publish}[parser.parse_args().action]()
