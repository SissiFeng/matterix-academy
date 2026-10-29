"""Failure-path regressions for the supervised runtime; software fixtures only."""

import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest
from academy.companion.client import AcademyClient, run_once
from academy.companion.compiler import compile_plan
from academy.companion.config import LocalConfig, private_directory, read_private, write_private
from academy.companion.journal import Journal
from academy.companion.protocol import ProtocolEngine
from academy.remote_run import workflow_digest
from test_connector_companion import CloudFixture, command_for, config, credentials
from test_connector_operator import invoke
from test_connector_operator import qualification_context as qualification_context
from test_connector_protocol import plan_for, profile_for
from test_connector_protocol import robot_http as robot_http


def actions(robot):
    return [
        (path, json.loads(body)["data"]["actionType"])
        for _, path, body, _ in robot.requests
        if path.endswith("/actions")
    ]


@pytest.mark.parametrize("failure", ["timeout", "503", "malformed", "changed-binding"])
@pytest.mark.parametrize("lost_stop", [False, True])
def test_failed_authority_check_stops_bound_run_once_and_preserves_unknown(
    tmp_path, robot_http, failure, lost_stop
):
    creds = credentials()
    cloud = CloudFixture(command_for(robot_http.profile, creds))
    robot_http.hold_running = True

    def handle(request):
        if robot_http.status == "running" and request.method == "GET":
            if failure == "timeout":
                raise httpx.ReadTimeout("authority response lost", request=request)
            if failure == "503":
                return httpx.Response(503, json={"detail": "temporary outage"})
            if failure == "malformed":
                return httpx.Response(200, json={"unexpected": True})
            return httpx.Response(200, json={**cloud.command, "plan_hash": "e" * 64})
        return cloud.handle(request)

    client = AcademyClient(
        config(robot_http.profile, robot_http.url), creds, transport=httpx.MockTransport(handle)
    )
    engine = ProtocolEngine(robot_http.url, robot_http.profile, sila_probe=lambda: None)
    original_request = engine._request

    def robot_request(method, path, **kwargs):
        result = original_request(method, path, **kwargs)
        if lost_stop and kwargs.get("json", {}).get("data", {}).get("actionType") == "stop":
            raise httpx.ReadTimeout("Stop response lost after acceptance")
        return result

    engine._request = robot_request
    state = private_directory(tmp_path / "state")
    try:
        with Journal(state) as journal:
            assert run_once(
                client, engine, journal, robot_http.profile, approve=lambda _: True, poll_seconds=0
            )
            receipt = cloud.receipts[0]
            assert receipt["outcome"] == "unknown"
            assert receipt["stop_confirmed"] is not lost_stop
            assert journal.unresolved()
        before = len(robot_http.requests)
        with Journal(state) as journal:
            assert not run_once(
                client,
                engine,
                journal,
                robot_http.profile,
                approve=lambda _: pytest.fail("Uncertain command must not replay"),
            )
        assert len(robot_http.requests) == before
        assert actions(robot_http) == [
            ("/runs/robot-run-1/actions", "play"),
            ("/runs/robot-run-1/actions", "stop"),
        ]
    finally:
        client.close()
        engine.close()


