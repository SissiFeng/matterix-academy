"""Cloud grants tested with a fake KVS service; not streaming/GPU evidence."""

from uuid import uuid4

import pytest
from academy.media import MEDIA, VIEWERS, MediaService
from academy.recipes import CreateMixing, mixing_session
from academy.runs import BindRequest, RunService, StartRequest, SubmitRun
from fastapi import HTTPException
from test_dispatch import worker


class Transport:
    def __init__(self):
        self.grants = []
        self.deleted = []

    def ensure(self, native_id):
        return "fixture:" + native_id

    def grant(self, arn, role, client_id=None):
        self.grants.append((arn, role, client_id))
        return {"signaling_url": "wss://fixture.invalid", "ice_servers": []}

    def delete(self, arn):
        self.deleted.append(arn)


@pytest.fixture
def media(store):
    clock = [1790863200.0]
    runs = RunService(store, True, clock=lambda: clock[0])
    worker(store, scenes=["flex-mixing"], controls=[])
    session = mixing_session(CreateMixing(session_id=uuid4()))
    store.put("alice", "session#" + session["id"], session, None)
    request = SubmitRun(run_id=uuid4(), session_id=session["id"], expected_version=1)
    runs.submit("alice", request)
    run = runs.claim("lab-1")
    runs.start(
        "lab-1", request.run_id, StartRequest(claim_token=run["claim_token"], command_id=uuid4())
    )
    runs.bind(
        "lab-1",
        request.run_id,
        BindRequest(
            claim_token=run["claim_token"],
            native_session_id=uuid4(),
            expected_revision=1,
            engine_version="fixture-engine",
            asset_version="fixture-assets",
        ),
    )
    transport = Transport()
    return MediaService(runs, transport), run, clock, transport


def test_grants_bind_owner_run_plan_and_native_instance(media):
    service, run, _, transport = media
    with pytest.raises(HTTPException) as missing:
        service.viewer("alice", run["run_id"], uuid4())
    assert missing.value.status_code == 409
    publisher = service.publisher("lab-1", run["run_id"], run["claim_token"])
    client_id = uuid4()
    viewer = service.viewer("alice", run["run_id"], client_id)
    assert viewer["native_session_id"] == publisher["native_session_id"]
    assert viewer["plan_hash"] == run["plan_hash"]
    assert viewer["client_id"] == str(client_id)
    assert [g[1] for g in transport.grants] == ["MASTER", "VIEWER"]
    with pytest.raises(HTTPException) as denied:
        service.viewer("bob", run["run_id"], uuid4())
    assert denied.value.status_code == 404
    assert len(transport.grants) == 2


def test_viewer_renewal_has_a_short_native_enforced_lease_and_replacement(media):
    service, run, clock, transport = media
    service.publisher("lab-1", run["run_id"], run["claim_token"])
    viewer = uuid4()
    service.viewer("alice", run["run_id"], viewer)
    state = service.viewers("lab-1", run["run_id"], run["claim_token"])
    assert state["viewers"][0]["frame_received"] is False
    clock[0] += 10
    renewed = service.viewer("alice", run["run_id"], viewer, connect=False, frame_received=True)
    assert renewed["expires"] == clock[0] + 35
    assert "signaling_url" not in renewed
    assert len(transport.grants) == 2
    replacement = uuid4()
    service.viewer("alice", run["run_id"], replacement)
    with pytest.raises(HTTPException):
        service.viewer("alice", run["run_id"], viewer, connect=False)
    clock[0] += 36
    assert service.viewers("lab-1", run["run_id"], run["claim_token"])["viewers"] == []


def test_expired_run_cannot_create_or_view_media_and_is_reaped(media):
    service, run, clock, transport = media
    service.publisher("lab-1", run["run_id"], run["claim_token"])
    service.viewer("alice", run["run_id"], uuid4())
    clock[0] += 61
    with pytest.raises(HTTPException):
        service.publisher("lab-1", run["run_id"], run["claim_token"])
    with pytest.raises(HTTPException):
        service.viewer("alice", run["run_id"], uuid4())
    assert service.reap() == 1
    assert len(transport.deleted) == 1
    assert service.store.partition(MEDIA) == []
    assert service.store.partition(VIEWERS) == []


def test_wrong_worker_or_disabled_deployment_never_receives_media_credentials(media):
    service, run, _, transport = media
    worker(service.store, "different-worker")
    with pytest.raises(HTTPException):
        service.publisher("different-worker", run["run_id"], run["claim_token"])
    service.runs.enabled = False
    with pytest.raises(HTTPException):
        service.publisher("lab-1", run["run_id"], run["claim_token"])
    assert transport.grants == []
