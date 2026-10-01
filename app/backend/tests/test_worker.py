"""Synthetic transport and runner tests; these are not native GPU acceptance."""

import json
from unittest.mock import Mock
from uuid import uuid4

import academy.worker as worker_module
import httpx
import pytest
from academy.gateway import (
    GatewayUnavailable,
    MatterixGateway,
    RemoteOperationPending,
    RemoteOutcomeUnknown,
)
from academy.remote_run import RemoteRunRequest, RemoteRunSnapshot
from academy.runs import RUNS, RunService, SubmitRun
from academy.worker import GatewayRunner, Journal, Worker, WorkerClient
from academy.worker_api import create_worker_app
from fastapi.testclient import TestClient
from test_dispatch import saved, worker
from test_remote_client import snapshot as session_snapshot
from test_remote_run import report


class FixtureRunner:
    def __init__(self, failure=None):
        self.starts = 0
        self.allocations = 0
        self.polls = 0
        self.releases = 0
        self.failure = failure
        self.native_session = str(uuid4())

    def prepare(self, local, recovering=False):
        if not recovering:
            self.allocations += 1
            if self.failure == "allocation":
                self.failure = None
                raise RemoteOutcomeUnknown("Synthetic allocation acknowledgement loss")
        return {
            "native_session_id": self.native_session,
            "expected_revision": 1,
            "engine_version": "fixture-engine",
            "asset_version": "fixture-assets",
        }

    def result(self, local):
        request = RemoteRunRequest(
            run_id=local["run"]["run_id"],
            expected_revision=1,
            experiment=local["run"]["plan"],
            plan_hash=local["run"]["plan_hash"],
        )
        return RemoteRunSnapshot.model_validate(
            report(self.native_session, request, completed=4, sequence=1)
        )

    def start(self, local):
        self.starts += 1
        if self.failure == "start":
            self.failure = None
            raise RemoteOutcomeUnknown("Synthetic start acknowledgement loss")
        if self.failure == "crash":
            self.failure = None
            raise InterruptedError("Synthetic process death after native start")
        return self.result(local)

    def poll(self, local):
        self.polls += 1
        return self.result(local)

    def cleanup(self, local, recovering=False):
        return dict(
            command_id=local["cleanup_id"],
            native_session_id=self.native_session,
            engine_version="fixture-engine",
            asset_version="fixture-assets",
            reset_verified=True,
            checks={k: True for k in ("objects", "liquids", "tips", "controllers", "stopped")},
        )

    def release(self, local, recovering=False):
        self.releases += not recovering


@pytest.fixture
def worker_system(store, tmp_path):
    now = 1790863200.0
    token = worker(store)
    service = RunService(store, enabled=True, clock=lambda: now)
    session = saved(store)
    submitted = service.submit(
        "alice", SubmitRun(run_id=uuid4(), session_id=session["id"], expected_version=1)
    )
    app = TestClient(create_worker_app(store, enabled=True, clock=lambda: now))

    def send(request):
        response = app.request(
            request.method, request.url.path, headers=dict(request.headers), content=request.content
        )
        return httpx.Response(response.status_code, content=response.content)

    client = WorkerClient("https://testserver", token, httpx.MockTransport(send))
    path = tmp_path / "worker.sqlite"
    return service, submitted, client, path, now


@pytest.mark.parametrize("failure", [None, "start", "allocation"])
def test_outbound_lifecycle_recovers_original_ids_without_native_replay(worker_system, failure):
    service, submitted, client, path, now = worker_system
    runner = FixtureRunner(failure)
    journal = Journal(path)
    engine = Worker(client, runner, journal, clock=lambda: now)
    try:
        engine.step()
        if journal.read():
            engine.step()
        assert service.raw(submitted["run_id"])["status"] == "completed"
        assert service.raw(submitted["run_id"])["cleanup"]["reset_verified"]
        assert journal.read() is None
        assert runner.starts == 1
        assert runner.allocations == 1
        assert runner.releases == 1
    finally:
        journal.close()


