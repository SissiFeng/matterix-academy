"""Software-only installer acceptance: local Git fixtures and intercepted transports.

These tests never invoke SSH, execute upstream hooks, or connect to an instrument.
They do not qualify the upstream recipe, a release, or physical service ownership.
"""

import builtins
import contextlib
import hashlib
import io
import json
import os
import shlex
import sqlite3
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from academy.companion import __main__ as companion_entry
from academy.companion import config
from academy.companion import installer as subject
from academy.companion.config import canonical, read_private
from test_connector_protocol import profile_for


def sha(data):
    return hashlib.sha256(data).hexdigest()


class FixtureInstallation:
    """Only local Git is executed. All robot/process activity is a recorded fixture."""

    def __init__(self, root, monkeypatch):
        self.root = root
        self.repo = root / "source-repository"
        self.repo.mkdir()
        self.profile = profile_for()
        self.files = {
            name: b"# Software fixture; never execute this hook.\n"
            for name in subject.REVIEWED_FILES
        }
        self.files["scripts/artifact_manifest.py"] = b'print("SOFTWARE-FIXTURE-MANIFEST")\n'
        self.files["config/flex_config.json"] = canonical(
            {
                "sila_server": {
                    "uuid": str(self.profile.sila_server_uuid),
                    "port": self.profile.sila_port,
                    "tls": self.profile.sila_tls,
                },
                "use_simulator": False,
                "with_robot_server": True,
            }
        )
        for name, content in self.files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.git("init", "-q")
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=Software Fixture",
            "-c",
            "user.email=fixture@invalid.example",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "Software-only installer fixture",
        )
        self.commit = self.git("rev-parse", "HEAD").decode().strip()
        monkeypatch.setattr(subject, "SOURCE_COMMIT", self.commit)
        monkeypatch.setattr(subject, "REVIEWED_FILES", {k: sha(v) for k, v in self.files.items()})
        self.archive = root / "actions-runtime.zip"
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("unitelabs-opentrons-flex", b"inert software fixture runtime\n")
            archive.writestr("manifest.json", b'{"fixture":true}')
            archive.writestr(
                "runtime-manifest.json", canonical({"releaseId": self.profile.runtime_release_id})
            )
        self.recipe = subject.InstallerRecipe(
            schema_version="academy.flex-installer/1",
            source_commit=self.commit,
            artifact_sha256=sha(self.archive.read_bytes()),
            files=subject.REVIEWED_FILES,
            qualification_report_sha256="e" * 64,
            no_motion_startup_verified=True,
            service_switch_verified=True,
            rollback_verified=True,
        )
        self.profile = self.profile.model_copy(
            update={"source_commit": self.commit, "artifact_sha256": self.recipe.artifact_sha256}
        )
        config_hash = sha(b"".join(self.files[name] for name in subject.CONFIG_FILES))
        self.target_release = (
            "/var/lib/unitelabs-opentrons-flex/releases/"
            + self.profile.runtime_release_id
            + "-cfg"
            + config_hash[:12]
        )
        for name in ("known_hosts", "identity"):
            path = root / name
            path.write_text("SOFTWARE-FIXTURE-NOT-A-REAL-KEY\n")
            path.chmod(0o600)
        self.request = subject.InstallerRequest(
            operation_id=uuid4(),
            installation_id=uuid4(),
            instrument="flex",
            platform="macos",
            ssh_host="192.168.50.2",
            known_hosts=str(root / "known_hosts"),
            identity_file=str(root / "identity"),
            robot_url="http://192.168.50.2:31950",
            profile=self.profile,
        )
        self.release = {
            "status": "approved",
            "instrument": "flex",
            "platform": "macos",
            "execution_transport": "opentrons-protocol-engine",
            "supported_firmware": [self.profile.firmware],
            "installer_recipe_sha256": self.recipe.sha256,
            **{
                key: getattr(self.profile, key)
                for key in (
                    "source_commit",
                    "release_id",
                    "artifact_sha256",
                    "runtime_contract_id",
                    "runtime_release_id",
                    "runtime_bundle_sha256",
                )
            },
        }
        self.calls = []
        self.observations = []
        self.approvals = []
        self.mutations = []
        self.fail_phase = None
        self.transform_snapshot = None
        self.change_report = lambda report, mode: report
        self.credential_exists = True
        self.credential_valid = True
        self.service_mode = "stock"
        self.active_release = "/var/lib/unitelabs-opentrons-flex/releases/previous-software-fixture"
        self.previous_release = (
            "release:/var/lib/unitelabs-opentrons-flex/releases/older-software-fixture"
        )
        self.installation = subject.Installer(
            root / "state",
            runner=self.runner,
            observer=self.observe,
            catalog=lambda instrument, platform: self.release,
        )

    def git(self, *arguments):
        return subprocess.run(
            ["/usr/bin/git", "-C", str(self.repo), *arguments],
            check=True,
            capture_output=True,
            env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"},
        ).stdout

    def runner(self, argv, *, input=b"", cwd=None, env=None, timeout=900):
        argv = list(argv)
        self.calls.append({"argv": argv, "input": input, "cwd": cwd, "env": env})
        if argv[0] == "/usr/bin/git":
            assert argv[1:3] == ["-C", str(self.repo)]
            result = self.git(*argv[3:])
            return self.transform_snapshot(result) if self.transform_snapshot else result
        # A separate SQLite reader proves the phase was durably committed before actuation.
        with sqlite3.connect(self.root / "state/installer.sqlite3") as database:
            pending = database.execute(
                "SELECT id,phase FROM installs WHERE receipt IS NULL"
            ).fetchall()
        if argv[0] == "/usr/bin/ssh":
            assert shlex.split(argv[-1]) == ["python3", "-c", subject.CREATE_CREDENTIAL]
            phase = "credential-create-attempted"
            credential = json.loads(input)
            assert set(credential) == {"actor", "secret"}
            assert credential["secret"] not in " ".join(argv)
            assert credential["secret"] not in json.dumps(env or {})
            self.credential_exists = self.credential_valid = True
        else:
            assert argv[0] == "/bin/sh", "No real unrecognized subprocess may execute"
            phase = {
                "deploy.sh": "deploy-attempted",
                "install_connector_service.sh": "service-switch-attempted",
                "rollback_connector.sh": "rollback-attempted",
                "switch_mode.sh": "stock-switch-attempted",
            }[Path(argv[1]).name]
            assert argv[2] == self.request.ssh_host
            assert str(cwd).startswith(str(self.root / "state"))
            assert set(env) == {"PATH", "HOME", "LC_ALL"}
            if phase == "deploy-attempted":
                self.previous_release = (
                    "release:" + self.active_release if self.active_release else None
                )
                self.active_release = self.target_release
            if phase == "service-switch-attempted":
                self.service_mode = "connector"
            if phase == "rollback-attempted":
                self.service_mode = "stock"
                self.active_release, self.previous_release = (
                    self.previous_release.split(":", 1)[1],
                    "release:" + self.active_release,
                )
            if phase == "stock-switch-attempted":
                assert argv[3] == "opentrons"
                self.service_mode = "stock"
        assert any(saved_phase == phase for _, saved_phase in pending)
        self.mutations.append(phase)
        if phase == self.fail_phase:
            raise subprocess.TimeoutExpired(argv, timeout, output=b"REMOTE SECRET NOT FOR LOGS")
        return b'{"created":true}' if phase == "credential-create-attempted" else b""

    def observe(self, request, mode):
        self.observations.append(mode)
        report = {
            "health": {
                "robot_serial": request.profile.serial,
                "robot_model": "OT-3 Standard",
                "fw_version": request.profile.firmware,
            },
            "idle": True,
            "services": {
                "sila2-connector": self.service_mode == "connector",
                **{name: self.service_mode == "stock" for name in subject.SERVICES},
            },
            "credential_exists": self.credential_exists,
            "credential_valid": self.credential_valid,
            "operation_lock_exists": False,
            "active_release_kind": "versioned" if self.active_release else "missing",
            "active_release": self.active_release,
            "previous_release": self.previous_release,
            "previous_release_exists": self.previous_release is not None,
        }
        return self.change_report(report, mode)

    def approve(self, summary):
        self.approvals.append(summary)
        return True

    def install(self, **kwargs):
        return self.installation.install(
            kwargs.pop("request", self.request),
            kwargs.pop("recipe", self.recipe),
            self.repo,
            self.archive,
            approve=kwargs.pop("approve", self.approve),
            **kwargs,
        )

    def unknown_recovery(self):
        self.fail_phase = "deploy-attempted"
        with pytest.raises(RuntimeError, match="unknown"):
            self.install()
        self.fail_phase = "rollback-attempted"
        recovery_id = uuid4()
        with pytest.raises(RuntimeError, match="unknown"):
            self.installation.rollback(self.request.operation_id, recovery_id, approve=self.approve)
        self.fail_phase = None
        return recovery_id


