"""Operator workflow tests use synthetic evidence; they do not qualify a host."""

import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from academy import worker_admin
from academy.runs import WORKERS, RunService, SubmitRun, revised, worker_credential
from academy.store import Conflict, Write
from academy.worker_admin import RECONCILIATIONS, REGISTRY, Reconciliation, enroll, reconcile
from fastapi import HTTPException
from pydantic import ValidationError
from test_dispatch import cleanup, saved, start, worker

ACCOUNT = "247893369214"
IDENTITY = {"Account": ACCOUNT, "Arn": f"arn:aws:sts::{ACCOUNT}:assumed-role/operator/fixture"}
NOW = 1790863200.0


def enrollment(store, tmp_path, worker_id="lab-1"):
    return enroll(
        store,
        worker_id,
        "fixture-engine",
        "fixture-assets",
        tmp_path / f"{worker_id}.token",
        clock=lambda: NOW,
    )


@pytest.mark.parametrize("committed", [False, True])
def test_enrollment_recovers_database_failure_with_original_token(
    store, tmp_path, monkeypatch, committed
):
    transact = store.transact

    def interrupted(writes):
        if committed:
            transact(writes)
        raise RuntimeError("Synthetic lost database connection")

    monkeypatch.setattr(store, "transact", interrupted)
    with pytest.raises(RuntimeError):
        enrollment(store, tmp_path)
    path = tmp_path / "lab-1.token"
    token = path.read_text().strip()
    assert path.stat().st_mode & 0o777 == 0o600
    monkeypatch.setattr(store, "transact", transact)
    record = enrollment(store, tmp_path)
    assert path.read_text().strip() == token
    assert record["token_digest"] == hashlib.sha256(token.encode()).hexdigest()
    assert store.get(REGISTRY, "workers")["count"] == 1
    assert enrollment(store, tmp_path) == record
    assert store.get(REGISTRY, "workers")["count"] == 1


def test_enrollment_capacity_is_atomic_under_interleaved_registrations(
    store, tmp_path, monkeypatch
):
    for index in range(99):
        worker(store, f"existing-{index}")
    store.put(REGISTRY, "workers", {"version": 99, "count": 99}, None)
    transact = store.transact

    def competing_enrollment(writes):
        monkeypatch.setattr(store, "transact", transact)
        enrollment(store, tmp_path, "lab-2")
        return transact(writes)

    monkeypatch.setattr(store, "transact", competing_enrollment)
    with pytest.raises(Conflict):
        enrollment(store, tmp_path)
    assert store.get(REGISTRY, "workers")["count"] == 100
    assert len(store.partition(WORKERS, limit=101)) == 100
    assert store.get(WORKERS, "lab-1") is None
    assert store.get(WORKERS, "lab-2") is not None
    with pytest.raises(ValueError, match="registry is full"):
        enrollment(store, tmp_path)


def test_enrollment_rejects_untracked_legacy_registry(store, tmp_path):
    worker(store)
    with pytest.raises(ValueError, match="migration"):
        enrollment(store, tmp_path, "lab-2")
    assert not (tmp_path / "lab-2.token").exists()


def test_enrollment_never_overwrites_existing_or_revoked_identity(store, tmp_path):
    original = enrollment(store, tmp_path)
    path = tmp_path / "lab-1.token"
    token = path.read_text()
    with pytest.raises(ValueError, match="differs"):
        enroll(store, "lab-1", "different", "fixture-assets", path, clock=lambda: NOW)
    store.put(WORKERS, "lab-1", revised(original, revoked=True), original["version"])
    with pytest.raises(ValueError, match="inactive"):
        enrollment(store, tmp_path)
    assert path.read_text() == token
    assert store.get(REGISTRY, "workers")["count"] == 1


def test_enrollment_rejects_exposed_or_symlink_credentials(store, tmp_path):
    path = tmp_path / "lab-1.token"
    path.write_text("lab-1." + "s" * 64)
    path.chmod(0o644)
    with pytest.raises(ValueError, match="protected"):
        enrollment(store, tmp_path)
    assert store.get(WORKERS, "lab-1") is None
    path.unlink()
    other = tmp_path / "source.token"
    other.write_text("lab-1." + "s" * 64)
    other.chmod(0o600)
    path.symlink_to(other)
    with pytest.raises(OSError):
        enrollment(store, tmp_path)
    assert store.get(REGISTRY, "workers") is None


@pytest.fixture
def incident(store):
    clock = [NOW]
    service = RunService(store, enabled=True, clock=lambda: clock[0])
    worker(store)
    session = saved(store)
    request = SubmitRun(run_id=uuid4(), session_id=session["id"], expected_version=1)
    service.submit("alice", request)
    run, _ = start((service, clock, request))
    old = service.worker("lab-1")
    store.put(WORKERS, "lab-1", revised(old, revoked=True, state="quarantined"), old["version"])
    service.reap()
    return service, request, run


def receipt(service, request, **changes):
    run = service.raw(request.run_id)
    old = service.store.get(WORKERS, "lab-1")
    data = dict(
        reconciliation_id=str(uuid4()),
        worker_id="lab-1",
        run_id=str(request.run_id),
        expected_run_version=run["version"],
        expected_worker_version=old["version"],
        native_session_id=(run.get("binding") or {}).get("native_session_id"),
        reset_command_id=str(uuid4()),
        release_command_id=str(uuid4()),
        engine_version="fixture-engine",
        asset_version="fixture-assets",
        evidence="native",
        report_uri="fixture://not-native-acceptance/recovery.json",
        reset_verified=True,
        checks={
            key: True
            for key in (
                "worker_stopped",
                "objects",
                "liquids",
                "tips",
                "controllers",
                "stopped",
                "released",
            )
        },
    )
    data.update(changes)
    return Reconciliation.model_validate(data)


