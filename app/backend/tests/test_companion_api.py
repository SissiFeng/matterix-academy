"""HTTP authentication boundary tests on both durable store implementations."""

import time
from uuid import uuid4

import httpx
import pytest
from academy.companion.client import AcademyClient, Credentials, run_once
from academy.companion.config import LocalConfig
from academy.companion.journal import Journal
from academy.companion.protocol import ProtocolEngine
from academy.companion_api import create_companion_app
from academy.connections import (
    BINDINGS,
    QUALIFICATIONS,
    ConnectionRevision,
    ConnectionService,
    ConnectorProbe,
)
from academy.connector_api import router
from academy.runs import revised
from fastapi.testclient import TestClient
from test_connections import PROBE, RELEASE, connection, pair, ready, receipt, resolution_for
from test_connector_protocol import robot_http  # noqa: F401


def machine_client(service, runtime="local"):
    app = create_companion_app(
        service.store,
        runtime=runtime,
        enabled=service.enabled,
        clock=service.clock,
        approved_release=service.approved_release,
    )
    return TestClient(app)


def test_browser_and_worker_credentials_cannot_access_machine_routes(store):
    service = ConnectionService(store)
    with machine_client(service) as client:
        assert client.get("/companion/me").status_code == 403
        assert (
            client.get(
                "/companion/me", headers={"authorization": "Bearer lab-1." + "s" * 50}
            ).status_code
            == 403
        )
        for origin in ["https://academy.test", "null", ""]:
            assert (
                client.post("/companion/pair", headers={"origin": origin}, json={}).status_code
                == 403
            )
        client.cookies.set("academy_local", "not-a-machine-token")
        assert client.post("/companion/command").status_code == 403


@pytest.mark.parametrize("runtime", ["local", "aws"])
def test_pair_and_probe_never_accept_owner_or_self_qualification(store, runtime):
    service = ConnectionService(store, approved_release=lambda *args: RELEASE)
    device, installation, data, token = pair(service)
    with machine_client(service, runtime) as client:
        headers = {"authorization": token}
        assert (
            client.post(
                "/companion/pair", json={**data.model_dump(mode="json"), "owner": "bob"}
            ).status_code
            == 422
        )
        assert (
            client.get("/companion/me", headers=headers).json()["connection"]["id"] == device["id"]
        )
        forged = {**PROBE, "qualified": True}
        assert client.post("/companion/probe", headers=headers, json=forged).status_code == 422
        response = client.post("/companion/probe", headers=headers, json=PROBE)
        assert response.status_code == 200
        assert not response.json()["connection"]["qualified"]
        assert response.headers["cache-control"] == "no-store"
        assert client.post("/companion/command", headers=headers).status_code == 204


def test_browser_routes_use_existing_identity_and_versions(app, client):
    if not hasattr(app.state, "connections"):
        app.state.connections = ConnectionService(app.state.store)
        app.include_router(router)
    connection_id = str(uuid4())
    path = f"/api/connections/{connection_id}"
    body = {
        "expected_version": 0,
        "instrument": "flex",
        "platform": "linux",
        "display_name": "Classroom Flex",
    }
    assert client.put(path, json=body).status_code == 200
    assert client.put(path, json=body).status_code == 409
    assert client.put(path, json={**body, "owner": "bob"}).status_code == 422
    first = client.post(path + "/pairing", json={"expected_version": 1})
    assert first.status_code == 200 and len(first.json()["code"]) >= 43
    assert "pairing_digest" not in first.text
    assert client.get("/api/connections").json()["connections"][0]["id"] == connection_id
    with TestClient(app) as other:
        assert other.get(path).status_code == 401
        other.post("/api/auth/guest", json={"name": "Other"})
        assert other.get(path).status_code == 404
        assert other.get("/api/connections").json() == {"connections": []}


def test_machine_http_claim_once_bound_receipt_and_no_cross_installation(store):
    now = [1790000000.0]
    service = ConnectionService(
        store, enabled=True, approved_release=lambda *args: RELEASE, clock=lambda: now[0]
    )
    device, _, token, _, _, request = ready(service)
    service.submit("alice", device["id"], request)
    _, _, _, other_token = pair(service, owner="bob", device=connection(service, owner="bob"))
    with machine_client(service) as client:
        headers = {"authorization": token}
        response = client.post("/companion/command", headers=headers)
        assert response.status_code == 200
        command = response.json()
        assert client.post("/companion/command", headers=headers).status_code == 204
        path = f"/companion/commands/{request.run_id}"
        assert client.get(path, headers={"authorization": other_token}).status_code == 404
        assert client.get(path, headers=headers).json()["run_id"] == str(request.run_id)
        evidence = receipt(command).model_dump(mode="json")
        assert client.post(path + "/receipt", headers=headers, json=evidence).status_code == 200
        assert client.post(path + "/receipt", headers=headers, json=evidence).status_code == 200
        evidence["detail"] = "conflicting receipt"
        assert client.post(path + "/receipt", headers=headers, json=evidence).status_code == 409