@pytest.fixture
def installation(tmp_path, monkeypatch):
    fixture = FixtureInstallation(tmp_path, monkeypatch)
    try:
        yield fixture
    finally:
        fixture.installation.close()


def test_approved_zip_installs_only_reviewed_committed_hooks_with_durable_phases(installation):
    fixture = installation
    # Dirty worktree contents are not the immutable reviewed Git object.
    (fixture.repo / "deploy.sh").write_text("UNREVIEWED DIRTY CONTENT\n")
    result = fixture.install()
    assert result["status"] == "completed"
    assert result["physical_workflow_executed"] is False
    assert fixture.mutations == ["deploy-attempted", "service-switch-attempted"]
    assert fixture.observations[0] == "stock"
    assert fixture.observations[-1] == "connector"
    assert set(fixture.observations) == {"stock", "connector"}
    assert fixture.approvals[0]["serial"] == fixture.profile.serial
    assert fixture.approvals[0]["recipe_sha256"] == fixture.recipe.sha256
    directory = fixture.root / "state" / str(fixture.request.operation_id)
    assert (directory / "source/deploy.sh").read_bytes() == fixture.files["deploy.sh"]
    assert (
        (directory / "source/dist_arm/unitelabs-opentrons-flex").read_bytes().startswith(b"inert")
    )
    assert (directory / "identity").stat().st_mode & 0o777 == 0o600
    assert (fixture.root / "state").stat().st_mode & 0o777 == 0o700
    count = len(fixture.calls)
    assert fixture.install() == result
    assert len(fixture.calls) == count


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "candidate"),
        ("installer_recipe_sha256", "0" * 64),
        ("source_commit", "0" * 40),
        ("artifact_sha256", "0" * 64),
        ("release_id", "another-release"),
        ("runtime_contract_id", "another-contract"),
        ("runtime_release_id", "another-runtime"),
        ("runtime_bundle_sha256", "0" * 64),
        ("supported_firmware", ["unsupported-firmware"]),
        ("instrument", "ot2"),
        ("platform", "linux"),
        ("execution_transport", "arbitrary-shell"),
    ],
)
def test_catalog_and_exact_recipe_are_required_before_preparation(installation, field, value):
    installation.release[field] = value
    with pytest.raises(ValueError, match="catalog-approved"):
        installation.install()
    assert installation.calls == installation.observations == installation.mutations == []


