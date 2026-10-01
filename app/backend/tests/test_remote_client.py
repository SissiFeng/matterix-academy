from uuid import uuid4

import httpx
import pytest
from academy.gateway import (
    GatewayUnavailable,
    MatterixGateway,
    RemoteCommand,
    RemoteOperationPending,
    RemoteOutcomeUnknown,
)


def snapshot(session_id):
    return {
        "id": str(session_id),
        "revision": 1,
        "status": "ready",
        "engine": "matterix",
        "simulation_only": True,
        "engine_version": "test-engine",
        "asset_version": "test-assets",
        "lease_expires_at": "2026-10-01T00:00:00Z",
        "observed_at": "2026-09-30T23:00:00Z",
    }


def test_remote_mutation_timeout_is_unknown_and_never_retried():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("timeout")

    gateway = MatterixGateway("https://gateway.example", "secret", httpx.MockTransport(handler))
    with pytest.raises(RemoteOutcomeUnknown):
        gateway.submit(
            uuid4(),
            RemoteCommand(
                command_id=uuid4(),
                expected_revision=1,
                action="aspirate",
                object_id="stock",
                volume_ul=100,
            ),
        )
    assert len(calls) == 1
    assert calls[0].headers["Authorization"] == "Bearer secret"
    gateway.close()


@pytest.mark.parametrize("status,body", [(500, {}), (200, {"unexpected": "response"})])
def test_remote_mutation_ambiguous_response_cannot_be_success(status, body):
    gateway = MatterixGateway(
        "https://gateway.example",
        "secret",
        httpx.MockTransport(lambda r: httpx.Response(status, json=body)),
    )
    with pytest.raises(RemoteOutcomeUnknown):
        gateway.reset(uuid4(), uuid4(), 1)
    gateway.close()


def test_remote_session_identity_and_engine_are_verified():
    session_id = uuid4()
    for body in [
        snapshot(uuid4()),
        {**snapshot(session_id), "engine": "teaching"},
        {**snapshot(session_id), "simulation_only": False},
    ]:
        gateway = MatterixGateway(
            "https://gateway.example",
            "secret",
            httpx.MockTransport(lambda r, body=body: httpx.Response(200, json=body)),
        )
        with pytest.raises(GatewayUnavailable):
            gateway.snapshot(session_id)
        gateway.close()


def test_remote_allocate_lookup_command_and_release_use_scoped_contract():
    import json

    session_id, command_id, operation_id = uuid4(), uuid4(), uuid4()
    allocation_id, reset_id, release_id = uuid4(), uuid4(), uuid4()
    requests = []

    def handler(request):
        requests.append(request)
        endpoint = request.method, request.url.path
        if endpoint == ("POST", "/v1/sessions"):
            assert json.loads(request.content) == {
                "allocation_id": str(allocation_id),
                "scene_id": "flex-first-transfer-v1",
            }
            return httpx.Response(200, json=snapshot(session_id))
        if endpoint == ("GET", f"/v1/allocations/{allocation_id}"):
            return httpx.Response(
                200,
                json={
                    "allocation_id": str(allocation_id),
                    "status": "allocated",
                    "session_id": str(session_id),
                },
            )
        if endpoint == ("GET", f"/v1/sessions/{session_id}"):
            return httpx.Response(200, json=snapshot(session_id))
        assert endpoint in {
            ("POST", f"/v1/sessions/{session_id}/commands"),
            ("GET", f"/v1/sessions/{session_id}/commands/{command_id}"),
            ("GET", f"/v1/sessions/{session_id}/operations/{operation_id}"),
            ("POST", f"/v1/sessions/{session_id}/reset"),
            ("DELETE", f"/v1/sessions/{session_id}"),
        }
        reply_command = (
            json.loads(request.content)["command_id"] if request.content else str(command_id)
        )
        return httpx.Response(
            200,
            json={
                "command_id": reply_command,
                "operation_id": str(operation_id),
                "status": "accepted",
            },
        )

    gateway = MatterixGateway("https://gateway.example", "secret", httpx.MockTransport(handler))
    assert gateway.allocate(allocation_id).id == session_id
    assert gateway.snapshot(session_id).revision == 1
    assert (
        gateway.submit(
            session_id,
            RemoteCommand(
                command_id=command_id, expected_revision=1, action="pickup", object_id="tips"
            ),
        ).operation_id
        == operation_id
    )
    assert gateway.operation(session_id, operation_id).status == "accepted"
    assert gateway.command_result(session_id, command_id).operation_id == operation_id
    gateway.reset(session_id, reset_id, 2)
    gateway.release(session_id, release_id, 3)
    assert json.loads(requests[-2].content) == {"command_id": str(reset_id), "expected_revision": 2}
    assert json.loads(requests[-1].content) == {
        "command_id": str(release_id),
        "expected_revision": 3,
    }
    assert [(r.method, r.url.path) for r in requests] == [
        ("POST", "/v1/sessions"),
        ("GET", f"/v1/allocations/{allocation_id}"),
        ("GET", f"/v1/sessions/{session_id}"),
        ("POST", f"/v1/sessions/{session_id}/commands"),
        ("GET", f"/v1/sessions/{session_id}/operations/{operation_id}"),
        ("GET", f"/v1/sessions/{session_id}/commands/{command_id}"),
        ("POST", f"/v1/sessions/{session_id}/reset"),
        ("DELETE", f"/v1/sessions/{session_id}"),
    ]
    assert all(r.url.host == "gateway.example" for r in requests)
    gateway.close()


