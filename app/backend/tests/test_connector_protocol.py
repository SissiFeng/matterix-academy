"""Software-only qualification of compiler/HTTP transport. No physical or SiLA evidence."""

import ast
import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from academy.companion.compiler import compile_plan
from academy.companion.config import RobotProfile, digest
from academy.companion.protocol import ProtocolEngine, ProtocolError
from academy.models import Action, Experiment
from academy.remote_run import workflow_digest


def profile_for(instrument="flex"):
    def labware(name, slot, tips=False):
        definition = {
            "namespace": "qualification-fixture",
            "version": 1,
            "parameters": {"loadName": name, "isTiprack": tips},
            "wells": {well: {"totalLiquidVolume": 1500} for well in ("A1", "A2", "A3")},
        }
        return {
            "load_name": name,
            "namespace": definition["namespace"],
            "version": 1,
            "sha256": digest(definition),
            "definition": definition,
            "slot": slot,
        }

    return RobotProfile.model_validate(
        {
            "qualification_id": "SOFTWARE-FIXTURE-ONLY",
            "qualified_by": "fixture",
            "qualified_until": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "instrument": instrument,
            "serial": "SOFTWARE-TEST",
            "source_commit": "a" * 40,
            "release_id": "fixture-1",
            "artifact_sha256": "b" * 64,
            "runtime_contract_id": "fixture-runtime-v1",
            "runtime_release_id": "fixture-runtime-release-1",
            "runtime_bundle_sha256": "d" * 64,
            "connector_version": "fixture-1",
            "calibration_sha256": digest(
                {
                    "calibration": {"deckCalibration": {"status": "OK"}},
                    "labware_offsets": {"data": []},
                    "pipette_offsets": {"data": []},
                    "tip_lengths": {"data": []},
                }
            ),
            "sila_server_uuid": "c3157e30-a79a-4134-9241-7fcff27da160",
            "sila_features_sha256": digest({"features": ["fixture-feature"]}),
            "sila_tls": False,
            "firmware": "fixture-fw",
            "api_version": "fixture-api",
            "pipette_serial": "PIPETTE-TEST",
            "pipette_model": "flex_1channel_1000" if instrument == "flex" else "p300_single_gen2",
            "pipette_mount": "left",
            "min_volume_ul": 20,
            "max_volume_ul": 300,
            "labware": {
                "tips": labware("tips", "B1" if instrument == "flex" else "1", True),
                "stock": labware("reservoir", "D1" if instrument == "flex" else "2"),
                "plate": labware("plate", "D2" if instrument == "flex" else "3"),
            },
            "tip_wells": ["A1", "A2", "A3"],
            "stock_well": "A1",
            "capacity_ul": {"stock": 1500, "A1": 300, "A2": 300, "A3": 300},
            "calibration_confirmed": True,
            "deck_confirmed": True,
        }
    )


def plan_for(instrument="flex"):
    return Experiment(
        course_id="workflow-sandbox",
        instrument=instrument,
        layout={"tips": "B1", "stock": "D1", "plate": "D2", "waste": "D3"}
        if instrument == "flex"
        else {"tips": "1", "stock": "2", "plate": "3", "waste": "12"},
        diluent_volume=0,
        actions=[
            Action(kind="pickup"),
            Action(kind="aspirate", volume=100),
            Action(kind="dispense", well="A1", volume=100),
            Action(kind="drop"),
        ],
    )