def test_absent_approved_release_cannot_install(installation):
    installation.release = None
    with pytest.raises(ValueError, match="catalog-approved"):
        installation.install()
    assert installation.calls == []


@pytest.mark.parametrize("field,value", [("source_commit", "0" * 40), ("files", {})])
def test_recipe_cannot_select_arbitrary_hooks(installation, field, value):
    data = installation.recipe.model_dump(mode="json")
    data[field] = value
    with pytest.raises(ValueError, match="reviewed source recipe"):
        subject.InstallerRecipe.model_validate(data)


@pytest.mark.parametrize(
    "changes",
    [
        {"ssh_host": "8.8.8.8", "robot_url": "http://8.8.8.8:31950"},
        {"ssh_host": "127.0.0.1", "robot_url": "http://127.0.0.1:31950"},
        {"ssh_host": "169.254.1.2", "robot_url": "http://169.254.1.2:31950"},
        {"ssh_host": "robot.local"},
        {"ssh_host": "192.168.50.2;echo unsafe"},
        {"robot_url": "http://192.168.50.3:31950"},
        {"robot_url": "http://192.168.50.2:22"},
        {"robot_url": "http://user:secret@192.168.50.2:31950"},
        {"instrument": "ot2"},
    ],
)
def test_install_target_is_explicit_local_matching_flex_only(installation, changes):
    data = installation.request.model_dump(mode="json") | changes
    with pytest.raises(ValueError):
        subject.InstallerRequest.model_validate(data)
    assert installation.calls == []


def test_wrong_artifact_digest_fails_before_device_observation(installation):
    installation.archive.write_bytes(b"changed download")
    with pytest.raises(ValueError, match="SHA256"):
        installation.install()
    assert installation.mutations == installation.observations == []


@pytest.mark.parametrize("corruption", ["digest", "unexpected", "symlink", "duplicate"])
def test_source_snapshot_is_bounded_by_exact_committed_files(installation, corruption):
    def corrupt(data):
        output = io.BytesIO()
        with (
            tarfile.open(fileobj=io.BytesIO(data)) as source,
            tarfile.open(fileobj=output, mode="w") as target,
        ):
            for member in source:
                content = source.extractfile(member).read() if member.isfile() else None
                if member.name == "deploy.sh":
                    if corruption == "digest":
                        content = b"unreviewed"
                        member.size = len(content)
                    if corruption == "symlink":
                        member.type, member.linkname, member.size = (
                            tarfile.SYMTYPE,
                            "/tmp/escape",
                            0,
                        )
                        content = None
                    if corruption == "duplicate":
                        target.addfile(member, io.BytesIO(content))
                target.addfile(member, io.BytesIO(content) if content is not None else None)
            if corruption == "unexpected":
                member = tarfile.TarInfo("unreviewed.sh")
                target.addfile(member, io.BytesIO(b""))
        return output.getvalue()

    installation.transform_snapshot = corrupt
    with pytest.raises(ValueError, match="checksum|unreviewed"):
        installation.install()
    assert installation.mutations == installation.observations == []


@pytest.mark.parametrize("name,mode", [("identity", 0o644), ("known_hosts", 0o666)])
def test_unprotected_local_credentials_are_refused(installation, name, mode):
    (installation.root / name).chmod(mode)
    with pytest.raises(ValueError):
        installation.install()
    assert installation.mutations == installation.observations == []


def test_symlinked_private_identity_is_refused(installation):
    source = installation.root / "identity"
    source.rename(installation.root / "actual-key")
    source.symlink_to(installation.root / "actual-key")
    with pytest.raises((ValueError, OSError)):
        installation.install()
    assert installation.mutations == []


@pytest.mark.parametrize(
    "change", ["serial", "model", "firmware", "busy", "ownership", "credential"]
)
def test_read_only_preflight_denies_wrong_identity_busy_robot_and_bad_credentials(
    installation, change
):
    def alter(report, mode):
        if change in {"serial", "model", "firmware"}:
            key = {"serial": "robot_serial", "model": "robot_model", "firmware": "fw_version"}[
                change
            ]
            report["health"][key] = "WRONG"
        elif change == "busy":
            report["idle"] = False
        elif change == "ownership":
            report["services"]["sila2-connector"] = True
        else:
            report["credential_valid"] = False
        return report

    installation.change_report = alter
    with pytest.raises(ValueError):
        installation.install()
    assert installation.observations == ["stock"]
    assert installation.mutations == installation.approvals == []


def test_local_decline_never_bootstraps_or_switches_services(installation):
    installation.credential_exists = installation.credential_valid = False
    result = installation.install(approve=lambda summary: False)
    assert result["status"] == "declined"
    assert result["mutation_attempted"] is False
    assert installation.mutations == []
    assert installation.installation.journal.get(installation.request.operation_id) is None


def test_bootstrap_secret_uses_only_private_file_and_ssh_stdin(installation):
    installation.credential_exists = installation.credential_valid = False
    result = installation.install()
    assert result["status"] == "completed"
    assert installation.mutations == [
        "credential-create-attempted",
        "deploy-attempted",
        "service-switch-attempted",
    ]
    path = (
        installation.root
        / "state"
        / str(installation.request.operation_id)
        / "mutation-credential.json"
    )
    credential = json.loads(read_private(path))
    assert len(credential["secret"]) >= 43
    assert credential["actor"] == "academy-" + str(installation.request.installation_id)
    assert path.stat().st_mode & 0o777 == 0o600
    assert credential["secret"] not in json.dumps(result)
    assert credential["secret"] not in json.dumps(installation.approvals)
    assert (
        credential["secret"]
        not in installation.installation.journal.get(installation.request.operation_id)["request"]
    )
    ssh = next(call for call in installation.calls if call["argv"][0] == "/usr/bin/ssh")
    assert json.loads(ssh["input"]) == credential