def test_restart_reads_running_simulator_without_repeating_start(worker_system):
    service, submitted, client, path, now = worker_system
    runner = FixtureRunner("crash")
    journal = Journal(path)
    with pytest.raises(InterruptedError):
        Worker(client, runner, journal, clock=lambda: now).step()
    assert journal.read()["phase"] == "start_intent"
    journal.close()
    journal = Journal(path)
    try:
        Worker(client, runner, journal, clock=lambda: now).step()
        assert runner.starts == 1 and runner.polls == 1
        assert service.raw(submitted["run_id"])["status"] == "completed"
    finally:
        journal.close()


def test_two_processes_cannot_share_native_journal(tmp_path):
    journal = Journal(tmp_path / "worker.sqlite")
    try:
        with pytest.raises(BlockingIOError):
            Journal(tmp_path / "worker.sqlite")
        assert (tmp_path / "worker.sqlite").stat().st_mode & 0o777 == 0o600
    finally:
        journal.close()


def test_lost_journal_after_start_never_starts_again(worker_system):
    service, submitted, client, path, now = worker_system
    runner = FixtureRunner("crash")
    journal = Journal(path)
    with pytest.raises(InterruptedError):
        Worker(client, runner, journal, clock=lambda: now).step()
    journal.clear()
    try:
        Worker(client, runner, journal, clock=lambda: now).step()
        assert service.store.get(RUNS, submitted["run_id"])["status"] == "outcome_unknown"
        assert runner.starts == 1
    finally:
        journal.close()


def test_lost_final_cloud_ack_resumes_cleanup_without_polling_new_terminal(worker_system):
    service, submitted, client, path, now = worker_system
    runner = FixtureRunner()
    journal = Journal(path)
    post = client.post
    lost = [False]

    def lose_ack(run, action, **body):
        result = post(run, action, **body)
        if action == "snapshots" and not lost[0]:
            lost[0] = True
            raise httpx.ReadTimeout("Synthetic cloud acknowledgement loss")
        return result

    client.post = lose_ack
    engine = Worker(client, runner, journal, clock=lambda: now)
    try:
        with pytest.raises(httpx.ReadTimeout):
            engine.step()
        assert service.raw(submitted["run_id"])["status"] == "completed"
        engine.step()
        assert runner.polls == 0
        assert runner.starts == 1
        assert journal.read() is None
    finally:
        journal.close()


def test_runtime_manifest_drift_is_rejected_before_native_start(worker_system):
    service, submitted, client, path, now = worker_system
    runner = FixtureRunner()
    prepare = runner.prepare
    runner.prepare = lambda local, recovering=False: {
        **prepare(local, recovering),
        "asset_version": "unqualified-upgrade",
    }
    journal = Journal(path)
    try:
        Worker(client, runner, journal, clock=lambda: now).step()
        assert runner.starts == 0
        assert service.raw(submitted["run_id"])["status"] == "outcome_unknown"
        assert service.worker("lab-1")["state"] == "quarantined"
    finally:
        journal.close()


@pytest.mark.parametrize("status", ["completed", "failed", "unknown"])
def test_terminal_journal_evidence_is_resent_when_cloud_write_never_arrived(worker_system, status):
    service, submitted, client, path, now = worker_system
    runner = FixtureRunner()
    result = runner.result
    runner.result = lambda local: result(local).model_copy(
        update={"status": status, "error": "Synthetic failure" if status == "failed" else None}
    )
    journal = Journal(path)
    post = client.post
    lost = [False]

    def lose_before_write(run, action, **body):
        if action == "snapshots" and not lost[0]:
            lost[0] = True
            raise httpx.ReadTimeout("Synthetic request loss before cloud write")
        return post(run, action, **body)

    client.post = lose_before_write
    engine = Worker(client, runner, journal, clock=lambda: now)
    try:
        with pytest.raises(httpx.ReadTimeout):
            engine.step()
        frozen = journal.read()["last_snapshot"]
        assert service.raw(submitted["run_id"])["snapshot"] is None
        engine.step()
        assert runner.polls == 0 and runner.starts == 1
        cloud = service.raw(submitted["run_id"])
        assert cloud["snapshot"] == frozen
        assert cloud["status"] == ("outcome_unknown" if status == "unknown" else status)
        assert bool(cloud["cleanup"]) == (status != "unknown")
    finally:
        journal.close()


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_lost_terminal_journal_requires_operator_instead_of_recreating_cleanup(
    worker_system, status
):
    from academy.runs import revised

    service, submitted, client, path, now = worker_system
    runner = FixtureRunner()
    runner.cleanup = Mock(side_effect=InterruptedError("Synthetic death before reset"))
    journal = Journal(path)
    engine = Worker(client, runner, journal, clock=lambda: now)
    try:
        with pytest.raises(InterruptedError):
            engine.step()
        previous = service.raw(submitted["run_id"])
        service.store.put(
            RUNS, submitted["run_id"], revised(previous, status=status), previous["version"]
        )
        journal.clear()
        engine.step()
        current = service.raw(submitted["run_id"])
        assert current["status"] == status
        assert "journal is missing" in current["reason"]
        assert service.worker("lab-1")["state"] == "quarantined"
        assert current["cleanup"] is None
        assert runner.starts == runner.allocations == runner.cleanup.call_count == 1
        assert runner.releases == 0
    finally:
        journal.close()