def test_real_companion_crosses_actual_api_and_protocol_engine_fixture(store, robot_http, tmp_path):  # noqa: F811
    """Real client/server/control flow, synthetic native proof and robot HTTP fixture only."""
    release = {**RELEASE}
    service = ConnectionService(store, enabled=True, approved_release=lambda *args: release)
    device, installation, token, _, _, request = ready(service)
    profile = robot_http.profile
    release.update(
        release_id=profile.release_id,
        artifact_sha256=profile.artifact_sha256,
        source_commit=profile.source_commit,
        supported_firmware=[profile.firmware],
        runtime_contract_id=profile.runtime_contract_id,
        runtime_release_id=profile.runtime_release_id,
        runtime_bundle_sha256=profile.runtime_bundle_sha256,
    )
    probe = {
        **{name: getattr(profile, name) for name in BINDINGS if name != "profile_sha256"},
        "profile_sha256": profile.sha256,
        "reachable": True,
        "capabilities": ["protocol-engine"],
    }
    service.probe(installation, ConnectorProbe(**probe))
    qualification = service.store.get(QUALIFICATIONS, device["id"])
    service.store.put(
        QUALIFICATIONS,
        device["id"],
        revised(
            qualification, **{name: probe[name] for name in BINDINGS}, expires_at=time.time() + 3600
        ),
        qualification["version"],
    )
    device = service.get("alice", device["id"])
    request = request.model_copy(update={"expected_version": device["version"]})
    service.submit("alice", device["id"], request)
    config = LocalConfig(
        academy_url="https://academy.example",
        allowed_academy_origins=["https://academy.example"],
        robot_url=robot_http.url,
        profile=profile,
    )
    credentials = Credentials(
        installation_id=installation["installation_id"],
        secret=token.split(".", 1)[1],
        academy_url=config.academy_url,
    )
    with machine_client(service, runtime="aws") as api:

        def forward(outgoing):
            response = api.request(
                outgoing.method,
                outgoing.url.raw_path.decode(),
                headers=dict(outgoing.headers),
                content=outgoing.content,
            )
            return httpx.Response(
                response.status_code, headers=response.headers, content=response.content
            )

        client = AcademyClient(config, credentials, transport=httpx.MockTransport(forward))
        # Explicitly injected SiLA fixture; this test proves no live SiLA wire behavior.
        engine = ProtocolEngine(config.robot_url, profile, sila_probe=lambda: None)
        try:
            with Journal(tmp_path / "companion") as journal:
                assert run_once(
                    client, engine, journal, profile, approve=lambda _: True, poll_seconds=0
                )
                assert not run_once(
                    client, engine, journal, profile, approve=lambda _: True, poll_seconds=0
                )
                assert journal.outbox() == []
        finally:
            engine.close()
            client.close()
    result = service.get_run("alice", device["id"], request.run_id)
    assert result["status"] == "completed"
    assert result["receipt"]["completed_actions"] == 4
    assert result["receipt"]["stop_confirmed"]
    assert service.get("alice", device["id"])["active_run_id"] is None
    assert (
        len([r for r in robot_http.requests if r[0] == "POST" and r[1].endswith("/actions")]) == 1
    )


def test_companion_reads_exact_offline_resolution_but_revoked_credentials_cannot(store):
    now = [1790000000.0]
    service = ConnectionService(
        store, enabled=True, approved_release=lambda *args: RELEASE, clock=lambda: now[0]
    )
    device, installation, token, _, _, request = ready(service)
    service.submit("alice", device["id"], request)
    command = service.claim(installation)
    assert command["resolution"] is None
    evidence = receipt(command, outcome="unknown", stop_confirmed=False)
    unknown = service.receipt(installation, request.run_id, evidence)
    resolution = resolution_for(command, unknown["version"])
    resolved = service.resolve_unknown(request.run_id, resolution)
    headers = {"authorization": token}
    path = f"/companion/commands/{request.run_id}"
    with machine_client(service) as api:
        response = api.get(path, headers=headers)
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "unknown"
        assert payload["resolution"] == {
            "request": resolution.model_dump(mode="json"),
            "resolved_at": now[0],
            "historical_status": "unknown",
            "replay_authorized": False,
        }
        assert payload["resolution"] == resolved["resolution"]
        _, _, _, other_token = pair(service)
        assert api.get(path, headers={"authorization": other_token}).status_code == 404
        assert api.post("/companion/command", headers=headers).status_code == 204
        assert service.get_run("alice", device["id"], request.run_id)[
            "receipt"
        ] == evidence.model_dump(mode="json")
        device = service.get("alice", device["id"])
        service.revoke(
            "alice", device["id"], ConnectionRevision(expected_version=device["version"])
        )
        assert api.get(path, headers=headers).status_code == 403
        assert (
            api.post(
                path + "/receipt", headers=headers, json=evidence.model_dump(mode="json")
            ).status_code
            == 403
        )
        assert (
            api.post(
                path + "/resolve", headers=headers, json=resolution.model_dump(mode="json")
            ).status_code
            == 404
        )