@pytest.mark.parametrize(
    "phase", ["credential-create-attempted", "deploy-attempted", "service-switch-attempted"]
)
def test_lost_mutation_response_is_unknown_and_same_operation_never_retries(installation, phase):
    installation.credential_exists = installation.credential_valid = (
        phase != "credential-create-attempted"
    )
    installation.fail_phase = phase
    with pytest.raises(RuntimeError, match="unknown") as failure:
        installation.install()
    assert "REMOTE SECRET" not in str(failure.value)
    original = installation.installation.journal.get(installation.request.operation_id)
    receipt = json.loads(original["receipt"])
    assert receipt["status"] == "unknown"
    assert receipt["automatic_replay_allowed"] is False
    calls = len(installation.calls)
    assert installation.install() == receipt
    assert len(installation.calls) == calls
    assert installation.mutations.count(phase) == 1


def test_unknown_install_receipt_survives_restart_without_replay(installation):
    installation.fail_phase = "deploy-attempted"
    with pytest.raises(RuntimeError, match="unknown"):
        installation.install()
    original = installation.installation.journal.get(installation.request.operation_id)
    installation.installation.close()
    installation.installation = subject.Installer(
        installation.root / "state",
        runner=installation.runner,
        observer=installation.observe,
        catalog=lambda instrument, platform: installation.release,
    )
    count = len(installation.calls)
    assert installation.install() == json.loads(original["receipt"])
    assert len(installation.calls) == count


def test_unknown_install_blocks_new_mutation_until_explicit_rollback(installation):
    installation.fail_phase = "deploy-attempted"
    with pytest.raises(RuntimeError, match="unknown"):
        installation.install()
    original = installation.installation.journal.get(installation.request.operation_id)
    installation.fail_phase = None
    next_request = installation.request.model_copy(update={"operation_id": uuid4()})
    with pytest.raises(RuntimeError, match="Unresolved"):
        installation.install(request=next_request)
    assert installation.mutations == ["deploy-attempted"]
    rollback_id = uuid4()
    result = installation.installation.rollback(
        installation.request.operation_id, rollback_id, approve=installation.approve
    )
    assert result["status"] == "completed"
    assert result["replay_authorized"] is False
    current = installation.installation.journal.get(installation.request.operation_id)
    assert current["receipt"] == original["receipt"]
    assert json.loads(current["resolution"]) == result
    count = len(installation.calls)
    assert (
        installation.installation.rollback(
            installation.request.operation_id, rollback_id, approve=installation.approve
        )
        == result
    )
    assert len(installation.calls) == count
    assert installation.install() == json.loads(original["receipt"])
    fresh = installation.request.model_copy(update={"operation_id": uuid4()})
    assert installation.install(request=fresh)["status"] == "completed"
    assert installation.mutations == [
        "deploy-attempted",
        "rollback-attempted",
        "deploy-attempted",
        "service-switch-attempted",
    ]


@pytest.mark.parametrize(
    "failure_phase,expected_recovery",
    [
        ("credential-create-attempted", "stock-reconciled"),
        ("deploy-attempted", "stock-reconciled"),
        ("service-switch-attempted", "stock-services-restored"),
    ],
)
def test_first_host_unknown_can_be_explicitly_recovered_without_a_previous_release(
    installation, failure_phase, expected_recovery
):
    installation.active_release = installation.previous_release = None
    installation.credential_exists = installation.credential_valid = False
    installation.fail_phase = failure_phase
    with pytest.raises(RuntimeError, match="unknown"):
        installation.install()
    original = installation.installation.journal.get(installation.request.operation_id)
    before = list(installation.mutations)
    installation.fail_phase = None
    result = installation.installation.rollback(
        installation.request.operation_id, uuid4(), approve=installation.approve
    )
    assert result["status"] == "completed"
    assert result["recovery_action"] == expected_recovery
    assert result["replay_authorized"] is False
    assert (
        installation.installation.journal.get(installation.request.operation_id)["receipt"]
        == original["receipt"]
    )
    assert installation.mutations == before + (
        ["stock-switch-attempted"] if expected_recovery == "stock-services-restored" else []
    )
    assert "rollback-attempted" not in installation.mutations
    assert installation.install() == json.loads(original["receipt"])


def test_rollback_requires_separate_local_approval(installation):
    installation.install()
    count = len(installation.calls)
    result = installation.installation.rollback(
        installation.request.operation_id, uuid4(), approve=lambda summary: False
    )
    assert result == {"status": "declined", "mutation_attempted": False}
    assert len(installation.calls) == count


@pytest.mark.parametrize("change", ["serial", "model", "firmware", "busy", "missing-release"])
def test_rollback_revalidates_identity_and_idle_before_mutation(installation, change):
    installation.install()

    def alter(report, mode):
        if mode == "rollback-preflight":
            if change in {"serial", "model", "firmware"}:
                key = {"serial": "robot_serial", "model": "robot_model", "firmware": "fw_version"}[
                    change
                ]
                report["health"][key] = "WRONG"
            else:
                report["idle" if change == "busy" else "previous_release_exists"] = False
        return report

    installation.change_report = alter
    with pytest.raises((ValueError, RuntimeError)):
        installation.installation.rollback(
            installation.request.operation_id, uuid4(), approve=installation.approve
        )
    assert "rollback-attempted" not in installation.mutations