@pytest.mark.parametrize("expiry_at", ["analysis", "preflight", "create", "authority"])
def test_expired_execution_budget_never_starts_motion(robot_http, expiry_at):
    now = [0.0]
    engine = ProtocolEngine(robot_http.url, robot_http.profile, sila_probe=lambda: None)
    request = engine._request
    health_checks = 0
    authority_checks = 0

    def slow_request(method, path, **kwargs):
        nonlocal health_checks
        result = request(method, path, **kwargs)
        if path == "/health":
            health_checks += 1
        if (
            expiry_at == "analysis"
            and path.endswith("/analyses/analysis-1")
            or expiry_at == "preflight"
            and path == "/health"
            and health_checks == 3
            or expiry_at == "create"
            and method == "POST"
            and path == "/runs"
        ):
            now[0] = 61
        return result

    def authority():
        nonlocal authority_checks
        authority_checks += 1
        if expiry_at == "authority" and authority_checks == 3:
            now[0] = 61
        return False

    engine._request = slow_request
    plan = plan_for()
    kwargs = dict(
        approve=lambda: True,
        phase=lambda *args, **kwargs: None,
        stop_requested=authority,
        timeout_seconds=60,
        poll_seconds=0,
        clock=lambda: now[0],
    )
    try:
        if expiry_at in {"analysis", "preflight"}:
            with pytest.raises(TimeoutError, match="deadline"):
                engine.execute(
                    compile_plan(plan, workflow_digest(plan), robot_http.profile), **kwargs
                )
            assert robot_http.run_number == 0
            assert actions(robot_http) == []
        else:
            result = engine.execute(
                compile_plan(plan, workflow_digest(plan), robot_http.profile), **kwargs
            )
            assert result["outcome"] == "unknown" and result["stop_confirmed"]
            assert actions(robot_http) == [("/runs/robot-run-1/actions", "stop")]
    finally:
        engine.close()


@pytest.mark.parametrize("stop_acknowledged", [False, True])
def test_running_deadline_uses_one_bounded_stop(robot_http, stop_acknowledged):
    now = [0.0]
    robot_http.hold_running = True
    engine = ProtocolEngine(robot_http.url, robot_http.profile, sila_probe=lambda: None)
    request = engine._request

    def stop_request(method, path, **kwargs):
        result = request(method, path, **kwargs)
        if (
            not stop_acknowledged
            and kwargs.get("json", {}).get("data", {}).get("actionType") == "stop"
        ):
            robot_http.status = "running"
        return result

    def tick(_seconds):
        now[0] += 31

    engine._request = stop_request
    plan = plan_for()
    kwargs = dict(
        approve=lambda: True,
        phase=lambda *args, **kwargs: None,
        stop_requested=lambda: False,
        timeout_seconds=30,
        poll_seconds=0,
        clock=lambda: now[0],
        sleep=tick,
    )
    try:
        if stop_acknowledged:
            result = engine.execute(
                compile_plan(plan, workflow_digest(plan), robot_http.profile), **kwargs
            )
            assert result["outcome"] == "unknown" and result["stop_confirmed"]
        else:
            with pytest.raises(TimeoutError, match="Bound stop"):
                engine.execute(
                    compile_plan(plan, workflow_digest(plan), robot_http.profile), **kwargs
                )
        assert actions(robot_http) == [
            ("/runs/robot-run-1/actions", "play"),
            ("/runs/robot-run-1/actions", "stop"),
        ]
    finally:
        engine.close()


@pytest.mark.parametrize("age", [-3600, -1, 301, 3600])
def test_qualification_rejects_future_or_stale_probe_without_writes(
    qualification_context, monkeypatch, age
):
    module, service, _, _, device, _, args = qualification_context
    connection = service.raw("alice", device["id"])
    connection["probe"]["observed_at"] = module.time.time() - age
    service.store.put("alice", f"connection#{device['id']}", connection, connection["version"])
    with pytest.raises(SystemExit) as error:
        invoke(module, monkeypatch, *args, "--apply", "--confirm-supervised-qualification")
    assert error.value.code == 2
    assert service.store.get(module.QUALIFICATIONS, device["id"]) is None


