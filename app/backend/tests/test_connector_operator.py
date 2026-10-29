"""Operator CLI boundaries on SQLite and mocked DynamoDB; no physical/cloud acceptance."""

import copy
import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from academy.companion.config import write_private
from academy.connections import (
    BINDINGS,
    DEVICE_LOCKS,
    QUALIFICATIONS,
    ConnectionService,
    ConnectorProbe,
)
from academy.connector_catalog import ConnectorArtifact
from academy.runs import revised
from academy.store import Conflict
from fastapi import HTTPException
from test_connections import RELEASE, pair, ready, receipt, resolution_for
from test_connector_catalog import artifact
from test_connector_protocol import profile_for


def script(name):
    spec = importlib.util.spec_from_file_location(
        f"operator_test_{name.replace('-', '_')}",
        Path(__file__).parents[3] / f"scripts/{name}.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def invoke(module, monkeypatch, *arguments):
    monkeypatch.setattr(sys, "argv", [module.__file__, *map(str, arguments)])
    return module.main()


@pytest.fixture
def qualification_context(store, tmp_path, monkeypatch):
    module = script("connector-qualify")
    profile = profile_for()
    release = {
        "status": "approved",
        "platform": "linux",
        "execution_transport": "opentrons-protocol-engine",
        "supported_firmware": [profile.firmware],
        **{key: getattr(profile, key) for key in BINDINGS if key != "profile_sha256"},
    }
    service = ConnectionService(store, approved_release=lambda *args: release)
    device, installation, _, _ = pair(service)
    service.probe(
        installation,
        ConnectorProbe(
            **{key: getattr(profile, key) for key in BINDINGS if key != "profile_sha256"},
            profile_sha256=profile.sha256,
            capabilities=["protocol-engine"],
            reachable=True,
        ),
    )
    evidence = {
        "operator": "SOFTWARE-FIXTURE-ONLY",
        "checked_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
        "connection_id": device["id"],
        "installation_id": installation["installation_id"],
        "profile_sha256": profile.sha256,
        "installed_release_verified": True,
        "sila_identity_verified": True,
        "calibration_verified": True,
        "protocol_engine_verified": True,
        "startup_without_motion_verified": True,
        "rollback_recovery_verified": True,
        "supervised_acceptance_report": "Software fixture, not a hardware report",
    }
    profile_path, evidence_path = tmp_path / "profile.json", tmp_path / "evidence.json"
    write_private(profile_path, profile.model_dump(mode="json"))
    write_private(evidence_path, evidence)
    monkeypatch.setattr(module, "SQLiteStore", lambda path: store)
    monkeypatch.setattr(module, "approved_release", lambda *args: release)
    args = [
        "--sqlite",
        tmp_path / "ignored.sqlite",
        "--owner",
        "alice",
        "--profile",
        profile_path,
        "--evidence",
        evidence_path,
    ]
    return module, service, profile, release, device, evidence_path, args


def test_qualification_preview_is_read_only_then_apply_binds_exact_evidence(
    qualification_context, monkeypatch, capsys
):
    module, service, profile, _, device, evidence_path, args = qualification_context
    before = service.raw("alice", device["id"])
    invoke(module, monkeypatch, *args)
    preview = json.loads(capsys.readouterr().out)
    assert not preview["applied"] and not preview["hardware_commands_executed"]
    assert service.store.get(QUALIFICATIONS, device["id"]) is None
    assert service.raw("alice", device["id"]) == before
    invoke(module, monkeypatch, *args, "--apply", "--confirm-supervised-qualification")
    applied = json.loads(capsys.readouterr().out)
    record = service.store.get(QUALIFICATIONS, device["id"])
    assert applied["applied"] and record == applied["qualification"]
    assert record["owner"] == "alice" and record["profile_sha256"] == profile.sha256
    assert record["evidence_sha256"] == hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    assert service.qualification(service.raw("alice", device["id"])) == record
    with pytest.raises(Conflict):
        invoke(module, monkeypatch, *args, "--apply", "--confirm-supervised-qualification")
    assert service.store.get(QUALIFICATIONS, device["id"]) == record


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("source_commit", "e" * 40),
        ("artifact_sha256", "e" * 64),
        ("runtime_bundle_sha256", "e" * 64),
        ("runtime_contract_id", "different-contract"),
        ("runtime_release_id", "different-runtime"),
        ("supported_firmware", ["different-firmware"]),
    ],
)
def test_qualification_rejects_changed_current_release_before_writes(
    qualification_context, monkeypatch, field, replacement
):
    module, service, _, release, device, _, args = qualification_context
    release[field] = replacement
    with pytest.raises(SystemExit) as error:
        invoke(module, monkeypatch, *args, "--apply", "--confirm-supervised-qualification")
    assert error.value.code == 2
    assert service.store.get(QUALIFICATIONS, device["id"]) is None