def test_async_reset_and_release_poll_original_operation_without_replay(worker_system):
    service, submitted, client, path, now = worker_system
    runner = FixtureRunner()
    commands, operations, requests = {}, {}, []

    def handle(request):
        requests.append(request)
        route = request.url.path
        if request.method in {"POST", "DELETE"}:
            body = json.loads(request.content)
            command_id = body["command_id"]
            op = {"command_id": command_id, "operation_id": str(uuid4()), "status": "accepted"}
            commands[command_id] = op
            operations[op["operation_id"]] = 0
            return httpx.Response(200, json=op)
        if "/commands/" in route:
            return httpx.Response(200, json=commands[route.rsplit("/", 1)[-1]])
        if "/operations/" in route:
            operation_id = route.rsplit("/", 1)[-1]
            operations[operation_id] += 1
            original = next(op for op in commands.values() if op["operation_id"] == operation_id)
            return httpx.Response(
                200,
                json={
                    **original,
                    "status": "running" if operations[operation_id] == 1 else "completed",
                },
            )
        if "/reset-verification/" in route:
            return httpx.Response(
                200,
                json={
                    "command_id": route.rsplit("/", 1)[-1],
                    "native_session_id": runner.native_session,
                    "engine_version": "fixture-engine",
                    "asset_version": "fixture-assets",
                    "reset_verified": True,
                    "checks": {
                        key: True
                        for key in ("objects", "liquids", "tips", "controllers", "stopped")
                    },
                },
            )
        assert route == f"/v1/sessions/{runner.native_session}"
        return httpx.Response(200, json={**session_snapshot(runner.native_session), "revision": 3})

    gateway = MatterixGateway("https://gateway.example", "secret", httpx.MockTransport(handle))
    native = GatewayRunner(gateway)
    runner.cleanup, runner.release = native.cleanup, native.release
    journal = Journal(path)
    engine = Worker(client, runner, journal, clock=lambda: now)
    try:
        engine.step()
        assert journal.read()["phase"] == "cleanup_intent"
        assert service.worker("lab-1")["state"] == "busy"
        engine.step()
        assert journal.read()["phase"] == "release_intent"
        assert service.worker("lab-1")["state"] == "busy"
        engine.step()
        assert journal.read() is None
        assert service.raw(submitted["run_id"])["cleanup"]["reset_verified"]
        assert [r.method for r in requests if r.method != "GET"] == ["POST", "DELETE"]
        assert list(operations.values()) == [2, 2]
    finally:
        journal.close()
        gateway.close()


@pytest.mark.parametrize("case", ["failed", "unknown", "command", "operation"])
def test_async_cleanup_rejects_failed_or_mismatched_operation(case):
    session_id, command_id, operation_id = uuid4(), uuid4(), uuid4()
    calls = []
    receipt = {
        "command_id": str(command_id),
        "operation_id": str(operation_id),
        "status": "accepted",
    }

    def handle(request):
        calls.append(request)
        if request.method == "POST":
            return httpx.Response(200, json=receipt)
        assert request.url.path == f"/v1/sessions/{session_id}/operations/{operation_id}"
        return httpx.Response(
            200,
            json={
                **receipt,
                "command_id": str(uuid4()) if case == "command" else str(command_id),
                "operation_id": str(uuid4()) if case == "operation" else str(operation_id),
                "status": case if case in {"failed", "unknown"} else "completed",
            },
        )

    gateway = MatterixGateway("https://gateway.example", "secret", httpx.MockTransport(handle))
    with pytest.raises(GatewayUnavailable):
        GatewayRunner(gateway).cleanup(
            {
                "binding": {"native_session_id": str(session_id)},
                "cleanup_id": str(command_id),
                "last_snapshot": {"session_revision": 2},
            }
        )
    assert [request.method for request in calls] == ["POST", "GET"]
    gateway.close()


