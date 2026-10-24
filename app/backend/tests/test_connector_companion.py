"""Software-only companion fault/transport checks; no actual installation or robot motion."""

import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from academy.companion.client import AcademyClient, Credentials, recover, run_once
from academy.companion.config import (
    LocalConfig,
    private_directory,
    read_private,
    validate_url,
    write_private,
)
from academy.companion.journal import Journal
from academy.companion.packages import stage_archive
from academy.companion.protocol import ProtocolEngine
from academy.remote_run import workflow_digest
from test_connector_protocol import plan_for, profile_for
from test_connector_protocol import robot_http as fixture_robot_http

robot_http = fixture_robot_http


def credentials():
    return Credentials(
        installation_id=uuid4(), secret="s" * 43, academy_url="http://127.0.0.1:8000"
    )


def config(profile, robot_url):
    return LocalConfig(
        academy_url="http://127.0.0.1:8000",
        allowed_academy_origins=["http://127.0.0.1:8000"],
        loopback_development=True,
        robot_url=robot_url,
        profile=profile,
    )


def command_for(profile, creds):
    plan = plan_for()
    return {
        "run_id": str(uuid4()),
        "connection_id": str(uuid4()),
        "installation_id": str(creds.installation_id),
        "version": 2,
        "plan_hash": workflow_digest(plan),
        "plan": plan.model_dump(mode="json"),
        "instrument": profile.instrument,
        "serial": profile.serial,
        "release_id": profile.release_id,
        "artifact_sha256": profile.artifact_sha256,
        "profile_sha256": profile.sha256,
        "source_commit": profile.source_commit,
        "firmware": profile.firmware,
        "runtime_contract_id": profile.runtime_contract_id,
        "runtime_release_id": profile.runtime_release_id,
        "runtime_bundle_sha256": profile.runtime_bundle_sha256,
        "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
        "status": "claimed",
        "stop_requested": False,
    }


class CloudFixture:
    def __init__(self, command):
        self.command = command
        self.receipts = []
        self.claimed = False
        self.fail_receipt_once = False
        self.repeat_claim = False
        self.resolutions = {}

    def handle(self, request):
        path = request.url.path
        if path == "/companion/command":
            if self.claimed and not self.repeat_claim:
                return httpx.Response(204)
            self.claimed = True
            return httpx.Response(200, json=self.command)
        if path.endswith("/receipt"):
            self.receipts.append(json.loads(request.content))
            if self.fail_receipt_once:
                self.fail_receipt_once = False
                raise httpx.ReadTimeout("lost receipt response", request=request)
            return httpx.Response(200, json={"accepted": True})
        if path.startswith("/companion/commands/"):
            return httpx.Response(
                200, json=self.resolutions.get(path.rsplit("/", 1)[1], self.command)
            )
        raise AssertionError(path)


def local_client(robot, cloud, creds):
    return AcademyClient(
        config(robot.profile, robot.url), creds, transport=httpx.MockTransport(cloud.handle)
    )


def test_private_credentials_and_symlink_rejection(tmp_path):
    state = private_directory(tmp_path / "state")
    path = state / "credentials.json"
    write_private(path, {"secret": "not-printed"})
    assert state.stat().st_mode & 0o777 == 0o700
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(read_private(path))["secret"] == "not-printed"
    with pytest.raises(FileExistsError):
        write_private(path, {})
    linked = state / "linked"
    linked.symlink_to(path)
    with pytest.raises(OSError):
        read_private(linked)
    path.chmod(0o644)
    with pytest.raises(ValueError, match="0600"):
        read_private(path)


@pytest.mark.parametrize(
    "url,robot,dev",
    [
        ("http://example.com", False, False),
        ("http://127.0.0.1", False, False),
        ("https://example.com/robot", False, False),
        ("https://u:p@example.com", False, False),
        ("https://example.com?token=secret", False, False),
        ("http://8.8.8.8", True, False),
        ("http://robot.local", True, False),
        ("http://169.254.169.254/latest", True, False),
    ],
)
def test_endpoint_validation(url, robot, dev):
    with pytest.raises(ValueError):
        validate_url(url, robot=robot, dev=dev)


