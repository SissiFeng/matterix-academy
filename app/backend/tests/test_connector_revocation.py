"""Explicit credential rejection stops one bound run; network ambiguity never replays."""

import json

import httpx
import pytest
from academy.companion.client import AcademyClient, run_once
from academy.companion.config import private_directory
from academy.companion.journal import Journal
from academy.companion.protocol import ProtocolEngine
from test_connector_companion import CloudFixture, command_for, config, credentials
from test_connector_protocol import robot_http as robot_http


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("lost_stop", [False, True])
def test_revoked_credential_stops_once_and_keeps_receipt_outbox(
    tmp_path, robot_http, status, lost_stop
):
    creds = credentials()
    cloud = CloudFixture(command_for(robot_http.profile, creds))
    robot_http.hold_running = True
    revoked = False

    def handle(request):
        nonlocal revoked
        if robot_http.status == "running":
            revoked = True
        if revoked:
            return httpx.Response(status, json={"detail": "credential rejected"})
        return cloud.handle(request)

    client = AcademyClient(
        config(robot_http.profile, robot_http.url), creds, transport=httpx.MockTransport(handle)
    )
    engine = ProtocolEngine(robot_http.url, robot_http.profile, sila_probe=lambda: None)
    original_request = engine._request

    def robot_request(method, path, **kwargs):
        result = original_request(method, path, **kwargs)
        if lost_stop and kwargs.get("json", {}).get("data", {}).get("actionType") == "stop":
            raise httpx.ReadTimeout("Stop response lost after fixture accepted it")
        return result

    engine._request = robot_request
    outcome = "unknown" if lost_stop else "stopped"
    state = private_directory(tmp_path / "state")
    try:
        with Journal(state) as journal:
            with pytest.raises(httpx.HTTPStatusError):
                run_once(
                    client,
                    engine,
                    journal,
                    robot_http.profile,
                    approve=lambda _: True,
                    poll_seconds=0,
                )
            assert journal.outbox()[0][1]["outcome"] == outcome
            assert journal.outbox()[0][1]["stop_confirmed"] is not lost_stop
        before = len(robot_http.requests)
        with Journal(state) as journal:
            with pytest.raises(httpx.HTTPStatusError):
                run_once(
                    client,
                    engine,
                    journal,
                    robot_http.profile,
                    approve=lambda _: pytest.fail("must not replay"),
                )
            assert journal.outbox()[0][1]["outcome"] == outcome
        assert len(robot_http.requests) == before
        actions = [
            json.loads(body)["data"]["actionType"]
            for _, path, body, _ in robot_http.requests
            if path.endswith("/actions")
        ]
        assert actions == ["play", "stop"]
    finally:
        client.close()
        engine.close()