@pytest.mark.parametrize("phase", ["prepare", "recover", "start"])
def test_missing_gateway_action_blocks_native_mutation(phase):
    calls = []

    def handle(request):
        calls.append(request)
        assert request.method == "GET" and request.url.path == "/v1/capabilities"
        return httpx.Response(
            200,
            json={
                "contract_version": "1",
                "engine": "matterix",
                "simulation_only": True,
                "supports_isolated_sessions": True,
                "actions": ["pickup", "dispense", "drop"],
            },
        )

    gateway = MatterixGateway("https://gateway.example", "secret", httpx.MockTransport(handle))
    native = GatewayRunner(gateway)
    local = {"allocation_id": str(uuid4()), "run": {"plan": {"actions": [{"kind": "aspirate"}]}}}
    with pytest.raises(GatewayUnavailable, match="every saved workflow action"):
        if phase == "start":
            native.start(local)
        else:
            native.prepare(local, recovering=phase == "recover")
    assert len(calls) == 1
    gateway.close()


def test_pending_allocation_recovers_by_lookup_without_allocating_again():
    allocation_id, session_id = uuid4(), uuid4()
    calls = []
    lookups = [0]

    def handle(request):
        calls.append(request)
        if request.url.path == "/v1/capabilities":
            return httpx.Response(
                200,
                json={
                    "contract_version": "1",
                    "engine": "matterix",
                    "simulation_only": True,
                    "supports_isolated_sessions": True,
                    "actions": ["pickup"],
                },
            )
        if request.url.path == f"/v1/allocations/{allocation_id}":
            lookups[0] += 1
            return httpx.Response(
                200,
                json={
                    "allocation_id": str(allocation_id),
                    "session_id": str(session_id),
                    "status": "pending" if lookups[0] == 1 else "allocated",
                },
            )
        return httpx.Response(200, json=session_snapshot(session_id))

    gateway = MatterixGateway("https://gateway.example", "secret", httpx.MockTransport(handle))
    native = GatewayRunner(gateway)
    local = {
        "allocation_id": str(allocation_id),
        "run": {"plan": {"actions": [{"kind": "pickup"}]}},
    }
    with pytest.raises(RemoteOperationPending):
        native.prepare(local)
    assert native.prepare(local, recovering=True)["native_session_id"] == str(session_id)
    assert len([request for request in calls if request.method == "POST"]) == 1
    gateway.close()


def test_idle_worker_uses_bounded_backoff_and_active_work_resets_it(monkeypatch, tmp_path):
    credential = tmp_path / "credential"
    credential.write_text("synthetic-secret")
    monkeypatch.setattr(
        "sys.argv",
        [
            "worker",
            "--api-url",
            "https://worker.example",
            "--gateway-url",
            "https://gateway.example",
            "--credential-file",
            str(credential),
            "--gateway-credential-file",
            str(credential),
        ],
    )
    monkeypatch.setattr(worker_module, "Journal", Mock())
    monkeypatch.setattr(worker_module, "WorkerClient", Mock())
    monkeypatch.setattr(worker_module, "MatterixGateway", Mock())
    engine = Mock()
    engine.step.side_effect = [False, False, False, False, False, None, False]
    monkeypatch.setattr(worker_module, "Worker", Mock(return_value=engine))
    delays = []

    def sleep(delay):
        delays.append(delay)
        if len(delays) == 7:
            raise KeyboardInterrupt

    monkeypatch.setattr(worker_module.time, "sleep", sleep)
    with pytest.raises(KeyboardInterrupt):
        worker_module.main()
    assert delays == [4, 8, 16, 20, 20, 2, 4]