def test_exact_origin_allowlist():
    with pytest.raises(ValueError, match="allowlisted"):
        LocalConfig(
            academy_url="https://other.example",
            allowed_academy_origins=["https://academy.example"],
            robot_url="http://192.168.1.2",
            profile=profile_for(),
        )


def test_cross_process_lock(tmp_path):
    state = private_directory(tmp_path / "state")
    with Journal(state):
        script = "from academy.companion.journal import Journal; from pathlib import Path; Journal(Path(__import__('sys').argv[1]))"
        completed = subprocess.run(
            [sys.executable, "-c", script, str(state)],
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
            capture_output=True,
            text=True,
        )
        assert completed.returncode != 0
        assert "Another companion" in completed.stderr


def test_restart_marks_unknown_without_replay_and_immutable_outbox(tmp_path):
    creds, profile = credentials(), profile_for()
    command = command_for(profile, creds)
    with Journal(private_directory(tmp_path / "state")) as journal:
        assert journal.begin(command)
        journal.phase(command["run_id"], "play_attempted", protocol_id="p", robot_run_id="r")
    with Journal(tmp_path / "state") as journal:
        recover(journal)
        receipt = journal.outbox()[0][1]
        assert receipt["outcome"] == "unknown" and receipt["robot_run_id"] == "r"
        journal.finish(command["run_id"], receipt)
        with pytest.raises(ValueError, match="immutable"):
            journal.finish(command["run_id"], {**receipt, "outcome": "completed"})
        assert not journal.begin(command)
        with pytest.raises(RuntimeError, match="Unresolved"):
            journal.begin({**command, "run_id": str(uuid4())})


def test_real_robot_transport_once_and_duplicate_claim_never_replays(tmp_path, robot_http):
    creds = credentials()
    cloud = CloudFixture(command_for(robot_http.profile, creds))
    cloud.repeat_claim = True
    client = local_client(robot_http, cloud, creds)
    engine = ProtocolEngine(robot_http.url, robot_http.profile, sila_probe=lambda: None)
    with Journal(private_directory(tmp_path / "state")) as journal:
        assert run_once(
            client, engine, journal, robot_http.profile, approve=lambda c: True, poll_seconds=0
        )
        assert not run_once(
            client,
            engine,
            journal,
            robot_http.profile,
            approve=lambda c: pytest.fail("reapproval"),
            poll_seconds=0,
        )
    assert (
        len([p for m, p, *_ in robot_http.requests if m == "POST" and p.endswith("/actions")]) == 1
    )
    assert cloud.receipts[0]["outcome"] == "completed"
    assert cloud.receipts[0]["source_commit"] == robot_http.profile.source_commit
    assert cloud.receipts[0]["stop_confirmed"]
    client.close()
    engine.close()


def test_lost_play_response_is_unknown_and_never_replayed(tmp_path, robot_http):
    robot_http.fail_play = True
    creds = credentials()
    cloud = CloudFixture(command_for(robot_http.profile, creds))
    client = local_client(robot_http, cloud, creds)
    engine = ProtocolEngine(robot_http.url, robot_http.profile, sila_probe=lambda: None)
    with Journal(private_directory(tmp_path / "state")) as journal:
        run_once(
            client, engine, journal, robot_http.profile, approve=lambda c: True, poll_seconds=0
        )
        assert cloud.receipts[0]["outcome"] == "unknown"
        run_once(
            client,
            engine,
            journal,
            robot_http.profile,
            approve=lambda c: pytest.fail("reapproval"),
            poll_seconds=0,
        )
    assert (
        len([p for m, p, *_ in robot_http.requests if m == "POST" and p.endswith("/actions")]) == 1
    )
    client.close()
    engine.close()