@pytest.mark.parametrize("missing", ["fingerprint", "file", "both", "mismatch"])
def test_tls_config_requires_certificate_and_exact_fingerprint(tmp_path, missing):
    cfg = config(profile_for(), "http://127.0.0.1:31950").model_dump(mode="json")
    certificate = tmp_path / "certificate.pem"
    certificate.write_bytes(b"software fixture certificate")
    certificate.chmod(0o600)
    cfg["profile"]["sila_tls"] = True
    cfg["profile"]["sila_certificate_sha256"] = hashlib.sha256(certificate.read_bytes()).hexdigest()
    cfg["sila_certificate_file"] = str(certificate)
    assert LocalConfig.model_validate(cfg).sila_certificate_file == str(certificate)
    if missing in {"fingerprint", "both"}:
        cfg["profile"]["sila_certificate_sha256"] = None
    if missing in {"file", "both"}:
        cfg["sila_certificate_file"] = None
    if missing == "mismatch":
        cfg["profile"]["sila_certificate_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="certificate"):
        LocalConfig.model_validate(cfg)


@pytest.fixture
def pairing_cli(tmp_path, monkeypatch):
    import academy.companion.__main__ as entry

    state = private_directory(tmp_path / "state")
    old = credentials()
    write_private(state / "credentials.json", old.model_dump(mode="json"))
    cfg = config(profile_for(), "http://127.0.0.1:31950")
    config_path = state / "config.json"
    write_private(config_path, cfg.model_dump(mode="json"))
    code_path = state / "code.txt"
    code_path.write_text("fixture-code")
    code_path.chmod(0o600)
    monkeypatch.setattr(
        entry, "ProtocolEngine", lambda *a, **kw: SimpleNamespace(close=lambda: None)
    )
    args = [
        "--state-dir",
        str(state),
        "pair",
        "--config",
        str(config_path),
        "--code-file",
        str(code_path),
    ]
    return entry, state, old, args


def test_explicit_rotation_archives_revoked_secret_and_new_pair_is_recoverable(
    pairing_cli, monkeypatch
):
    entry, state, old, args = pairing_cli
    paired = []

    def handle(request):
        if request.url.path == "/companion/me":
            if paired and request.headers["Authorization"].startswith(
                f"Bearer {paired[0]['installation_id']}."
            ):
                return httpx.Response(200, json={"paired": True})
            return httpx.Response(403, json={"detail": "revoked"})
        paired.append(json.loads(request.content))
        raise httpx.ReadTimeout("Pair response lost after acceptance", request=request)

    monkeypatch.setattr(
        entry,
        "AcademyClient",
        lambda cfg, creds: AcademyClient(cfg, creds, transport=httpx.MockTransport(handle)),
    )
    with pytest.raises(httpx.ReadTimeout):
        entry.main([*args, "--rotate-credentials"])
    replacement = json.loads(read_private(state / "credentials.json"))
    assert replacement["installation_id"] != str(old.installation_id)
    assert replacement["secret"] != old.secret
    assert json.loads(
        read_private(state / f"credentials-{old.installation_id}.json")
    ) == old.model_dump(mode="json")
    assert paired[0]["installation_id"] == replacement["installation_id"]
    assert entry.main(args) == 0
    assert len(paired) == 1
    assert json.loads(read_private(state / "credentials.json")) == replacement


@pytest.mark.parametrize("authority", ["timeout", "503", "active"])
def test_rotation_does_not_replace_credentials_without_confirmed_rejection(
    pairing_cli, monkeypatch, authority
):
    entry, state, old, args = pairing_cli

    def handle(request):
        assert request.url.path == "/companion/me"
        if authority == "timeout":
            raise httpx.ReadTimeout("uncertain authority", request=request)
        return httpx.Response(200 if authority == "active" else 503, json={})

    monkeypatch.setattr(
        entry,
        "AcademyClient",
        lambda cfg, creds: AcademyClient(cfg, creds, transport=httpx.MockTransport(handle)),
    )
    with pytest.raises((httpx.HTTPError, RuntimeError)):
        entry.main([*args, "--rotate-credentials"])
    assert json.loads(read_private(state / "credentials.json")) == old.model_dump(mode="json")
    assert not list(state.glob("credentials-*.json"))


def test_rotation_cannot_bypass_unresolved_work(pairing_cli, monkeypatch):
    entry, state, old, args = pairing_cli
    with Journal(state) as journal:
        journal.begin(command_for(profile_for(), old))
    monkeypatch.setattr(
        entry,
        "AcademyClient",
        lambda cfg, creds: AcademyClient(
            cfg, creds, transport=httpx.MockTransport(lambda request: httpx.Response(403, json={}))
        ),
    )
    with pytest.raises(RuntimeError, match="Reconcile"):
        entry.main([*args, "--rotate-credentials"])
    assert json.loads(read_private(state / "credentials.json")) == old.model_dump(mode="json")
    assert not list(state.glob("credentials-*.json"))
