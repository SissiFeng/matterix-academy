import importlib.util
import json
from pathlib import Path

import pytest
from academy.connector_catalog import (
    ConnectorArtifact,
    approved_release,
    public_catalog,
    read_catalog,
)


def artifact(**changes):
    return {
        "schema_version": "academy.connector-artifact/1",
        "instrument": "flex",
        "repository": "AccelerationConsortium/opentrons-flex",
        "source_commit": "a" * 40,
        "artifact_source_commit": "a" * 40,
        "version": "0.9.1",
        "filename": "flex.zip",
        "artifact_sha256": "b" * 64,
        "size_bytes": 100,
        "build_run_id": 12,
        "github_artifact_id": 34,
        "artifact_kind": "actions",
        "build_succeeded": True,
        "tests_passed": True,
        "status": "candidate",
        "platforms": ["macos", "linux"],
        "robot_arch": "aarch64",
        "supported_firmware": ["9.0.0"],
        "execution_transport": "opentrons-protocol-engine",
        **changes,
    }


def test_current_candidates_never_unlock_hardware():
    assert approved_release("flex", "macos") is None
    assert approved_release("ot2", "linux") is None
    catalog = public_catalog()
    assert all(r["download_url"] is None for r in catalog["releases"])
    assert catalog["companion"]["status"] == "source-only"


@pytest.mark.parametrize(
    "changes",
    [
        {"repository": "attacker/opentrons-flex"},
        {"filename": "../package.zip"},
        {"filename": "package;run.sh"},
        {"robot_arch": "armv7l"},
        {"status": "approved"},
        {"platforms": ["windows"]},
    ],
)
def test_unsafe_or_unqualified_artifacts_rejected(changes):
    with pytest.raises(ValueError):
        ConnectorArtifact.model_validate(artifact(**changes))


def test_approval_requires_each_independent_gate():
    fields = artifact(
        status="approved",
        rollback_test_passed=True,
        no_motion_startup_passed=True,
        qualification_report_sha256="c" * 64,
        runtime_contract_id="contract-v1",
        runtime_release_id="release-1",
        runtime_bundle_sha256="d" * 64,
    )
    good = ConnectorArtifact.model_validate(fields)
    assert good.object_key == f"connectors/approved/flex/{'a' * 40}/{'b' * 64}/flex.zip"
    for key in (
        "build_succeeded",
        "tests_passed",
        "rollback_test_passed",
        "no_motion_startup_passed",
    ):
        with pytest.raises(ValueError):
            ConnectorArtifact.model_validate(fields | {key: False})
    with pytest.raises(ValueError):
        ConnectorArtifact.model_validate(fields | {"artifact_source_commit": "d" * 40})


def test_duplicate_active_release_is_rejected(tmp_path):
    item = artifact(
        status="approved",
        rollback_test_passed=True,
        no_motion_startup_passed=True,
        qualification_report_sha256="c" * 64,
        runtime_contract_id="contract-v1",
        runtime_release_id="release-1",
        runtime_bundle_sha256="d" * 64,
    )
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps({"schema": "academy.connector-catalog/1", "artifacts": [item, item]})
    )
    with pytest.raises(ValueError, match="Only one"):
        read_catalog(path)


def test_invalid_catalog_fails_closed(tmp_path, monkeypatch):
    path = tmp_path / "broken.json"
    path.write_text("not json")
    monkeypatch.setenv("ACADEMY_CONNECTOR_CATALOG", str(path))
    assert approved_release("flex", "macos") is None


def test_release_verifier_rejects_tampering_and_symlinks(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "connector_release", Path(__file__).parents[3] / "scripts/connector-release.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    package = tmp_path / "package.zip"
    package.write_bytes(b"x" * 100)
    manifest = ConnectorArtifact.model_validate(artifact())
    with pytest.raises(ValueError, match="SHA256"):
        module.verify_file(manifest, package)
    link = tmp_path / "link.zip"
    link.symlink_to(package)
    with pytest.raises(ValueError, match="non-symlink"):
        module.verify_file(manifest, link)