def test_qualification_requires_explicit_apply_confirmation_and_correct_owner(
    qualification_context, monkeypatch
):
    module, service, _, _, device, _, args = qualification_context
    with pytest.raises(SystemExit) as error:
        invoke(module, monkeypatch, *args, "--apply")
    assert error.value.code == 2
    wrong_owner = ["bob" if arg == "alice" else arg for arg in args]
    with pytest.raises(HTTPException) as error:
        invoke(module, monkeypatch, *wrong_owner, "--apply", "--confirm-supervised-qualification")
    assert error.value.status_code == 404
    assert service.store.get(QUALIFICATIONS, device["id"]) is None


def test_qualification_connection_change_during_apply_is_atomic(qualification_context, monkeypatch):
    module, service, _, _, device, _, args = qualification_context
    original = service.store.transact

    def changed_connection(writes):
        current = service.raw("alice", device["id"])
        service.store.put(
            "alice",
            f"connection#{device['id']}",
            revised(current, installation_id=None, status="revoked"),
            current["version"],
        )
        return original(writes)

    monkeypatch.setattr(service.store, "transact", changed_connection)
    with pytest.raises(Conflict):
        invoke(module, monkeypatch, *args, "--apply", "--confirm-supervised-qualification")
    assert service.store.get(QUALIFICATIONS, device["id"]) is None
    assert service.raw("alice", device["id"])["status"] == "revoked"


def test_qualification_rejects_profile_change_even_when_release_is_unchanged(
    qualification_context, monkeypatch
):
    module, service, profile, _, device, evidence_path, args = qualification_context
    profile_path = Path(args[args.index("--profile") + 1])
    changed = profile.model_dump(mode="json")
    changed["calibration_sha256"] = "e" * 64
    profile_path.write_text(json.dumps(changed))
    original_evidence = evidence_path.read_bytes()
    with pytest.raises(SystemExit) as error:
        invoke(module, monkeypatch, *args, "--apply", "--confirm-supervised-qualification")
    assert error.value.code == 2
    assert evidence_path.read_bytes() == original_evidence
    assert service.store.get(QUALIFICATIONS, device["id"]) is None


@pytest.fixture
def resolution_context(store, tmp_path, monkeypatch):
    module = script("connector-resolve")
    service = ConnectionService(
        store, enabled=True, approved_release=lambda *args: copy.deepcopy(RELEASE)
    )
    device, installation, _, _, _, request = ready(service)
    service.submit("alice", device["id"], request)
    command = service.claim(installation)
    unknown = service.receipt(
        installation, request.run_id, receipt(command, outcome="unknown", stop_confirmed=False)
    )
    evidence = resolution_for(command, unknown["version"])
    path = tmp_path / "resolution.json"
    write_private(path, evidence.model_dump(mode="json"))
    monkeypatch.setattr(module, "SQLiteStore", lambda path: store)
    args = [
        "--sqlite",
        tmp_path / "ignored.sqlite",
        "--run-id",
        request.run_id,
        "--evidence",
        path,
    ]
    return module, service, device, request, path, args


def test_resolution_cli_preview_preserves_locks_apply_preserves_unknown_history(
    resolution_context, monkeypatch, capsys
):
    module, service, device, request, _, args = resolution_context
    before = service.run_raw(request.run_id)
    lock = service.store.get(DEVICE_LOCKS, before["lock_key"])
    invoke(module, monkeypatch, *args)
    assert json.loads(capsys.readouterr().out)["applied"] is False
    assert service.run_raw(request.run_id) == before
    assert service.store.get(DEVICE_LOCKS, before["lock_key"]) == lock
    invoke(module, monkeypatch, *args, "--apply", "--confirm-physically-stopped-and-released")
    output = json.loads(capsys.readouterr().out)
    after = service.run_raw(request.run_id)
    assert output["applied"] and not output["hardware_commands_executed"]
    assert after["status"] == "unknown" and after["receipt"] == before["receipt"]
    assert after["resolution"]["replay_authorized"] is False
    assert service.raw("alice", device["id"])["active_run_id"] is None
    assert service.store.get(DEVICE_LOCKS, before["lock_key"])["active_run_id"] is None
    invoke(module, monkeypatch, *args, "--apply", "--confirm-physically-stopped-and-released")
    assert service.run_raw(request.run_id) == after


