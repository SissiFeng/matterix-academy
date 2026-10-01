"""Synthetic transport and runner tests; these are not native GPU acceptance."""

from uuid import uuid4

import httpx
import pytest
from academy.gateway import RemoteOutcomeUnknown
from academy.remote_run import RemoteRunRequest, RemoteRunSnapshot
from academy.runs import RUNS, RunService, SubmitRun
from academy.worker import Journal, Worker, WorkerClient
from academy.worker_api import create_worker_app
from fastapi.testclient import TestClient
from test_dispatch import saved, worker
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