def test_lost_receipt_reposts_same_receipt_only(tmp_path, robot_http):
    creds = credentials()
    cloud = CloudFixture(command_for(robot_http.profile, creds))
    cloud.fail_receipt_once = True
    client = local_client(robot_http, cloud, creds)
    engine = ProtocolEngine(robot_http.url, robot_http.profile, sila_probe=lambda: None)
    state = private_directory(tmp_path / "state")
    with Journal(state) as journal:
        with pytest.raises(httpx.ReadTimeout):
            run_once(
                client, engine, journal, robot_http.profile, approve=lambda c: True, poll_seconds=0
            )
    mutations = len([m for m, *_ in robot_http.requests if m != "GET"])
    with Journal(state) as journal:
        run_once(
            client,
            engine,
            journal,
            robot_http.profile,
            approve=lambda c: pytest.fail("reapproval"),
            poll_seconds=0,
        )
    assert cloud.receipts[0] == cloud.receipts[1]
    assert len([m for m, *_ in robot_http.requests if m != "GET"]) == mutations
    client.close()
    engine.close()


def test_hash_mismatch_fails_before_prompt_or_mutation(tmp_path, robot_http):
    creds = credentials()
    command = command_for(robot_http.profile, creds)
    command["plan"]["title"] = "changed after DT"
    cloud = CloudFixture(command)
    client = local_client(robot_http, cloud, creds)
    engine = ProtocolEngine(robot_http.url, robot_http.profile, sila_probe=lambda: None)
    with Journal(private_directory(tmp_path / "state")) as journal:
        run_once(
            client, engine, journal, robot_http.profile, approve=lambda c: pytest.fail("approval")
        )
    assert not robot_http.requests
    assert cloud.receipts[0]["outcome"] == "failed"
    client.close()
    engine.close()


def make_tar(path, *, name="package/file.txt", symlink=False):
    with tarfile.open(path, "w:gz") as tar:
        info = tarfile.TarInfo(name)
        if symlink:
            info.type, info.linkname = tarfile.SYMTYPE, "/tmp/escape"
            tar.addfile(info)
        else:
            data = b"verified fixture contents"
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "name,symlink",
    [
        ("../escape", False),
        ("/absolute", False),
        ("package/escape", True),
        ("package\\escape", False),
    ],
)
def test_safe_package_staging_rejects_traversal_and_links(tmp_path, name, symlink):
    archive = tmp_path / "package.tar.gz"
    checksum = make_tar(archive, name=name, symlink=symlink)
    parent = private_directory(tmp_path / "staging")
    with pytest.raises(ValueError, match="Unsafe"):
        stage_archive(archive, checksum, parent / "artifact")
    assert not list(parent.iterdir())


def test_staging_checks_hash_bounds_and_never_overwrites(tmp_path):
    archive = tmp_path / "package.tar.gz"
    checksum = make_tar(archive)
    parent = private_directory(tmp_path / "staging")
    with pytest.raises(ValueError, match="SHA256"):
        stage_archive(archive, "0" * 64, parent / "artifact")
    stage_archive(archive, checksum, parent / "artifact")
    assert (parent / "artifact/package/file.txt").read_text() == "verified fixture contents"
    with pytest.raises(ValueError, match="replace"):
        stage_archive(archive, checksum, parent / "artifact")
    with pytest.raises(ValueError, match="Unsafe"):
        stage_archive(archive, checksum, parent / "other", max_files=0)


def test_bounded_sila_standard_property_decoding():
    from academy.companion.identity import boolean, strings

    assert strings(b"\x0a\x05\x0a\x03abc\x0a\x05\x0a\x03def") == ["abc", "def"]
    assert boolean(b"\x0a\x02\x08\x01") is True
    assert boolean(b"\x0a\x00") is False
    for malformed in (b"", b"\x0a\xff", b"\x0a\x02\x08\x03", b"x" * 65537):
        with pytest.raises(ValueError):
            boolean(malformed)


