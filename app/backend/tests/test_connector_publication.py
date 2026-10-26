"""Publication boundary tests use fake GitHub and AWS; no cloud writes."""

import base64
import hashlib
import importlib.util
from pathlib import Path

import pytest
from academy import connector_catalog as catalog
from botocore.exceptions import ClientError
from fastapi import HTTPException
from test_connector_catalog import artifact


def release_module():
    spec = importlib.util.spec_from_file_location(
        "connector_release_test", Path(__file__).parents[3] / "scripts/connector-release.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def approved(**changes):
    return catalog.ConnectorArtifact.model_validate(
        artifact(
            status="approved",
            rollback_test_passed=True,
            no_motion_startup_passed=True,
            qualification_report_sha256="c" * 64,
            runtime_contract_id="runtime-v1",
            runtime_release_id="release-1",
            runtime_bundle_sha256="d" * 64,
            **changes,
        )
    )


def test_release_asset_cannot_be_promoted_despite_passing_flags():
    with pytest.raises(ValueError, match="Approval requires"):
        approved(artifact_kind="release")


@pytest.mark.parametrize("broken", ["source", "run", "expired", "digest", "tests"])
def test_approved_artifact_cannot_borrow_other_build_evidence(monkeypatch, broken):
    module = release_module()
    manifest = approved()
    run = {
        "repository": {"full_name": manifest.repository},
        "head_sha": "a" * 40,
        "status": "completed",
        "conclusion": "success",
    }
    package = {
        "expired": False,
        "workflow_run": {"id": 12, "head_sha": "a" * 40},
        "digest": "sha256:" + "b" * 64,
    }
    tests = {"workflow_runs": [{"name": "Test", "conclusion": "success"}]}
    if broken == "source":
        package["workflow_run"]["head_sha"] = "f" * 40
    elif broken == "run":
        package["workflow_run"]["id"] = 99
    elif broken == "expired":
        package["expired"] = True
    elif broken == "digest":
        package["digest"] = "sha256:" + "f" * 64
    else:
        tests["workflow_runs"][0]["conclusion"] = "failure"
    monkeypatch.setattr(
        module,
        "github",
        lambda path: tests if "?" in path else package if "artifacts/" in path else run,
    )
    with pytest.raises(ValueError):
        module.verify_build(manifest)


def test_fetch_rejects_unreviewed_artifact_id_before_network(tmp_path, monkeypatch):
    module = release_module()
    monkeypatch.setattr(module, "github", lambda _: pytest.fail("No network should be used"))
    with pytest.raises(ValueError, match="ID and kind"):
        module.fetch_bundle(approved(), 99, "actions", tmp_path / "out.zip")


def test_immutable_duplicate_checks_stored_bytes():
    module = release_module()
    digest = hashlib.sha256(b"package").hexdigest()

    class Storage:
        def __init__(self, stored):
            self.stored = stored

        def put_object(self, **kwargs):
            assert kwargs["IfNoneMatch"] == "*"
            assert kwargs["ChecksumSHA256"] == base64.b64encode(bytes.fromhex(digest)).decode()
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")

        def head_object(self, **kwargs):
            assert kwargs["ChecksumMode"] == "ENABLED"
            return {"ChecksumSHA256": self.stored}

    module.immutable_put(
        Storage(base64.b64encode(bytes.fromhex(digest)).decode()),
        "private",
        "key",
        b"package",
        digest,
        "application/zip",
    )
    with pytest.raises(ValueError, match="different bytes"):
        module.immutable_put(
            Storage("changed"), "private", "key", b"package", digest, "application/zip"
        )


def test_wrong_account_cannot_publish(tmp_path, monkeypatch):
    module = release_module()
    package = tmp_path / "bundle"
    package.write_bytes(b"package")
    manifest = approved(size_bytes=7, artifact_sha256=hashlib.sha256(b"package").hexdigest())
    monkeypatch.setattr(module, "verify_build", lambda _: None)

    class Session:
        def client(self, service):
            assert service == "sts", "An account mismatch must not reach S3"
            return self

        def get_caller_identity(self):
            return {"Account": "111111111111"}

    with pytest.raises(ValueError, match="account mismatch"):
        module.mirror(manifest, package, "private", "222222222222", Session())


@pytest.mark.parametrize(
    "principal",
    [
        "*",
        {"AWS": "*"},
        {"Service": "cloudfront.amazonaws.com"},
        {"AWS": "arn:aws:iam::cloudfront:user/CloudFront Origin Access Identity EXAMPLE"},
        {"AWS": ["arn:aws-cn:iam::cloudfront:user/CloudFront Origin Access Identity EXAMPLE"]},
    ],
)
def test_website_bucket_cannot_receive_connector_artifact(tmp_path, monkeypatch, principal):
    module = release_module()
    package = tmp_path / "bundle"
    package.write_bytes(b"package")
    manifest = approved(size_bytes=7, artifact_sha256=hashlib.sha256(b"package").hexdigest())
    monkeypatch.setattr(module, "verify_build", lambda _: None)

    class Session:
        def client(self, service):
            return self

        def get_caller_identity(self):
            return {"Account": "111111111111"}

        def head_bucket(self, **kwargs):
            assert kwargs["ExpectedBucketOwner"] == "111111111111"

        def get_public_access_block(self, **kwargs):
            return {
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True,
                    "IgnorePublicAcls": True,
                    "BlockPublicPolicy": True,
                    "RestrictPublicBuckets": True,
                }
            }

        def get_bucket_policy(self, **kwargs):
            return {
                "Policy": module.json.dumps(
                    {"Statement": [{"Effect": "Allow", "Principal": principal}]}
                )
            }

        def get_bucket_versioning(self, **kwargs):
            pytest.fail("Website policy must be rejected before publication")

    with pytest.raises(ValueError, match="website distribution"):
        module.mirror(manifest, package, "private", "111111111111", Session())