@pytest.mark.parametrize("case", ["session", "allocation", "pending"])
def test_allocation_response_requires_its_original_allocation_association(case):
    session_id, allocation_id = uuid4(), uuid4()
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            return httpx.Response(200, json=snapshot(session_id))
        assert request.url.path == f"/v1/allocations/{allocation_id}"
        return httpx.Response(
            200,
            json={
                "allocation_id": str(uuid4() if case == "allocation" else allocation_id),
                "session_id": str(uuid4() if case == "session" else session_id),
                "status": "pending" if case == "pending" else "allocated",
            },
        )

    gateway = MatterixGateway("https://gateway.example", "secret", httpx.MockTransport(handler))
    with pytest.raises(RemoteOperationPending if case == "pending" else RemoteOutcomeUnknown):
        gateway.allocate(allocation_id)
    assert [request.method for request in calls] == ["POST", "GET"]
    gateway.close()


def test_unknown_mutations_can_be_reconciled_by_ids_known_before_submission():
    session_id, command_id, allocation_id, operation_id = uuid4(), uuid4(), uuid4(), uuid4()
    mutations = []

    def handler(request):
        if request.method != "GET":
            mutations.append(request)
            raise httpx.ReadTimeout("response lost after execution")
        if request.url.path == f"/v1/allocations/{allocation_id}":
            return httpx.Response(
                200,
                json={
                    "allocation_id": str(allocation_id),
                    "status": "allocated",
                    "session_id": str(session_id),
                },
            )
        assert request.url.path == f"/v1/sessions/{session_id}/commands/{command_id}"
        return httpx.Response(
            200,
            json={
                "command_id": str(command_id),
                "operation_id": str(operation_id),
                "status": "completed",
            },
        )

    gateway = MatterixGateway("https://gateway.example", "secret", httpx.MockTransport(handler))
    with pytest.raises(RemoteOutcomeUnknown):
        gateway.allocate(allocation_id)
    assert gateway.allocation(allocation_id).session_id == session_id
    with pytest.raises(RemoteOutcomeUnknown):
        gateway.submit(
            session_id,
            RemoteCommand(
                command_id=command_id, expected_revision=1, action="pickup", object_id="tips"
            ),
        )
    assert gateway.command_result(session_id, command_id).status == "completed"
    assert len(mutations) == 2
    gateway.close()


def test_reconciliation_rejects_different_command_or_allocation():
    for allocation in [True, False]:
        response = (
            {"allocation_id": str(uuid4()), "status": "allocated", "session_id": str(uuid4())}
            if allocation
            else {"command_id": str(uuid4()), "operation_id": str(uuid4()), "status": "completed"}
        )
        gateway = MatterixGateway(
            "https://gateway.example",
            "secret",
            httpx.MockTransport(lambda r, response=response: httpx.Response(200, json=response)),
        )
        with pytest.raises(GatewayUnavailable):
            if allocation:
                gateway.allocation(uuid4())
            else:
                gateway.command_result(uuid4(), uuid4())
        gateway.close()