def test_sila_missing_dependency_fails_closed(monkeypatch):
    import importlib.metadata

    from academy.companion.identity import probe_sila

    def unavailable(*args):
        raise importlib.metadata.PackageNotFoundError("grpcio")

    monkeypatch.setattr(importlib.metadata, "version", unavailable)
    with pytest.raises(RuntimeError, match="pinned"):
        probe_sila("http://127.0.0.1:31950", profile_for())


def test_cloud_revocation_requests_bound_stop_not_replay(tmp_path, robot_http):
    creds = credentials()
    cloud = CloudFixture(command_for(robot_http.profile, creds))
    robot_http.hold_running = True
    original = cloud.handle

    def handle(request):
        if (
            request.url.path.startswith("/companion/commands/")
            and not request.url.path.endswith("/receipt")
            and robot_http.status == "running"
        ):
            return httpx.Response(
                200, json={**cloud.command, "status": "unknown", "stop_requested": True}
            )
        return original(request)

    client = AcademyClient(
        config(robot_http.profile, robot_http.url), creds, transport=httpx.MockTransport(handle)
    )
    engine = ProtocolEngine(robot_http.url, robot_http.profile, sila_probe=lambda: None)
    with Journal(private_directory(tmp_path / "state")) as journal:
        run_once(
            client, engine, journal, robot_http.profile, approve=lambda c: True, poll_seconds=0
        )
    assert cloud.receipts[0]["outcome"] == "stopped"
    actions = [
        json.loads(body)["data"]["actionType"]
        for _, path, body, _ in robot_http.requests
        if path.endswith("/actions")
    ]
    assert actions == ["play", "stop"]
    client.close()
    engine.close()


def make_zip(path, entries, *, symlink=False, compress=True):
    import stat
    import zipfile

    with zipfile.ZipFile(
        path, "w", compression=zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
    ) as archive:
        for name, data in entries:
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
            info.external_attr = (
                (stat.S_IFLNK | 0o777) << 16 if symlink else (stat.S_IFREG | 0o600) << 16
            )
            archive.writestr(info, data)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_actions_zip_stages_with_private_files(tmp_path):
    archive = tmp_path / "github-actions.zip"
    checksum = make_zip(
        archive,
        [("dist/runtime.whl", b"reviewed runtime fixture"), ("dist/runtime-manifest.json", b"{}")],
    )
    parent = private_directory(tmp_path / "staging")
    staged = stage_archive(archive, checksum, parent / "release")
    assert (staged / "dist/runtime.whl").read_bytes() == b"reviewed runtime fixture"
    assert (staged / "dist/runtime.whl").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "name,symlink",
    [
        ("../escape", False),
        ("/absolute", False),
        ("C:/drive", False),
        ("a/./b", False),
        ("a\\b", False),
        ("package/link", True),
    ],
)
def test_zip_rejects_unsafe_paths_and_symlink(tmp_path, name, symlink):
    archive = tmp_path / "artifact.zip"
    checksum = make_zip(archive, [(name, b"/tmp/escape")], symlink=symlink)
    parent = private_directory(tmp_path / "staging")
    with pytest.raises(ValueError, match="Unsafe"):
        stage_archive(archive, checksum, parent / "artifact")
    assert not list(parent.iterdir())


def test_zip_duplicate_compression_and_expanded_limits(tmp_path):
    archive = tmp_path / "artifact.zip"
    parent = private_directory(tmp_path / "staging")
    with pytest.warns(UserWarning, match="Duplicate"):
        checksum = make_zip(archive, [("same", b"first"), ("same", b"second")])
    with pytest.raises(ValueError, match="duplicate"):
        stage_archive(archive, checksum, parent / "artifact")
    checksum = make_zip(archive, [("bomb", b"0" * 100000)])
    with pytest.raises(ValueError, match="compression"):
        stage_archive(archive, checksum, parent / "artifact", max_compression_ratio=100)
    with pytest.raises(ValueError, match="expanded"):
        stage_archive(
            archive, checksum, parent / "artifact", max_bytes=2000, max_compression_ratio=100000
        )
    with pytest.raises(ValueError, match="file limit"):
        stage_archive(archive, checksum, parent / "artifact", max_files=0)
    assert not list(parent.iterdir())