def test_rollback_lost_output_cannot_be_automatically_replayed(installation):
    installation.install()
    installation.fail_phase = "rollback-attempted"
    operation_id = uuid4()
    with pytest.raises(RuntimeError, match="unknown"):
        installation.installation.rollback(
            installation.request.operation_id, operation_id, approve=installation.approve
        )
    count = len(installation.calls)
    result = installation.installation.rollback(
        installation.request.operation_id, operation_id, approve=installation.approve
    )
    assert result["status"] == "unknown"
    assert result["automatic_replay_allowed"] is False
    assert len(installation.calls) == count
    assert (
        installation.installation.journal.get(installation.request.operation_id)["resolution"]
        is None
    )


def test_recovery_receipt_and_original_resolution_commit_atomically(installation):
    journal = installation.installation.journal
    original, recovery = uuid4(), uuid4()
    journal.begin(original, {"software_fixture": "original"})
    journal.finish(original, {"status": "unknown", "automatic_replay_allowed": False})
    journal.begin(recovery, {"rollback_of": str(original)}, rollback_of=str(original))
    receipt = {"status": "completed", "operation_id": str(recovery), "rollback_of": str(original)}
    # This crash fixture aborts the original-resolution write inside the transaction.
    journal.db.execute(
        "CREATE TRIGGER interrupt_resolution BEFORE UPDATE OF resolution ON installs "
        "WHEN NEW.resolution IS NOT NULL BEGIN SELECT RAISE(ABORT,'software crash fixture'); END"
    )
    with pytest.raises(sqlite3.IntegrityError, match="software crash fixture"):
        journal.resolve(recovery, original, receipt)
    assert journal.get(recovery)["receipt"] is None
    assert journal.get(original)["resolution"] is None
    assert json.loads(journal.get(original)["receipt"])["status"] == "unknown"
    journal.db.execute("DROP TRIGGER interrupt_resolution")
    journal.resolve(recovery, original, receipt)
    assert json.loads(journal.get(recovery)["receipt"]) == receipt
    assert json.loads(journal.get(original)["resolution"]) == receipt
    assert json.loads(journal.get(original)["receipt"])["status"] == "unknown"


def test_lost_rollback_can_be_read_only_reconciled_without_replay_and_unblock_new_install(
    installation,
):
    recovery_id = installation.unknown_recovery()
    journal = installation.installation.journal
    original = journal.get(installation.request.operation_id)
    recovery = journal.get(recovery_id)
    count = len(installation.calls)
    resolution_id = uuid4()
    receipt = installation.installation.reconcile(
        installation.request.operation_id, recovery_id, resolution_id, approve=installation.approve
    )
    assert receipt["status"] == "completed"
    assert receipt["recovery_action"] == "read-only-stock-reconciliation"
    assert receipt["mutation_attempted"] is False
    assert receipt["replay_authorized"] is False
    assert len(installation.calls) == count
    assert journal.get(installation.request.operation_id)["receipt"] == original["receipt"]
    assert journal.get(recovery_id)["receipt"] == recovery["receipt"]
    assert json.loads(journal.get(recovery_id)["resolution"]) == receipt
    assert json.loads(journal.get(installation.request.operation_id)["resolution"]) == receipt
    assert (
        installation.installation.reconcile(
            installation.request.operation_id,
            recovery_id,
            resolution_id,
            approve=installation.approve,
        )
        == receipt
    )
    assert len(installation.calls) == count
    fresh = installation.request.model_copy(update={"operation_id": uuid4()})
    assert installation.install(request=fresh)["status"] == "completed"
    assert installation.mutations == [
        "deploy-attempted",
        "rollback-attempted",
        "deploy-attempted",
        "service-switch-attempted",
    ]