@pytest.mark.parametrize("change", ["stale_version", "wrong_installation", "no_confirmation"])
def test_resolution_cli_rejects_wrong_authority_without_unlocking(
    resolution_context, monkeypatch, change
):
    module, service, device, request, path, args = resolution_context
    before = service.run_raw(request.run_id)
    evidence = json.loads(path.read_text())
    if change == "stale_version":
        evidence["expected_version"] -= 1
    elif change == "wrong_installation":
        evidence["installation_id"] = str(uuid4())
    path.write_text(json.dumps(evidence))
    flags = [] if change == "no_confirmation" else ["--confirm-physically-stopped-and-released"]
    with pytest.raises(SystemExit if change == "no_confirmation" else Conflict):
        invoke(module, monkeypatch, *args, "--apply", *flags)
    assert service.run_raw(request.run_id) == before
    assert service.raw("alice", device["id"])["active_run_id"] == str(request.run_id)
    assert service.store.get(DEVICE_LOCKS, before["lock_key"])["active_run_id"] == str(
        request.run_id
    )


@pytest.mark.parametrize("operator_script", ["connector-qualify", "connector-resolve"])
def test_operator_aws_account_guard_precedes_dynamodb_access(
    qualification_context, resolution_context, monkeypatch, operator_script
):
    import boto3

    context = (
        qualification_context if operator_script == "connector-qualify" else resolution_context
    )
    module, args = context[0], context[-1]
    args = ["--table", "fixture-table", *args[2:], "--expected-account", "111111111111"]

    class Identity:
        def get_caller_identity(self):
            return {"Account": "222222222222"}

    def client(service):
        assert service == "sts"
        return Identity()

    def forbidden_store(table):
        pytest.fail("A mismatched AWS identity reached the data store")

    monkeypatch.setattr(boto3, "client", client)
    monkeypatch.setattr(module, "DynamoStore", forbidden_store)
    with pytest.raises(SystemExit) as error:
        invoke(module, monkeypatch, *args)
    assert error.value.code == 2


def approved_artifact():
    return ConnectorArtifact.model_validate(
        artifact(
            status="approved",
            rollback_test_passed=True,
            no_motion_startup_passed=True,
            qualification_report_sha256="c" * 64,
            runtime_contract_id="contract-v1",
            runtime_release_id="release-1",
            runtime_bundle_sha256="d" * 64,
        )
    )


@pytest.mark.parametrize(
    "corruption", ["wrong_source", "wrong_run", "failed_tests", "wrong_digest"]
)
def test_publication_rechecks_exact_build_and_tests(monkeypatch, corruption):
    module = script("connector-release")
    manifest = approved_artifact()
    run = {
        "repository": {"full_name": manifest.repository},
        "head_sha": manifest.source_commit,
        "status": "completed",
        "conclusion": "success",
    }
    package = {
        "expired": False,
        "workflow_run": {"id": manifest.build_run_id, "head_sha": manifest.source_commit},
        "digest": f"sha256:{manifest.artifact_sha256}",
    }
    tests = {"workflow_runs": [{"name": "CI", "conclusion": "success"}]}
    if corruption == "wrong_source":
        run["head_sha"] = "e" * 40
    elif corruption == "wrong_run":
        package["workflow_run"]["id"] += 1
    elif corruption == "failed_tests":
        tests["workflow_runs"][0]["conclusion"] = "failure"
    elif corruption == "wrong_digest":
        package["digest"] = "sha256:" + "e" * 64

    def github(path):
        if "/artifacts/" in path:
            return package
        if "?" in path:
            return tests
        return run

    monkeypatch.setattr(module, "github", github)
    with pytest.raises(ValueError):
        module.verify_build(manifest)


def test_immutable_upload_lost_reply_accepts_only_same_server_checksum():
    from botocore.exceptions import ClientError

    module = script("connector-release")
    digest = hashlib.sha256(b"reviewed").hexdigest()

    class ExistingObject:
        def __init__(self, checksum):
            self.checksum = checksum
            self.puts = []

        def put_object(self, **kwargs):
            self.puts.append(kwargs)
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")

        def head_object(self, **kwargs):
            assert kwargs["ChecksumMode"] == "ENABLED"
            return {"ChecksumSHA256": self.checksum}

    same = ExistingObject(module.base64.b64encode(bytes.fromhex(digest)).decode())
    module.immutable_put(
        same, "private-fixture", "fixed-key", b"reviewed", digest, "application/zip"
    )
    assert len(same.puts) == 1 and same.puts[0]["IfNoneMatch"] == "*"
    different = ExistingObject("different")
    with pytest.raises(ValueError, match="different bytes"):
        module.immutable_put(
            different, "private-fixture", "fixed-key", b"reviewed", digest, "application/zip"
        )
    assert len(different.puts) == 1