class RobotFixture:
    def __init__(self):
        self.requests = []
        self.profile = profile_for()
        self.current = False
        self.status = "idle"
        self.action_types = ["pickUpTip", "aspirate", "dispense", "dropTip"]
        self.fail_play = False
        self.analysis_ok = True
        self.bad_serial = False
        self.hold_running = False
        self.redirect_health = False
        self.run_number = 0
        self.run_id = "robot-run-0"

    def response(self, method, path, body):
        if path == "/health":
            if self.redirect_health:
                return 302, {}, {"Location": "http://127.0.0.1:9/health"}
            return (
                200,
                {
                    "robot_model": "OT-3 Standard",
                    "robot_serial": "WRONG" if self.bad_serial else self.profile.serial,
                    "fw_version": self.profile.firmware,
                    "api_version": self.profile.api_version,
                    "minimum_protocol_api_version": [2, 15],
                    "maximum_protocol_api_version": [2, 20],
                },
                {},
            )
        if path == "/unitelabs/runtime":
            return (
                200,
                {
                    "runtimeContractId": self.profile.runtime_contract_id,
                    "connectorVersion": self.profile.connector_version,
                    "opentronsVersion": self.profile.api_version,
                    "releaseIdentity": {
                        "release_id": self.profile.runtime_release_id,
                        "bundle_sha256": self.profile.runtime_bundle_sha256,
                    },
                },
                {},
            )
        if path == "/calibration/status":
            return 200, {"deckCalibration": {"status": "OK"}}, {}
        if path in {"/labwareOffsets", "/calibration/pipette_offset", "/calibration/tip_length"}:
            return 200, {"data": []}, {}
        if path == "/pipettes":
            return (
                200,
                {"left": {"name": self.profile.pipette_model, "id": self.profile.pipette_serial}},
                {},
            )
        if path.startswith("/runs?"):
            return (
                200,
                {
                    "data": [{"id": "other", "current": True}] if self.current else [],
                    "meta": {"totalLength": 1 if self.current else 0},
                    "links": {"current": {"href": "/runs/other"} if self.current else None},
                },
                {},
            )
        if path == "/protocols":
            return 201, {"data": {"id": "protocol-1"}}, {}
        if path == "/protocols/protocol-1/analyses":
            return 200, {"data": [{"id": "analysis-1", "status": "completed"}]}, {}
        if path == "/protocols/protocol-1/analyses/analysis-1":
            return (
                200,
                {
                    "data": {
                        "id": "analysis-1",
                        "status": "completed",
                        "result": "ok" if self.analysis_ok else "not-ok",
                        "errors": [],
                    }
                },
                {},
            )
        if path == "/runs" and method == "POST":
            self.current = True
            self.status = "idle"
            self.run_number += 1
            self.run_id = f"robot-run-{self.run_number}"
            return 201, {"data": {"id": self.run_id}}, {}
        if path == f"/runs/{self.run_id}" and method == "PATCH":
            self.current = False
            return 200, {"data": {"id": self.run_id}}, {}
        if path == f"/runs/{self.run_id}":
            return (
                200,
                {
                    "data": {
                        "id": self.run_id,
                        "protocolId": "protocol-1",
                        "status": self.status,
                        "current": self.current,
                        "errors": [],
                    }
                },
                {},
            )
        if path == f"/runs/{self.run_id}/actions":
            action = json.loads(body)["data"]["actionType"]
            self.status = (
                "stopped" if action == "stop" else "running" if self.hold_running else "succeeded"
            )
            if self.fail_play:
                return 503, {"error": "response failed after mutation"}, {}
            return 201, {"data": {"actionType": action}}, {}
        if path.startswith(f"/runs/{self.run_id}/commands?"):
            commands = (
                []
                if self.status == "stopped"
                else [{"commandType": name, "status": "succeeded"} for name in self.action_types]
            )
            return 200, {"data": commands, "meta": {"cursor": 0, "totalLength": len(commands)}}, {}
        return 404, {}, {}


