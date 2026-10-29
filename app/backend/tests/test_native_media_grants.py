"""Local grant handoff tests; no AWS requests, video or native qualification."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from academy import native_media
from academy.gateway import GatewayUnavailable
from academy.native_files import read_json, write_json
from academy.native_runner import NativeFlexRunner


@pytest.fixture
def setup(tmp_path):
    run_id, native_id = str(uuid4()), str(uuid4())
    local = {
        "run": {"run_id": run_id, "plan_hash": "saved-plan"},
        "binding": {"native_session_id": native_id},
    }
    manifest = {"binding": local["binding"], "request": local["run"]}
    runner = object.__new__(NativeFlexRunner)
    runner.config = SimpleNamespace(run_root=str(tmp_path))
    runner.client = Mock()
    folder = runner.folder(local)
    folder.mkdir()

    def lease(client_id):
        return {
            "native_session_id": native_id,
            "lease_expires": time.time() + 60,
            "viewers": [{"client_id": client_id, "expires": time.time() + 35}],
        }

    def grant(client_id, password):
        return {
            "run_id": run_id,
            "native_session_id": native_id,
            "plan_hash": "saved-plan",
            "signaling_url": "wss://fixture.invalid",
            "ice_servers": [
                {"urls": "turn:fixture.invalid:443", "username": "fixture", "credential": password}
            ],
            "viewer_client_id": client_id,
        }

    write_json(folder / "lease.json", lease("previous-viewer"))
    write_json(folder / "publisher.json", grant("previous-viewer", "expired-fixture"))
    return runner, local, manifest, folder, lease, grant


def test_new_viewer_refreshes_turn_before_publishing_allowlist(setup):
    runner, local, manifest, folder, lease, grant = setup
    calls = []

    def post(run, action):
        assert run == local["run"]
        calls.append(action)
        if action == "viewers":
            return lease("reloaded-viewer")
        assert action == "publisher"
        # The new viewer cannot be authorized until its fresh credentials exist.
        assert read_json(folder / "lease.json")["viewers"][0]["client_id"] == "previous-viewer"
        result = grant(None, "fresh-fixture")
        result.pop("viewer_client_id")  # Existing API response stays unchanged.
        return result

    runner.client.post.side_effect = post
    runner.renew(local)
    assert calls == ["viewers", "publisher"]
    assert read_json(folder / "lease.json")["viewers"][0]["client_id"] == "reloaded-viewer"
    saved = native_media.publisher_grant(folder, manifest, "reloaded-viewer")
    assert saved["ice_servers"][0]["credential"] == "fresh-fixture"
    assert native_media.publisher_grant(folder, manifest, "previous-viewer") is None


def test_same_viewer_heartbeat_does_not_request_more_turn_credentials(setup):
    runner, local, _, folder, lease, _ = setup
    original = read_json(folder / "publisher.json")
    runner.client.post.return_value = lease("previous-viewer")
    runner.renew(local)
    runner.client.post.assert_called_once_with(local["run"], "viewers")
    assert read_json(folder / "publisher.json") == original


def test_failed_grant_refresh_does_not_authorize_new_viewer_or_replace_old_grant(setup):
    runner, local, _, folder, lease, _ = setup
    previous_lease = read_json(folder / "lease.json")
    previous_grant = read_json(folder / "publisher.json")
    runner.client.post.side_effect = [lease("reloaded-viewer"), OSError("fixture unavailable")]
    with pytest.raises(OSError):
        runner.renew(local)
    assert read_json(folder / "lease.json") == previous_lease
    assert read_json(folder / "publisher.json") == previous_grant


@pytest.mark.parametrize("field", ["run_id", "native_session_id", "plan_hash"])
def test_mismatched_refreshed_grant_never_replaces_current_binding(setup, field):
    runner, local, manifest, folder, lease, grant = setup
    original = read_json(folder / "publisher.json")
    wrong = grant(None, "fresh-fixture") | {field: "different"}
    runner.client.post.side_effect = [lease("reloaded-viewer"), wrong]
    with pytest.raises(GatewayUnavailable, match="bound native run"):
        runner.renew(local)
    assert read_json(folder / "publisher.json") == original
    write_json(folder / "publisher.json", wrong)
    with pytest.raises(ValueError, match="identity mismatch"):
        native_media.publisher_grant(folder, manifest)


def test_offer_waits_for_new_allowlist_and_matching_fresh_credentials(setup, monkeypatch):
    runner, local, manifest, folder, lease, grant = setup
    sleeps = []

    async def advance(_):
        sleeps.append(1)
        runner.client.post.side_effect = [lease("reloaded-viewer"), grant(None, "fresh-fixture")]
        runner.renew(local)

    def allowed(client_id):
        return read_json(folder / "lease.json")["viewers"][0]["client_id"] == client_id

    monkeypatch.setattr(native_media.asyncio, "sleep", advance)
    result = asyncio.run(
        native_media.wait_for_viewer_grant(folder, manifest, "reloaded-viewer", allowed)
    )
    assert sleeps == [1]
    assert result["ice_servers"][0]["credential"] == "fresh-fixture"


def test_offer_never_uses_stale_credentials_even_if_allowlist_arrives_first(setup, monkeypatch):
    _, _, manifest, folder, _, grant = setup
    sleeps = []

    async def advance(_):
        sleeps.append(1)
        write_json(folder / "publisher.json", grant("reloaded-viewer", "fresh-fixture"))

    monkeypatch.setattr(native_media.asyncio, "sleep", advance)
    result = asyncio.run(
        native_media.wait_for_viewer_grant(folder, manifest, "reloaded-viewer", lambda _: True)
    )
    assert sleeps == [1]
    assert result["viewer_client_id"] == "reloaded-viewer"
    assert result["ice_servers"][0]["credential"] == "fresh-fixture"


def test_offer_wait_has_deadline_and_expired_lease_never_authorizes(setup, monkeypatch):
    _, _, manifest, folder, _, _ = setup
    # asyncio itself reads monotonic; hold a stable initial value until the
    # coroutine reaches its first sleep, then advance past its finite deadline.
    clock = [100.0]
    monkeypatch.setattr(native_media.time, "monotonic", lambda: clock[0])

    async def advance(_):
        clock[0] = 121.0

    monkeypatch.setattr(native_media.asyncio, "sleep", advance)
    with pytest.raises(ValueError, match="Fresh authorized"):
        asyncio.run(
            native_media.wait_for_viewer_grant(folder, manifest, "reloaded-viewer", lambda _: False)
        )
    write_json(folder / "lease.json", {"lease_expires": time.time() - 1})
    with pytest.raises(ValueError, match="Fresh authorized"):
        asyncio.run(
            native_media.wait_for_viewer_grant(folder, manifest, "previous-viewer", lambda _: True)
        )


def test_cleanup_interrupts_pending_offer_before_supervisor_exit_timeout(setup, monkeypatch):
    _, _, manifest, folder, _, _ = setup

    async def stop(_):
        write_json(folder / "stop-media.json", {})

    monkeypatch.setattr(native_media.asyncio, "sleep", stop)
    with pytest.raises(ValueError, match="Fresh authorized"):
        asyncio.run(
            native_media.wait_for_viewer_grant(folder, manifest, "reloaded-viewer", lambda _: False)
        )
