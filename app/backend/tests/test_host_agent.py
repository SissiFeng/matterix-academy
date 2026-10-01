"""Bootstrap tests are software fixtures, never host/GPU qualification evidence."""

from academy.worker_api import create_worker_app
from fastapi.testclient import TestClient
from test_dispatch import worker


def test_unqualified_worker_can_only_publish_its_own_environment(store):
    token = worker(store, qualified=False, state="quarantined")
    worker(store, "lab-2", native_config={"python": "/other/python"})
    client = TestClient(create_worker_app(store, enabled=False))
    headers = {"Authorization": "Bearer " + token}
    report = dict(
        observed_at="2026-10-01T15:00:00Z",
        hostname="fixture-host",
        display=":1",
        environments=[],
        repositories=[],
        gpu="Fixture GPU",
    )
    assert client.post("/internal/workers/probe", json=report).status_code == 403
    response = client.post("/internal/workers/probe", json=report, headers=headers)
    assert response.status_code == 200
    assert store.get("system#host-probes", "lab-1")["report"] == report
    assert store.get("system#host-probes", "lab-2") is None
    assert client.get("/internal/workers/configuration", headers=headers).json() == {
        "enabled": False,
        "qualified": False,
        "configuration": None,
    }
    assert client.post("/internal/runs/claim", headers=headers).status_code == 403
    assert (
        client.post(
            "/internal/workers/probe", json={**report, "worker_id": "lab-2"}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/internal/workers/probe", json={**report, "gpu": "x" * 32000}, headers=headers
        ).status_code
        == 413
    )
    assert (
        client.post(
            "/internal/workers/probe",
            json=report,
            headers={**headers, "Origin": "https://example.org"},
        ).status_code
        == 403
    )


def test_operator_configuration_changes_only_when_journal_is_idle(tmp_path, monkeypatch):
    import pytest
    from academy.host_agent import configured_runner
    from academy.native_runner import NativeConfig
    from academy.worker import Journal

    monkeypatch.setattr(NativeConfig, "verify", lambda self: None)
    old = dict(
        python="/old/python",
        matterix_root="/old/code",
        assets_root="/old/assets",
        assets_data_dir="/old/assets/data",
        engine_version="a" * 40,
        asset_version="b" * 40,
        run_root="/old/runs",
        frame_root="/old/frames",
    )
    new = {**old, "run_root": "/new/runs", "engine_version": "c" * 40}
    journal = Journal(tmp_path / "journal.sqlite")
    try:
        runner = configured_runner(tmp_path, None, journal, {"configuration": old}, None)
        journal.save({"phase": "polling"})
        assert configured_runner(tmp_path, None, journal, {"configuration": new}, runner) is runner
        restarted = configured_runner(tmp_path, None, journal, {"configuration": new}, None)
        assert restarted.config.run_root == "/old/runs"
        journal.clear()
        updated = configured_runner(tmp_path, None, journal, {"configuration": new}, runner)
        assert updated.config.run_root == "/new/runs"
        journal.save({"phase": "polling"})
        (tmp_path / "native-config.json").unlink()
        with pytest.raises(RuntimeError, match="no saved native configuration"):
            configured_runner(tmp_path, None, journal, {"configuration": new}, None)
    finally:
        journal.close()