def resolution_for(command, *, protocol_id="protocol-1", robot_run_id="robot-run-1"):
    fields = (
        "connection_id",
        "installation_id",
        "plan_hash",
        "instrument",
        "serial",
        "release_id",
        "artifact_sha256",
        "profile_sha256",
        "source_commit",
        "firmware",
        "runtime_contract_id",
        "runtime_release_id",
        "runtime_bundle_sha256",
    )
    expected_version = command["version"] + 2
    request = {
        **{key: command[key] for key in fields},
        "expected_version": expected_version,
        "resolution_id": str(uuid4()),
        "protocol_id": protocol_id,
        "robot_run_id": robot_run_id,
        "no_run_created": robot_run_id is None,
        "stopped": True,
        "released": True,
        "operator_id": "fixture-operator",
        "evidence_sha256": "e" * 64,
        "detail": "SOFTWARE FIXTURE: observed stopped and released original run",
    }
    return {
        **command,
        "version": expected_version + 1,
        "status": "unknown",
        "stop_requested": True,
        "resolution": {
            "request": request,
            "resolved_at": datetime.now(UTC).timestamp(),
            "historical_status": "unknown",
            "replay_authorized": False,
        },
    }


def test_authoritative_resolution_unlocks_new_command_never_replays_old(tmp_path, robot_http):
    creds = credentials()
    old = command_for(robot_http.profile, creds)
    cloud = CloudFixture(old)
    client = local_client(robot_http, cloud, creds)
    engine = ProtocolEngine(robot_http.url, robot_http.profile, sila_probe=lambda: None)
    state = private_directory(tmp_path / "state")
    robot_http.fail_play = True
    with Journal(state) as journal:
        run_once(
            client, engine, journal, robot_http.profile, approve=lambda c: True, poll_seconds=0
        )
        original_receipt = cloud.receipts[0]
        assert original_receipt["outcome"] == "unknown"
    # Software fixture represents an administrative inspection/release, not an automatic stop/retry.
    robot_http.fail_play, robot_http.current = False, False
    cloud.resolutions[old["run_id"]] = resolution_for(old)
    new = command_for(robot_http.profile, creds)
    cloud.command, cloud.claimed = new, False
    approved = []
    with Journal(state) as journal:
        run_once(
            client,
            engine,
            journal,
            robot_http.profile,
            approve=lambda c: approved.append(str(c.run_id)) or True,
            poll_seconds=0,
        )
        row = journal.db.execute(
            "SELECT receipt FROM commands WHERE id=?", (old["run_id"],)
        ).fetchone()
        assert json.loads(row["receipt"]) == original_receipt
        assert len(list(journal.db.execute("SELECT * FROM resolutions"))) == 1
        assert not journal.unresolved()
        # The previously attempted ID remains non-executable forever.
        saved = journal.db.execute(
            "SELECT command FROM commands WHERE id=?", (old["run_id"],)
        ).fetchone()
        assert not journal.begin(json.loads(saved["command"]))
        import sqlite3

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            journal.db.execute("DELETE FROM resolutions")
    assert approved == [new["run_id"]]
    assert cloud.receipts[-1]["command_id"] == new["run_id"]
    assert cloud.receipts[-1]["outcome"] == "completed"
    plays = [
        path
        for _, path, body, _ in robot_http.requests
        if path.endswith("/actions") and json.loads(body)["data"]["actionType"] == "play"
    ]
    assert plays == ["/runs/robot-run-1/actions", "/runs/robot-run-2/actions"]
    client.close()
    engine.close()