@pytest.fixture
def robot_http():
    robot = RobotFixture()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def handle_request(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            robot.requests.append(
                (self.command, self.path, body, self.headers.get("Opentrons-Version"))
            )
            status, payload, headers = robot.response(self.command, self.path, body)
            data = json.dumps(payload).encode()
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_PATCH = handle_request

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    robot.url = f"http://127.0.0.1:{server.server_port}"
    yield robot
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.mark.parametrize("instrument", ["flex", "ot2"])
def test_compiler_binds_slots_data_and_action_count(instrument):
    profile, plan = profile_for(instrument), plan_for(instrument)
    compiled = compile_plan(plan, workflow_digest(plan), profile)
    tree = ast.parse(compiled.source)
    assert compiled.action_count == 4
    assert not any(
        isinstance(node, ast.Attribute) and node.attr == "home" for node in ast.walk(tree)
    )
    assert workflow_digest(plan).encode() in compiled.source
    assert (b"load_waste_chute" in compiled.source) == (instrument == "flex")
    assert b"fixed_trash" in compiled.source if instrument == "ot2" else True


def test_arbitrary_title_is_not_executable():
    plan = plan_for()
    plan.title = '__import__("os").system("touch /tmp/never")'
    compiled = compile_plan(plan, workflow_digest(plan), profile_for())
    assert b"/tmp/never" not in compiled.source


@pytest.mark.parametrize(
    "case",
    ["hash", "layout", "capacity", "liquid", "tip", "end", "expiry", "pipette", "definition"],
)
def test_compiler_rejects_unqualified_or_invalid_plan(case):
    plan, profile = plan_for(), profile_for()
    if case == "hash":
        plan.title = "changed"
    elif case == "layout":
        plan.layout["tips"] = "C1"
    elif case == "capacity":
        plan.diluent_volume = 250
    elif case == "liquid":
        plan.source_volume = 20
    elif case == "tip":
        plan.actions.pop(0)
    elif case == "end":
        plan.actions.pop()
    elif case == "expiry":
        profile.qualified_until = datetime.now(UTC) - timedelta(seconds=1)
    elif case == "pipette":
        with pytest.raises(ValueError):
            RobotProfile.model_validate({**profile.model_dump(), "pipette_model": "arbitrary()"})
        return
    elif case == "definition":
        profile_data = profile.model_dump()
        profile_data["labware"]["plate"]["definition"]["version"] = 7
        with pytest.raises(ValueError, match="checksum"):
            RobotProfile.model_validate(profile_data)
        return
    with pytest.raises(ValueError):
        compile_plan(plan, "f" * 64 if case == "hash" else workflow_digest(plan), profile)


def execute(robot, **kwargs):
    plan = plan_for()
    engine = ProtocolEngine(robot.url, robot.profile, sila_probe=lambda: None)
    try:
        return engine.execute(
            compile_plan(plan, workflow_digest(plan), robot.profile),
            approve=kwargs.pop("approve", lambda: True),
            phase=lambda *a, **k: None,
            stop_requested=kwargs.pop("stop_requested", lambda: False),
            poll_seconds=0,
            **kwargs,
        )
    finally:
        engine.close()


def test_real_http_read_only_probe_and_full_execution(robot_http):
    engine = ProtocolEngine(robot_http.url, robot_http.profile, sila_probe=lambda: None)
    engine.probe()
    engine.close()
    assert all(method == "GET" for method, *_ in robot_http.requests)
    result = execute(robot_http)
    assert result["outcome"] == "completed"
    assert result["completed_actions"] == 4
    assert not robot_http.current
    assert all(header == "3" for *_, header in robot_http.requests)
    assert [
        json.loads(body)["data"]["actionType"]
        for method, path, body, _ in robot_http.requests
        if path.endswith("/actions")
    ] == ["play"]


def test_operator_decline_does_not_upload_or_move(robot_http):
    result = execute(robot_http, approve=lambda: False)
    assert result["outcome"] == "stopped" and result["stop_confirmed"]
    assert all(method == "GET" for method, *_ in robot_http.requests)


def test_identity_mismatch_does_not_mutate(robot_http):
    robot_http.bad_serial = True
    with pytest.raises(ProtocolError, match="identity"):
        execute(robot_http)
    assert all(method == "GET" for method, *_ in robot_http.requests)


def test_busy_robot_not_taken_over(robot_http):
    robot_http.current = True
    with pytest.raises(ProtocolError, match="current run"):
        execute(robot_http)
    assert all(method == "GET" for method, *_ in robot_http.requests)


def test_bad_analysis_never_creates_or_plays_run(robot_http):
    robot_http.analysis_ok = False
    with pytest.raises(ProtocolError, match="analysis rejected"):
        execute(robot_http)
    assert not any(
        path.endswith("/actions") or path == "/runs" for _, path, *_ in robot_http.requests
    )


def test_missing_command_evidence_never_reports_completion(robot_http):
    robot_http.action_types.pop()
    with pytest.raises(ProtocolError, match="action completion"):
        execute(robot_http)


def test_stop_only_current_bound_run(robot_http):
    robot_http.hold_running = True

    def should_stop():
        return robot_http.status == "running"

    result = execute(robot_http, stop_requested=should_stop)
    assert result["outcome"] == "stopped" and result["stop_confirmed"]
    actions = [
        (path, json.loads(body)["data"]["actionType"])
        for _, path, body, _ in robot_http.requests
        if path.endswith("/actions")
    ]
    assert actions == [("/runs/robot-run-1/actions", "play"), ("/runs/robot-run-1/actions", "stop")]


def test_redirect_not_followed(robot_http):
    import httpx

    robot_http.redirect_health = True
    with pytest.raises(httpx.HTTPStatusError):
        execute(robot_http)
    assert len(robot_http.requests) == 1


def test_saved_fixed_waste_is_never_substituted():
    plan = plan_for()
    plan.layout["waste"] = "C3"  # Deliberate in-memory bypass of the validated plan model.
    with pytest.raises(ValueError, match="fixed waste"):
        compile_plan(plan, workflow_digest(plan), profile_for())


def test_stock_robot_http_without_connector_runtime_is_rejected(robot_http):
    original = robot_http.response
    robot_http.response = lambda method, path, body: (
        (404, {}, {}) if path == "/unitelabs/runtime" else original(method, path, body)
    )
    import httpx

    with pytest.raises(httpx.HTTPStatusError):
        execute(robot_http)
    assert all(method == "GET" for method, *_ in robot_http.requests)


def test_changed_calibration_is_rejected_before_robot_mutation(robot_http):
    robot_http.profile.calibration_sha256 = "f" * 64
    with pytest.raises(ProtocolError, match="Calibration"):
        execute(robot_http)
    assert all(method == "GET" for method, *_ in robot_http.requests)


def test_sila_failure_is_not_ignored(robot_http):
    def reject():
        raise ValueError("SiLA identity mismatch")

    engine = ProtocolEngine(robot_http.url, robot_http.profile, sila_probe=reject)
    with pytest.raises(ValueError, match="SiLA identity"):
        engine.probe()
    engine.close()
    assert all(method == "GET" for method, *_ in robot_http.requests)


def test_large_history_uses_global_current_ownership_link(robot_http):
    original = robot_http.response

    def response(method, path, body):
        if path.startswith("/runs?"):
            return (
                200,
                {
                    "data": [{"id": f"old-{i}", "current": False} for i in range(100)],
                    "meta": {"totalLength": 5000},
                    "links": {"current": None},
                },
                {},
            )
        return original(method, path, body)

    robot_http.response = response
    engine = ProtocolEngine(robot_http.url, robot_http.profile, sila_probe=lambda: None)
    engine._assert_idle()
    engine.close()
    assert len(robot_http.requests) == 1
    assert robot_http.requests[0][1] == "/runs?pageLength=100"


def test_current_run_outside_latest_history_is_never_overlooked(robot_http):
    original = robot_http.response

    def response(method, path, body):
        if path.startswith("/runs?"):
            return (
                200,
                {
                    "data": [{"id": "recent", "current": False}],
                    "meta": {"totalLength": 5000},
                    "links": {"current": {"href": "/runs/older-current"}},
                },
                {},
            )
        return original(method, path, body)

    robot_http.response = response
    with pytest.raises(ProtocolError, match="current run"):
        execute(robot_http)
    assert all(method == "GET" for method, *_ in robot_http.requests)


def test_missing_current_ownership_link_fails_closed(robot_http):
    original = robot_http.response
    robot_http.response = lambda method, path, body: (
        (200, {"data": [], "meta": {"totalLength": 0}}, {})
        if path.startswith("/runs?")
        else original(method, path, body)
    )
    with pytest.raises(ProtocolError, match="ownership"):
        execute(robot_http)