def test_revoked_worker_cannot_cleanup_but_verified_operator_can(incident):
    service, request, run = incident
    with pytest.raises(HTTPException) as error:
        service.cleanup("lab-1", request.run_id, cleanup(run))
    assert error.value.status_code == 403
    data = receipt(service, request)
    reconcile(service.store, data, IDENTITY, ACCOUNT, clock=lambda: NOW)
    result = service.get("alice", request.run_id)
    assert result["status"] == "outcome_unknown"
    assert result["cleanup"]["reset_verified"]
    assert service.store.get("alice", f"session#{request.session_id}")["remote_active_run"] is None
    retired = service.store.get(WORKERS, "lab-1")
    assert retired["revoked"] and not retired["qualified"]
    assert retired["state"] == "quarantined" and retired["active_run"] is None
    assert worker_credential(service.store, "Bearer lab-1." + "s" * 40, NOW) is None
    audit = service.store.get(RECONCILIATIONS, str(data.reconciliation_id))
    assert audit["operator_arn"] == IDENTITY["Arn"]
    assert audit["request"] == data.model_dump(mode="json")
    assert "operator_arn" not in json.dumps(result)
    assert data.report_uri not in json.dumps(result)
    reconcile(service.store, data, IDENTITY, ACCOUNT, clock=lambda: NOW)
    assert service.store.get(WORKERS, "lab-1") == retired
    with pytest.raises(Conflict):
        reconcile(
            service.store,
            data.model_copy(update={"report_uri": "fixture://changed"}),
            IDENTITY,
            ACCOUNT,
        )


@pytest.mark.parametrize(
    "change", ["account", "worker_version", "run_version", "session", "runtime"]
)
def test_operator_reconciliation_rejects_wrong_identity_or_stale_evidence(incident, change):
    service, request, _ = incident
    data = receipt(service, request)
    if change == "worker_version":
        data = data.model_copy(update={"expected_worker_version": 1})
    elif change == "run_version":
        data = data.model_copy(update={"expected_run_version": 1})
    elif change == "session":
        data = data.model_copy(update={"native_session_id": uuid4()})
    elif change == "runtime":
        data = data.model_copy(update={"engine_version": "different"})
    with pytest.raises((Conflict, ValueError)):
        reconcile(service.store, data, IDENTITY, "000000000000" if change == "account" else ACCOUNT)
    assert service.store.get(RECONCILIATIONS, str(data.reconciliation_id)) is None
    assert service.store.get("alice", f"session#{request.session_id}")["remote_active_run"] == str(
        request.run_id
    )


def test_operator_reconciliation_transaction_rolls_back_on_racing_session(incident, monkeypatch):
    service, request, _ = incident
    data = receipt(service, request)
    store = service.store
    transact = store.transact

    def race(writes):
        # An independent trusted mutation wins after the recovery read.
        key = f"session#{request.session_id}"
        old = store.get("alice", key)
        transact([Write("alice", key, revised(old), old["version"])])
        return transact(writes)

    monkeypatch.setattr(store, "transact", race)
    with pytest.raises(Conflict):
        reconcile(store, data, IDENTITY, ACCOUNT)
    assert store.get(RECONCILIATIONS, str(data.reconciliation_id)) is None
    assert service.raw(request.run_id)["cleanup"] is None
    assert store.get(WORKERS, "lab-1")["active_run"] == str(request.run_id)


def test_operator_recovery_requires_explicit_true_native_checks(incident):
    service, request, _ = incident
    data = receipt(service, request).model_dump(mode="json")
    for value in (False, "true", 1):
        data["checks"]["worker_stopped"] = value
        with pytest.raises(ValidationError):
            Reconciliation.model_validate(data)


def test_unbound_expired_run_can_close_only_after_verified_no_allocation(store):
    clock = [NOW]
    service = RunService(store, enabled=True, clock=lambda: clock[0])
    worker(store)
    session = saved(store)
    request = SubmitRun(run_id=uuid4(), session_id=session["id"], expected_version=1)
    service.submit("alice", request)
    service.claim("lab-1")
    clock[0] += 61
    service.reap()
    data = receipt(
        service,
        request,
        native_session_id=None,
        reset_command_id=None,
        release_command_id=None,
        no_allocation=True,
    )
    reconcile(store, data, IDENTITY, ACCOUNT)
    assert service.raw(request.run_id)["status"] == "outcome_unknown"
    assert store.get("alice", f"session#{request.session_id}")["remote_active_run"] is None
    assert store.get(WORKERS, "lab-1")["revoked"]


def test_operator_cli_checks_account_before_data_access(monkeypatch, tmp_path):
    monkeypatch.setattr(
        worker_admin.boto3,
        "client",
        lambda _: SimpleNamespace(
            get_caller_identity=lambda: {**IDENTITY, "Account": "000000000000"}
        ),
    )
    monkeypatch.setattr(
        worker_admin,
        "DynamoStore",
        lambda _: pytest.fail("Account mismatch must not open the store"),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "worker_admin",
            "enroll",
            "--expected-account-id",
            ACCOUNT,
            "--table",
            "academy-test",
            "--worker-id",
            "lab-1",
            "--engine-version",
            "fixture-engine",
            "--asset-version",
            "fixture-assets",
            "--credential-file",
            str(tmp_path / "token"),
        ],
    )
    with pytest.raises(SystemExit) as error:
        worker_admin.main()
    assert error.value.code == 2
    assert not (tmp_path / "token").exists()