@pytest.mark.parametrize(
    "corruption",
    [
        "installation",
        "plan",
        "physical_run",
        "replay",
        "historical",
        "quiescence",
        "revision",
        "future",
        "extra",
    ],
)
def test_resolution_rejects_forged_or_mismatched_evidence(tmp_path, corruption):
    from academy.companion.client import Command, validate_resolution

    creds, profile = credentials(), profile_for()
    command = command_for(profile, creds)
    current = resolution_for(command)
    request = current["resolution"]["request"]
    if corruption == "installation":
        request["installation_id"] = str(uuid4())
    elif corruption == "plan":
        current["plan"]["title"] = "forged"
    elif corruption == "physical_run":
        request["robot_run_id"] = "different-physical-run"
    elif corruption == "replay":
        current["resolution"]["replay_authorized"] = True
    elif corruption == "historical":
        current["status"] = "completed"
    elif corruption == "quiescence":
        request["released"] = False
    elif corruption == "revision":
        request["expected_version"] = 1
    elif corruption == "future":
        current["resolution"]["resolved_at"] = datetime.now(UTC).timestamp() + 3600
    elif corruption == "extra":
        current["resolution"]["local_override"] = True
    # Deep-copy the original because response mutations must not edit persisted evidence.
    original = command_for(profile, creds)
    original.update({key: command[key] for key in ("run_id", "connection_id", "expires_at")})
    row = {
        "command": Command.model_validate(original).model_dump_json(),
        "protocol_id": "protocol-1",
        "robot_run_id": "robot-run-1",
    }
    with pytest.raises(ValueError):
        validate_resolution(row, current, creds)


def test_idle_refresh_probes_again_before_server_ttl(monkeypatch):
    from types import SimpleNamespace

    import academy.companion.client as module

    times, events = [0.0], []

    def tick(seconds):
        times[0] += 60
        if times[0] > 300:
            raise StopIteration

    engine = SimpleNamespace(probe=lambda: events.append(("robot-probe", times[0])))
    client = SimpleNamespace(probe=lambda profile: events.append(("cloud-probe", times[0])))
    monkeypatch.setattr(
        module, "run_once", lambda *args, **kwargs: events.append(("claim", times[0]))
    )
    with pytest.raises(StopIteration):
        module.run_supervised(
            client, engine, None, None, approve=None, clock=lambda: times[0], sleep=tick
        )
    assert [when for kind, when in events if kind == "robot-probe"] == [0, 120, 240]
    assert [when for kind, when in events if kind == "cloud-probe"] == [0, 120, 240]
    for time_value in (0, 120, 240):
        assert (
            events.index(("robot-probe", time_value))
            < events.index(("cloud-probe", time_value))
            < events.index(("claim", time_value))
        )


def test_packaged_cli_redacts_exception_secrets(monkeypatch, capsys):
    import academy.companion.__main__ as entry

    def fail(_argv):
        raise RuntimeError("Authorization: Bearer private-test-secret")

    monkeypatch.setattr(entry, "main", fail)
    assert entry.cli([]) == 1
    output = capsys.readouterr()
    assert "RuntimeError" in output.err
    assert "private-test-secret" not in output.err


def test_revoked_machine_cannot_accept_resolution(tmp_path):
    from academy.companion.client import Command, reconcile_resolutions

    creds, profile = credentials(), profile_for()
    command = Command.model_validate(command_for(profile, creds)).model_dump(mode="json")
    with Journal(private_directory(tmp_path / "state")) as journal:
        journal.begin(command)
        journal.phase(
            command["run_id"],
            "play_attempted",
            protocol_id="protocol-1",
            robot_run_id="robot-run-1",
        )
        recover(journal)
        journal.acknowledged(command["run_id"])
        client = AcademyClient(
            config(profile, "http://127.0.0.1:31950"),
            creds,
            transport=httpx.MockTransport(
                lambda req: httpx.Response(403, json={"detail": "revoked"})
            ),
        )
        with pytest.raises(httpx.HTTPStatusError):
            reconcile_resolutions(client, journal)
        assert journal.unresolved()
        assert list(journal.db.execute("SELECT * FROM resolutions")) == []
        client.close()