def test_reconciliation_resolves_both_unknown_histories_in_one_transaction(installation):
    recovery_id = installation.unknown_recovery()
    journal = installation.installation.journal
    original_id, resolution_id = installation.request.operation_id, uuid4()
    journal.begin(
        resolution_id,
        {"software_fixture": "read-only-resolution"},
        resolving_ids=(original_id, recovery_id),
    )
    receipt = {"status": "completed", "operation_id": str(resolution_id)}
    # Abort the last related-record write, after the resolution and original updates.
    journal.db.execute(
        "CREATE TRIGGER interrupt_related BEFORE UPDATE OF resolution ON installs "
        f"WHEN NEW.id='{recovery_id}' AND NEW.resolution IS NOT NULL "
        "BEGIN SELECT RAISE(ABORT,'software crash fixture'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        journal.resolve(resolution_id, original_id, receipt, related_id=recovery_id)
    assert journal.get(resolution_id)["receipt"] is None
    assert journal.get(original_id)["resolution"] is None
    assert journal.get(recovery_id)["resolution"] is None
    journal.db.execute("DROP TRIGGER interrupt_related")
    journal.resolve(resolution_id, original_id, receipt, related_id=recovery_id)
    assert json.loads(journal.get(original_id)["resolution"]) == receipt
    assert json.loads(journal.get(recovery_id)["resolution"]) == receipt
    assert json.loads(journal.get(original_id)["receipt"])["status"] == "unknown"
    assert json.loads(journal.get(recovery_id)["receipt"])["status"] == "unknown"


@pytest.mark.parametrize("change", ["serial", "firmware", "busy", "pointer", "ownership"])
def test_read_only_reconciliation_cannot_clear_mismatched_or_busy_state(installation, change):
    recovery_id = installation.unknown_recovery()

    def alter(report, mode):
        if change in {"serial", "firmware"}:
            report["health"]["robot_serial" if change == "serial" else "fw_version"] = "WRONG"
        elif change == "busy":
            report["idle"] = False
        elif change == "pointer":
            report["active_release"] = "/var/lib/unitelabs-opentrons-flex/releases/unrelated"
        else:
            report["services"]["sila2-connector"] = True
        return report

    installation.change_report = alter
    count = len(installation.calls)
    with pytest.raises(ValueError):
        installation.installation.reconcile(
            installation.request.operation_id, recovery_id, uuid4(), approve=installation.approve
        )
    assert len(installation.calls) == count
    assert (
        installation.installation.journal.get(installation.request.operation_id)["resolution"]
        is None
    )
    assert installation.installation.journal.get(recovery_id)["resolution"] is None


def test_read_only_reconciliation_checks_fresh_state_after_approval(installation):
    recovery_id = installation.unknown_recovery()

    def approve(summary):
        installation.change_report = lambda report, mode: report | {"idle": False}
        return True

    with pytest.raises(ValueError):
        installation.installation.reconcile(
            installation.request.operation_id, recovery_id, uuid4(), approve=approve
        )
    assert installation.installation.journal.get(recovery_id)["resolution"] is None


def test_prepared_read_only_reconciliation_can_finish_after_local_process_loss(
    installation, monkeypatch
):
    recovery_id = installation.unknown_recovery()
    resolution_id = uuid4()
    journal = installation.installation.journal
    actual_resolve = journal.resolve
    interrupted = False

    def interrupt_once(*args, **kwargs):
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise RuntimeError("software fixture process loss before read-only resolution commit")
        return actual_resolve(*args, **kwargs)

    monkeypatch.setattr(journal, "resolve", interrupt_once)
    calls = len(installation.calls)
    with pytest.raises(RuntimeError, match="process loss"):
        installation.installation.reconcile(
            installation.request.operation_id,
            recovery_id,
            resolution_id,
            approve=installation.approve,
        )
    assert journal.get(resolution_id)["receipt"] is None
    observations = len(installation.observations)
    result = installation.installation.reconcile(
        installation.request.operation_id, recovery_id, resolution_id, approve=installation.approve
    )
    assert result["status"] == "completed"
    assert len(installation.observations) > observations
    assert len(installation.calls) == calls
    assert json.loads(journal.get(resolution_id)["receipt"]) == result


def test_read_only_reconciliation_rejects_recovery_bound_to_another_installation(installation):
    recovery_id = installation.unknown_recovery()
    journal = installation.installation.journal
    original = journal.get(installation.request.operation_id)
    with journal.db:
        journal.db.execute(
            "UPDATE installs SET request=? WHERE id=?",
            (
                canonical(
                    {"rollback_of": str(uuid4()), "original_request_sha256": "0" * 64}
                ).decode(),
                str(recovery_id),
            ),
        )
    before = len(installation.observations)
    with pytest.raises(ValueError, match="this installation"):
        installation.installation.reconcile(
            installation.request.operation_id, recovery_id, uuid4(), approve=installation.approve
        )
    assert len(installation.observations) == before
    assert journal.get(installation.request.operation_id) == original


def test_expired_motion_qualification_blocks_install_but_not_verified_recovery(
    installation, monkeypatch
):
    installation.install()
    monkeypatch.setattr(
        config,
        "datetime",
        SimpleNamespace(now=lambda timezone: installation.profile.qualified_until),
    )
    with pytest.raises(ValueError, match="expired"):
        installation.install(
            request=installation.request.model_copy(update={"operation_id": uuid4()})
        )
    result = installation.installation.rollback(
        installation.request.operation_id, uuid4(), approve=installation.approve
    )
    assert result["status"] == "completed"
    assert installation.mutations.count("rollback-attempted") == 1


def test_journal_blocks_concurrent_installer_process_and_receipt_rewrite(installation):
    with pytest.raises(BlockingIOError):
        subject.InstallJournal(installation.root / "state")
    result = installation.install()
    with pytest.raises(ValueError, match="immutable"):
        installation.installation.journal.finish(
            installation.request.operation_id, result | {"status": "unknown"}
        )


@pytest.mark.parametrize("when", ["approval", "deploy"])
def test_becoming_busy_during_install_cannot_switch_hardware_ownership(installation, when):
    def alter(report, mode):
        if when == "approval" and installation.approvals:
            report["idle"] = False
        if when == "deploy" and "deploy-attempted" in installation.mutations:
            report["idle"] = False
        return report

    installation.change_report = alter
    with pytest.raises((ValueError, RuntimeError)):
        installation.install()
    assert "service-switch-attempted" not in installation.mutations
    if when == "approval":
        assert installation.mutations == []


@pytest.mark.parametrize(
    "relative",
    [
        "identity",
        "known_hosts",
        "ssh-policy.json",
        "bin/ssh",
        "bin/python3",
        "source/deploy.sh",
        "source/dist_arm/runtime-manifest.json",
        "source/config/flex_config.local.json",
    ],
)
def test_changed_local_trust_recipe_or_artifact_during_approval_never_mutates_robot(
    installation, relative
):
    def approve(summary):
        path = installation.root / "state" / str(installation.request.operation_id) / relative
        path.write_bytes(b"UNREVIEWED CHANGE")
        return True

    with pytest.raises(RuntimeError, match="unknown"):
        installation.install(approve=approve)
    assert installation.mutations == []


def test_rollback_rechecks_idle_after_local_approval(installation):
    installation.install()

    def approve(summary):
        installation.change_report = lambda report, mode: report | {"idle": False}
        return True

    with pytest.raises(RuntimeError, match="unknown"):
        installation.installation.rollback(
            installation.request.operation_id, uuid4(), approve=approve
        )
    assert "rollback-attempted" not in installation.mutations


def test_a_new_rollback_id_cannot_toggle_an_already_resolved_installation(installation):
    installation.install()
    installation.installation.rollback(
        installation.request.operation_id, uuid4(), approve=installation.approve
    )
    before = list(installation.mutations)
    with pytest.raises((ValueError, RuntimeError)):
        installation.installation.rollback(
            installation.request.operation_id, uuid4(), approve=installation.approve
        )
    assert installation.mutations == before


@pytest.mark.parametrize("pointer", ["active_release", "previous_release"])
def test_rollback_cannot_use_release_pointers_changed_by_another_operation(installation, pointer):
    installation.install()
    setattr(
        installation,
        pointer,
        "release:/unrelated" if pointer == "previous_release" else "/unrelated",
    )
    with pytest.raises((ValueError, RuntimeError)):
        installation.installation.rollback(
            installation.request.operation_id, uuid4(), approve=installation.approve
        )
    assert "rollback-attempted" not in installation.mutations


def test_frozen_transport_wrappers_dispatch_to_companion_setup(monkeypatch, tmp_path):
    monkeypatch.setattr(subject.sys, "frozen", True, raising=False)
    for kind in ("ssh", "scp", "python3"):
        wrapper = subject.wrapper_source(kind, tmp_path / "policy.json")
        argv = shlex.split(wrapper.splitlines()[1])
        assert argv[:3] == ["exec", subject.sys.executable, "setup"]
        assert "-m" not in argv
        assert ("_python3" if kind == "python3" else "_transport") in argv


def test_frozen_setup_entry_runs_private_verified_python_helpers_without_external_python(
    installation, monkeypatch, capsys
):
    installation.install()
    directory = installation.root / "state" / str(installation.request.operation_id)
    workspace = directory / "source"
    monkeypatch.setattr(subject.sys, "frozen", True, raising=False)
    wrapper = subject.wrapper_source("python3", directory / "ssh-policy.json")
    arguments = shlex.split(wrapper.splitlines()[1])[2:-1]
    assert arguments[0] == "setup"
    companion_entry.main(
        [
            *arguments,
            "-c",
            subject.CONFIG_HASH_CODE,
            *[str(workspace / path) for path in subject.CONFIG_FILES],
        ]
    )
    assert capsys.readouterr().out.strip() == sha(
        b"".join(installation.files[name] for name in subject.CONFIG_FILES)
    )
    companion_entry.main(
        [
            *arguments,
            str(workspace / "scripts/artifact_manifest.py"),
            "verify",
            str(workspace / "dist_arm"),
        ]
    )
    assert capsys.readouterr().out.strip() == "SOFTWARE-FIXTURE-MANIFEST"
    # A policy file that loses its private protection cannot authorize a helper.
    (directory / "ssh-policy.json").chmod(0o644)
    with pytest.raises(ValueError):
        companion_entry.main([*arguments, "-c", subject.CONFIG_HASH_CODE])


@pytest.mark.parametrize("kind", ["ssh", "scp"])
def test_frozen_setup_transport_entry_enforces_private_policy_before_exec(
    installation, monkeypatch, kind
):
    installation.install()
    directory = installation.root / "state" / str(installation.request.operation_id)
    policy_path = directory / "ssh-policy.json"
    policy = json.loads(read_private(policy_path))
    monkeypatch.setattr(subject.sys, "frozen", True, raising=False)
    wrapper = subject.wrapper_source(kind, policy_path)
    arguments = shlex.split(wrapper.splitlines()[1])[2:-1]
    extra = (
        ["root@" + installation.request.ssh_host, "true"]
        if kind == "ssh"
        else [
            str(directory / "source/dist_arm/runtime-manifest.json"),
            "root@"
            + installation.request.ssh_host
            + ":/root/unitelabs-flex-upload-fixture/runtime-manifest.json",
        ]
    )
    observed = []

    class InterceptedExec(Exception):
        pass

    def fake_exec(executable, argv):
        observed.append((executable, argv))
        raise InterceptedExec

    monkeypatch.setattr(subject.os, "execv", fake_exec)
    with pytest.raises(InterceptedExec):
        companion_entry.main([*arguments, *extra])
    expected = subject.ssh_argv(kind, extra, policy)
    assert observed == [(expected[0], expected)]
    with pytest.raises(ValueError):
        companion_entry.main([*arguments, "root@8.8.8.8", "true"])
    assert len(observed) == 1


def test_local_python_helper_only_runs_reviewed_manifest_or_exact_config_hash(
    installation, monkeypatch, capsys
):
    installation.install()
    workspace = installation.root / "state" / str(installation.request.operation_id) / "source"
    policy = {"workspace": str(workspace)}
    subject.run_reviewed_python(
        policy,
        ["-c", subject.CONFIG_HASH_CODE, *[str(workspace / name) for name in subject.CONFIG_FILES]],
    )
    assert capsys.readouterr().out.strip() == sha(
        b"".join(installation.files[name] for name in subject.CONFIG_FILES)
    )
    calls = []
    monkeypatch.setattr(
        subject.runpy, "run_path", lambda *args, **kwargs: calls.append((args, kwargs))
    )
    script = workspace / "scripts/artifact_manifest.py"
    subject.run_reviewed_python(policy, [str(script), "verify", str(workspace / "dist_arm")])
    assert calls == [((str(script),), {"run_name": "__main__"})]
    for arguments in (
        ["-c", "print('arbitrary code')"],
        ["-c", subject.CONFIG_HASH_CODE, "/etc/hosts"],
        ["/unreviewed/script.py", "verify", str(workspace / "dist_arm")],
        [str(script), "verify", "/unreviewed/runtime"],
        [str(script), "execute", str(workspace / "dist_arm")],
    ):
        with pytest.raises(ValueError):
            subject.run_reviewed_python(policy, arguments)
    script.write_text("UNREVIEWED SCRIPT\n")
    with pytest.raises(ValueError):
        subject.run_reviewed_python(policy, [str(script), "verify", str(workspace / "dist_arm")])
    assert len(calls) == 1


def read_status_fixture(runs):
    """Execute the actual fixed probe with isolated fake imports, never real I/O."""
    calls, handlers, output = [], [], io.StringIO()

    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            assert timeout == 10
            if request.full_url.endswith("/health"):
                return io.BytesIO(b'{"robot_serial":"SOFTWARE-TEST"}')
            assert request.full_url.startswith("http://127.0.0.1:31950/runs?")
            return io.BytesIO(canonical(runs))

    def build_opener(*values):
        handlers.extend(values)
        return Opener()

    def run(argv, **kwargs):
        assert argv[:3] == ["systemctl", "is-active", "--quiet"]
        return SimpleNamespace(returncode=1)

    fake_os = SimpleNamespace(
        path=SimpleNamespace(
            exists=lambda path: False,
            lexists=lambda path: False,
            isfile=lambda path: False,
            islink=lambda path: False,
            isdir=lambda path: False,
        )
    )
    fake_request = SimpleNamespace(
        HTTPRedirectHandler=urllib.request.HTTPRedirectHandler,
        ProxyHandler=urllib.request.ProxyHandler,
        Request=urllib.request.Request,
        build_opener=build_opener,
    )
    modules = {
        "os": fake_os,
        "subprocess": SimpleNamespace(run=run, DEVNULL=subprocess.DEVNULL),
        "urllib.request": SimpleNamespace(request=fake_request),
    }

    def import_fixture(name, *args, **kwargs):
        return modules[name] if name in modules else builtins.__import__(name, *args, **kwargs)

    scope = {"__builtins__": {**vars(builtins), "__import__": import_fixture}}
    with contextlib.redirect_stdout(output):
        exec(compile(subject.READ_STATUS, "installer-read-only-probe", "exec"), scope)
    return json.loads(output.getvalue()), calls, handlers


def test_actual_read_status_script_uses_only_versioned_local_gets_and_global_current_link():
    report, requests, handlers = read_status_fixture(
        {"data": [], "meta": {"totalLength": 10_000}, "links": {"current": None}}
    )
    assert report["idle"] is True
    assert [request.get_method() for request in requests] == ["GET", "GET"]
    assert all(request.get_header("Opentrons-version") == "3" for request in requests)
    assert all(request.full_url.startswith("http://127.0.0.1:31950/") for request in requests)
    proxies = [handler for handler in handlers if isinstance(handler, urllib.request.ProxyHandler)]
    assert proxies and all(handler.proxies == {} for handler in proxies)
    redirect = next(
        handler for handler in handlers if isinstance(handler, urllib.request.HTTPRedirectHandler)
    )
    with pytest.raises(ValueError, match="redirect"):
        redirect.redirect_request(None, None, None, None, None, None)


def test_read_status_rejects_missing_current_ownership_and_observes_busy_link_outside_page():
    with pytest.raises(ValueError, match="current-run"):
        read_status_fixture({"data": [], "meta": {"totalLength": 0}})
    report, _, _ = read_status_fixture(
        {"data": [], "links": {"current": {"href": "/runs/not-in-first-page"}}}
    )
    assert report["idle"] is False


def test_ssh_and_scp_transports_pin_key_target_and_trust_without_user_configuration(tmp_path):
    source = tmp_path / "runtime"
    source.write_bytes(b"inert")
    policy = {
        "host": "192.168.50.2",
        "known_hosts": str(tmp_path / "known_hosts"),
        "identity_file": str(tmp_path / "identity"),
        "workspace": str(tmp_path),
    }
    argv = subject.ssh_argv("ssh", ["root@192.168.50.2", "fixed-command"], policy)
    assert argv[:3] == ["/usr/bin/ssh", "-F", "/dev/null"]
    for option in (
        "StrictHostKeyChecking=yes",
        "BatchMode=yes",
        "IdentitiesOnly=yes",
        "IdentityAgent=none",
        "ForwardAgent=no",
        "ClearAllForwardings=yes",
        "ProxyCommand=none",
        "ProxyJump=none",
        "GlobalKnownHostsFile=/dev/null",
    ):
        assert option in argv
    assert argv[argv.index("-i") + 1] == policy["identity_file"]
    argv = subject.ssh_argv(
        "scp",
        ["-O", str(source), "root@192.168.50.2:/root/unitelabs-flex-upload-test/runtime"],
        policy,
    )
    assert argv[0] == "/usr/bin/scp"
    assert "-O" in argv
    for kind, args in (
        ("ssh", ["root@192.168.50.3", "true"]),
        ("ssh", ["-o", "StrictHostKeyChecking=no", "root@192.168.50.2"]),
        ("scp", ["-r", str(source), "root@192.168.50.2:/data/start_connector.sh"]),
        ("scp", [str(source), "root@192.168.50.2:/etc/shadow"]),
        ("scp", ["/etc/hosts", "root@192.168.50.2:/data/start_connector.sh"]),
        ("scp", [str(source), "root@192.168.50.2:/root/unitelabs-flex-upload-test/../escape"]),
        ("scp", [str(source), "root@192.168.50.3:/data/start_connector.sh"]),
    ):
        with pytest.raises(ValueError):
            subject.ssh_argv(kind, args, policy)