def desktop_package(**changes):
    return {
        "platform": "macos",
        "architecture": "arm64",
        "version": "0.2.0",
        "source_commit": "a" * 40,
        "source_tree_sha256": "b" * 64,
        "artifact_sha256": "c" * 64,
        "size_bytes": 100,
        "filename": "academy-bridge-macos-arm64.zip",
        "notarized": True,
        "tests_passed": True,
        "status": "approved",
        **changes,
    }


def test_desktop_download_uses_exact_private_manifest_and_temporary_url(monkeypatch):
    package = catalog.CompanionPackage.model_validate(desktop_package())

    class S3:
        def head_object(self, **kwargs):
            assert kwargs == {
                "Bucket": "private-connectors",
                "Key": package.object_key,
                "ChecksumMode": "ENABLED",
            }
            return {
                "Metadata": {"sha256": package.artifact_sha256},
                "ChecksumSHA256": base64.b64encode(bytes.fromhex(package.artifact_sha256)).decode(),
                "ContentLength": 100,
            }

        def generate_presigned_url(self, operation, **kwargs):
            assert operation == "get_object" and kwargs["ExpiresIn"] == 300
            assert kwargs["Params"]["Key"] == package.object_key
            return "https://private-connectors.s3.example/signed-package"

    monkeypatch.setenv("ACADEMY_CONNECTOR_BUCKET", "private-connectors")
    monkeypatch.setattr(catalog.boto3, "client", lambda _: S3())
    result = catalog.companion_download(
        {"companion_packages": [desktop_package()]}, "macos", "arm64"
    )
    assert result["status"] == "available" and result["download_url"].startswith("https://")
    assert (
        catalog.companion_download({"companion_packages": [desktop_package()]}, "macos", "x86_64")
        is None
    )
    with pytest.raises(ValueError):
        catalog.companion_download(
            {"companion_packages": [desktop_package(notarized=False)]}, "macos", "arm64"
        )


def test_catalog_reports_unavailable_instead_of_leaking_storage_error(monkeypatch):
    def unavailable(*_):
        raise ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "private bucket detail"}}, "HeadObject"
        )

    monkeypatch.setattr(catalog, "companion_download", unavailable)
    with pytest.raises(HTTPException) as failure:
        catalog.public_catalog()
    assert failure.value.status_code == 503
    assert "private bucket detail" not in failure.value.detail
