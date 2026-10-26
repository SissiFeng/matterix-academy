"""Sim-to-real coordination through one machine API with two worker classes.

Fake workers below implement the protocol-2 agent contract (ack, durable
outbox, same-ID redelivery) without a device or GPU. They prove control-plane
semantics only; physical and native acceptance remain separate.
"""

import copy
import json
import secrets

import pytest
from academy.broker import CommandBroker, Held, Offline
from academy.external import issue_orchestrator
from academy.instruments import InstrumentService
from academy.lab_admin import link_device
from academy.main import create_app
from academy.pairing import PAIR_RUNS
from academy.runs import WORKERS, revised
from academy.settings import Settings
from academy.worker_admin import enroll, qualification_changes
from academy.worker_api import create_worker_app
from fastapi.testclient import TestClient
from labtwin import workflows
from labtwin.models import Evidence, Fact, Observation, Outcome, Status
from labtwin.wire import plain

SECRET = "test-secret-that-is-at-least-32-characters"


def flex_profile():
    profile = workflows.profile_template("opentrons_flex")
    profile["device_id"] = "flex-a"
    profile["real"].update(
        server_uuid="flex-uuid",
        pipette_id="P1",
        pipette_model="p1000_single",
        calibration_revision="cal-1",
        tiprack="rack",
        tip_length_mm=58.0,
        pickup={"x": 10.0, "y": 20.0, "z": 5.0},
        pickup_clearance={"x": 10.0, "y": 20.0, "z": 100.0},
        drop={"x": 300.0, "y": 20.0, "z": 50.0},
        drop_clearance={"x": 300.0, "y": 20.0, "z": 100.0},
        park={"x": 200.0, "y": 200.0, "z": 100.0},
    )
    return profile


def obs(evidence, tip, x=200.0, source="flex-sila"):
    return Observation(
        source,
        {
            "pipette.tip_attached": Fact(tip, evidence),
            "position.x": Fact(x, evidence, "mm", "flex.deck.LEFT"),
        },
        "r",
        "t",
    )


def observation(*args, **kwargs):
    return plain(obs(*args, **kwargs))


class DeviceModel:
    """Fake physical side of the gateway executor (connector + local ledger)."""

    def __init__(self, fail_step=None, x_offset=0.0):
        self.tip, self.fail_step, self.x_offset = False, fail_step, x_offset
        self.executed, self.plan = [], None

    def __call__(self, kind, payload):
        if kind == "inspect":
            return {"server_uuid": "flex-uuid", "is_simulating": False}
        if kind == "begin":
            workflows.validate_plan(payload)
            self.plan = payload
            return {"ready": True}
        if kind == "snapshot":
            return observation(Evidence.HARDWARE, self.tip, 200.0 + self.x_offset)
        if kind == "execute":
            self.executed.append(payload["operation_id"])
            if payload["operation_id"] == self.fail_step:
                return plain(Outcome(Status.FAILED, error="Unexpected tip state"))
            self.tip = payload["action"] == "pick_up_tip"
            return plain(
                Outcome(Status.SUCCEEDED, obs(Evidence.HARDWARE, self.tip, 200.0 + self.x_offset))
            )
        if kind in {"finish", "stop", "reconcile"}:
            self.plan = None
            return {"closed": True}
        raise ValueError(kind)


class SimModel:
    def __init__(self, reject_step=None):
        self.tip, self.reject_step, self.begins, self.executed = False, reject_step, [], []

    def __call__(self, kind, payload):
        if kind == "inspect":
            return {"simulation_only": True, "engine_version": "eng-1", "asset_version": "ast-1"}
        if kind == "begin":
            assert set(payload) == {"plan", "seed", "corrections", "start_operation_id"}
            self.begins.append(payload)
            return {
                "ready": True,
                "simulation_only": True,
                "seed_applied": payload["seed"] is not None,
            }
        if kind == "snapshot":
            return observation(Evidence.SIMULATED, self.tip, source="matterix")
        if kind == "execute":
            self.executed.append(payload["operation_id"])
            if payload["operation_id"] == self.reject_step:
                return plain(
                    Outcome(
                        Status.FAILED,
                        obs(Evidence.SIMULATED, self.tip, source="matterix"),
                        "collision predicted",
                    )
                )
            self.tip = payload["action"] == "pick_up_tip"
            return plain(
                Outcome(Status.SUCCEEDED, obs(Evidence.SIMULATED, self.tip, source="matterix"))
            )
        if kind in {"finish", "stop", "reconcile"}:
            return {"closed": True}
        raise ValueError(kind)


class FakeAgent:
    """Protocol-2 agent: acks, durable outbox, same-ID dedupe. One command per poll."""

    def __init__(self, client, prefix, token, identity, model):
        self.client, self.prefix, self.model = client, prefix, model
        self.headers = {"Authorization": f"Bearer {token}"}
        self.identity, self.instance = identity, secrets.token_urlsafe(12)
        self.session, self.seq, self.acks, self.outbox, self.ledger = None, 0, [], {}, {}

    def post(self, action, body):
        return self.client.post(f"{self.prefix}/{action}", json=body, headers=self.headers)

    def register(self):
        reply = self.post(
            "register",
            {
                **self.identity,
                "instance": self.instance,
                "protocol": 2,
                "results": list(self.outbox.values()),
            },
        )
        assert reply.status_code == 200, reply.text
        body = reply.json()
        for cid in body["confirmed"]:
            self.outbox.pop(cid, None)
        self.session, self.seq = body["session"], 0
        return body

    def poll(self, *, lose_response=False):
        self.seq += 1
        reply = self.post(
            "poll",
            {
                "session": self.session,
                "seq": self.seq,
                "acks": self.acks,
                "results": list(self.outbox.values())[:8],
            },
        )
        assert reply.status_code == 200, reply.text
        body = reply.json()
        self.acks = []
        for cid in body["confirmed"]:
            self.outbox.pop(cid, None)
        command = body.get("command")
        if command is None or lose_response:
            return command
        self.acks.append(command["id"])
        if command["id"] not in self.ledger:  # never execute an ID twice
            try:
                result = {
                    "id": command["id"],
                    "value": self.model(command["kind"], command["payload"]),
                    "error": "",
                }
            except Exception as exc:
                result = {
                    "id": command["id"],
                    "value": None,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            self.ledger[command["id"]] = result
            self.outbox[command["id"]] = result
        return command

    def drain(self, limit=60):
        idle = 0
        for _ in range(limit):
            if self.poll() is None and not self.outbox:
                idle += 1
                if idle >= 2:
                    return
            else:
                idle = 0


@pytest.fixture
def lab(store, tmp_path):
    settings = Settings(
        allow_demo=True,
        secret=SECRET,
        data_path=str(tmp_path / "unused.sqlite"),
        pairing_enabled=True,
        real_enabled=True,
        local_operator=True,
    )
    learner_settings = Settings(
        allow_demo=True,
        secret=SECRET,
        data_path=str(tmp_path / "unused.sqlite"),
        pairing_enabled=True,
        real_enabled=True,
    )
    api = TestClient(create_app(settings, store=store))
    assert api.post("/api/auth/guest", json={"name": "Op"}).status_code == 200
    second = TestClient(create_app(settings, store=store))
    assert second.post("/api/auth/guest", json={"name": "Op2"}).status_code == 200
    learner = TestClient(create_app(learner_settings, store=store))
    assert learner.post("/api/auth/guest", json={"name": "Lea"}).status_code == 200
    machine = TestClient(
        create_worker_app(
            store,
            runtime="local",
            enabled=False,
            pairing_enabled=True,
            real_enabled=True,
            poll_wait=0,
        )
    )
    instruments = InstrumentService(store)
    instruments.register("flex-a", "Flex A", flex_profile())
    gateway_token, _ = instruments.issue_gateway("flex-a", "flex-a-mac")
    enroll(store, "sim-1", "eng-1", "ast-1", tmp_path / "sim.token")
    sim_token = (tmp_path / "sim.token").read_text().strip()
    worker = store.get(WORKERS, "sim-1")
    evidence = {
        "evidence": "native",
        "worker_id": "sim-1",
        "engine_version": "eng-1",
        "asset_version": "ast-1",
        "report_uri": "s3://evidence/sim-1.json",
        "checks": {
            k: True
            for k in (
                "session_isolation",
                "plan_binding",
                "at_most_once",
                "native_observations",
                "reset_verification",
                "release",
                "restart_recovery",
                "no_hardware",
            )
        },
        "scenes": [],
        "pair_models": ["opentrons_flex"],
        "pair_protocol_verified": True,
    }
    store.put(
        WORKERS,
        "sim-1",
        revised(worker, **qualification_changes(worker, evidence)),
        worker["version"],
    )
    device, sim = DeviceModel(), SimModel()
    gateway = FakeAgent(
        machine, "/internal/gateway", gateway_token, {"profile": flex_profile()}, device
    )
    simulator = FakeAgent(
        machine,
        "/internal/sim",
        sim_token,
        {"runtime": {"simulation_only": True, "engine_version": "eng-1", "asset_version": "ast-1"}},
        sim,
    )
    gateway.register()
    simulator.register()

    class Lab:
        pass

    lab = Lab()
    lab.__dict__.update(
        store=store,
        api=api,
        second=second,
        learner=learner,
        machine=machine,
        gateway=gateway,
        simulator=simulator,
        device=device,
        sim=sim,
        gateway_token=gateway_token,
        sim_token=sim_token,
    )

    def pump(rounds=30):
        idle = 0
        for _ in range(rounds):
            g = gateway.poll()
            s = simulator.poll()
            idle = (
                idle + 1
                if g is None and s is None and not gateway.outbox and not simulator.outbox
                else 0
            )
            if idle >= 2:
                break

    lab.pump = pump
    return lab


def confirm():
    return {
        "deck_matches_plan": True,
        "workspace_clear": True,
        "emergency_stop_reachable": True,
        "note": "Deck checked against plan",
    }


def create(lab, mode, run_id=None, client=None, **extra):
    run_id = run_id or secrets.token_hex(8)
    reply = (client or lab.api).post(
        "/api/pair-runs", json={"run_id": run_id, "instrument_id": "flex-a", "mode": mode, **extra}
    )
    assert reply.status_code == 201, reply.text
    return reply.json()


def approve(lab, run):
    reply = lab.api.post(
        f"/api/pair-runs/{run['run_id']}/approve",
        json={"expected_version": run["version"], "confirmation": confirm()},
    )
    assert reply.status_code == 200, reply.text
    return reply.json()


def read(lab, run_id):
    return lab.api.get(f"/api/pair-runs/{run_id}").json()


def test_sim_only_run_completes_with_simulation_evidence_only(lab):
    run = create(lab, "sim_only")
    assert run["status"] == "running"
    lab.pump()
    run = read(lab, run["run_id"])
    assert run["status"] == "completed", run["reason"]
    assert lab.device.executed == [] and lab.sim.executed == ["01-pickup", "02-drop", "03-park"]
    assert all(
        s["sim"]["observation"]["facts"]["position.x"]["evidence"] == "simulated"
        for s in run["steps"]
    )
    assert lab.store.partition("system#pairs", "flex-a#") == []  # no physical evidence fabricated


def test_real_run_requires_operator_approval_and_physical_confirmation(lab):
    run = create(lab, "real_only")
    assert run["status"] == "awaiting_approval"
    lab.pump()
    assert lab.device.executed == []
    reply = lab.learner.post(
        f"/api/pair-runs/{run['run_id']}/approve",
        json={"expected_version": run["version"], "confirmation": confirm()},
    )
    assert reply.status_code == 403
    bad = {**confirm(), "workspace_clear": False}
    reply = lab.api.post(
        f"/api/pair-runs/{run['run_id']}/approve",
        json={"expected_version": run["version"], "confirmation": bad},
    )
    assert reply.status_code == 422
    approve(lab, run)
    lab.pump()
    run = read(lab, run["run_id"])
    assert run["status"] == "completed", run["reason"]
    assert lab.device.executed == ["01-pickup", "02-drop", "03-park"]
    assert run["approval"]["confirmation"]["note"] == "Deck checked against plan"
    instrument = lab.api.get("/api/instruments/flex-a").json()
    assert instrument["lease_holder"] is None


def test_sim_first_dispatches_each_real_step_only_after_its_receipt(lab):
    run = approve(lab, create(lab, "sim_first"))
    order = []
    original_device, original_sim = lab.device.__call__, lab.sim.__call__

    def tracking(name, inner):
        def call(kind, payload):
            if kind == "execute":
                order.append((name, payload["operation_id"]))
            return inner(kind, payload)

        return call

    lab.gateway.model = tracking("real", original_device)
    lab.simulator.model = tracking("sim", original_sim)
    lab.pump(60)
    run = read(lab, run["run_id"])
    assert run["status"] == "completed", run["reason"]
    assert order == [
        ("sim", "01-pickup"),
        ("real", "01-pickup"),
        ("sim", "02-drop"),
        ("real", "02-drop"),
        ("sim", "03-park"),
        ("real", "03-park"),
    ]
    assert all(s["gate"] == "passed" and s["receipt"]["consumed"] for s in run["steps"])
    # The twin was seeded with the real initial observation.
    assert lab.sim.begins[0]["seed"]["source"] == "flex-sila"
    rows = lab.api.get("/api/instruments/flex-a/dataset").json()
    assert (
        rows["summary"]["paired"] == 4 and rows["summary"]["status_agree"] == 4
    )  # initial + 3 steps


def test_twin_rejection_holds_the_real_step(lab):
    lab.sim.reject_step = "02-drop"
    run = approve(lab, create(lab, "sim_first"))
    lab.pump(60)
    run = read(lab, run["run_id"])
    assert run["status"] == "sim_rejected"
    assert lab.device.executed == ["01-pickup"]  # 02-drop never reached the device
    assert run["steps"][1]["gate"] == "held" and run["steps"][1]["real"] is None
    assert lab.device.plan is None  # the device run was finished cleanly
    assert not lab.api.get("/api/instruments/flex-a").json()["gateway"]["fault"]


def test_paired_divergence_and_comparison_units(lab):
    lab.device.x_offset = 2.0
    lab.api.put(
        "/api/instruments/flex-a/validation",
        json={"expected_version": 1, "tolerances": {"position.x": 0.5, "pipette.tip_attached": 0}},
    )
    run = approve(lab, create(lab, "paired"))
    lab.pump(60)
    run = read(lab, run["run_id"])
    assert run["status"] == "diverged"
    comparison = {c["field"]: c["status"] for c in run["steps"][0]["comparisons"]}
    assert comparison == {"position.x": "different", "pipette.tip_attached": "match"}


def test_failed_physical_step_holds_until_reconciled(lab):
    lab.device.fail_step = "02-drop"
    run = approve(lab, create(lab, "real_only"))
    lab.pump(60)
    run = read(lab, run["run_id"])
    assert run["status"] == "failed" and "held" in run["reason"]
    instrument = lab.api.get("/api/instruments/flex-a").json()
    assert instrument["gateway"]["fault"]
    second = create(lab, "real_only")
    reply = lab.api.post(
        f"/api/pair-runs/{second['run_id']}/approve",
        json={"expected_version": second["version"], "confirmation": confirm()},
    )
    assert reply.status_code == 409 and "held" in reply.json()["detail"]
    assert (
        lab.api.post(
            "/api/instruments/flex-a/reconcile",
            json={"note": "Tip removed by hand, deck inspected"},
        ).status_code
        == 200
    )
    lab.pump()
    instrument = lab.api.get("/api/instruments/flex-a").json()
    assert instrument["gateway"]["fault"] == ""
    assert lab.store.partition("system#instrument-reconciliations", "device:flex-a#")[0][
        "note"
    ].startswith("Tip removed")


def test_lost_poll_response_is_redelivered_with_the_same_id_and_runs_once(lab):
    run = approve(lab, create(lab, "real_only"))
    lost = lab.gateway.poll(lose_response=True)  # inspect delivered, response lost
    assert lost["kind"] == "inspect"
    again = lab.gateway.poll()
    assert again["id"] == lost["id"]
    lab.pump(60)
    assert read(lab, run["run_id"])["status"] == "completed"
    assert lab.device.executed == ["01-pickup", "02-drop", "03-park"]
    assert lab.api.get("/api/instruments/flex-a").json()["gateway"]["redeliveries"] >= 1


def test_gateway_restart_mid_command_is_unknown_and_holds(lab):
    run = approve(lab, create(lab, "real_only"))
    lab.gateway.poll()  # inspect
    lab.gateway.poll()  # inspect result in; begin delivered
    command = lab.gateway.poll(lose_response=True)  # a command is in flight on the old process
    assert command is not None
    # The old process stops polling; after the online window a new process registers.
    target = lab.store.get("system#targets", "device:flex-a")
    lab.store.put(
        "system#targets",
        "device:flex-a",
        {**target, "seen_at": 0, "version": target["version"] + 1},
        target["version"],
    )
    restarted = FakeAgent(
        lab.machine, "/internal/gateway", lab.gateway_token, {"profile": flex_profile()}, lab.device
    )
    restarted.register()
    run = read(lab, run["run_id"])
    assert run["status"] == "outcome_unknown"
    assert lab.api.get("/api/instruments/flex-a").json()["gateway"]["fault"]


def test_worker_classes_cannot_use_each_others_routes(lab):
    sim_headers = {"Authorization": f"Bearer {lab.sim_token}"}
    gw_headers = {"Authorization": f"Bearer {lab.gateway_token}"}
    body = {"profile": flex_profile(), "instance": "instance-123", "protocol": 2}
    reply = lab.machine.post("/internal/gateway/register", json=body, headers=sim_headers)
    assert reply.status_code == 403 and reply.json()["code"] == "credential"
    reply = lab.machine.post(
        "/internal/sim/register",
        json={"instance": "instance-123", "protocol": 2, "runtime": {}},
        headers=gw_headers,
    )
    assert reply.status_code == 403
    assert lab.machine.post("/internal/runs/claim", headers=gw_headers).status_code == 403
    # A gateway presenting a substituted profile is refused.
    changed = flex_profile()
    changed["real"]["tip_length_mm"] = 60.0
    reply = lab.machine.post(
        "/internal/gateway/register", json={**body, "profile": changed}, headers=gw_headers
    )
    assert reply.status_code == 409 or reply.json()["code"] in {"invalid", "conflict"}


def test_authorizers_are_class_specific(lab, monkeypatch):
    from academy import worker_api

    monkeypatch.setattr(worker_api, "machine_store", lambda: lab.store)
    event = lambda token: {"headers": {"authorization": f"Bearer {token}"}}  # noqa: E731
    assert (
        worker_api.authorize(event(lab.sim_token), None)["context"]["worker_class"] == "simulation"
    )
    assert worker_api.authorize(event(lab.gateway_token), None) == {"isAuthorized": False}
    assert (
        worker_api.authorize_gateway(event(lab.gateway_token), None)["context"]["worker_class"]
        == "device"
    )
    assert worker_api.authorize_gateway(event(lab.sim_token), None) == {"isAuthorized": False}
    assert worker_api.authorize_orchestrator(event(lab.gateway_token), None) == {
        "isAuthorized": False
    }


def test_learner_needs_a_linked_device_and_never_controls_hardware(lab):
    reply = lab.learner.post(
        "/api/pair-runs",
        json={"run_id": "learner-run-1", "instrument_id": "flex-a", "mode": "sim_only"},
    )
    assert reply.status_code == 403
    me = lab.learner.get("/api/me")
    assert me.status_code == 200
    device_id = "6d0f4f43-58a7-4a39-8f7e-3e6a7f2a1c11"
    saved = lab.learner.put(
        f"/api/devices/{device_id}",
        json={
            "expected_version": 0,
            "name": "Flex A",
            "workcell": "Bench 1",
            "connection": "sila2",
            "capabilities": ["pickup"],
            "stage": 3,
        },
    )
    assert saved.status_code == 200
    owner = [k for k in _owners(lab.store) if lab.store.get(k, f"device#{device_id}")][0]
    link_device(lab.store, owner, device_id, "flex-a")
    run = create(lab, "real_only", client=lab.learner)
    assert run["status"] == "awaiting_approval" and run["requested_as"] == "learner"
    assert (
        lab.learner.post(
            f"/api/pair-runs/{run['run_id']}/approve",
            json={"expected_version": run["version"], "confirmation": confirm()},
        ).status_code
        == 403
    )
    approve(lab, run)
    lab.pump(60)
    detail = lab.learner.get(f"/api/devices/{device_id}").json()
    checks = {c["id"]: c["status"] for c in detail["checks"] if c["scope"] == "physical"}
    assert checks["authorization"] == "passed" and checks["connection"] == "passed"
    assert detail["instrument_id"] == "flex-a"
    assert lab.learner.get(f"/api/devices/{device_id}/pair-runs").json()[0]["status"] == "completed"
    # Server-owned link cannot be set or removed by the learner's declaration.
    resaved = lab.learner.put(
        f"/api/devices/{device_id}",
        json={
            "expected_version": detail["version"],
            "name": "Flex A2",
            "workcell": "Bench 1",
            "connection": "sila2",
            "capabilities": ["pickup"],
            "stage": 3,
        },
    )
    assert resaved.json()["instrument_id"] == "flex-a"


def _owners(store):
    if hasattr(store, "connection"):
        with store.connection() as db:
            return [
                row[0]
                for row in db.execute("SELECT DISTINCT owner FROM records WHERE id LIKE 'device#%'")
            ]
    return list(
        {item["pk"] for item in store.table.scan()["Items"] if item["sk"].startswith("device#")}
    )


def test_rehearsal_must_match_workflow_and_profile(lab):
    lab.api.put(
        "/api/instruments/flex-a/validation",
        json={"expected_version": 1, "require_rehearsal": True},
    )
    reply = lab.api.post(
        "/api/pair-runs",
        json={"run_id": "real-without-rehearsal", "instrument_id": "flex-a", "mode": "real_only"},
    )
    assert reply.status_code == 409
    rehearsal = create(lab, "sim_only")
    lab.pump()
    assert read(lab, rehearsal["run_id"])["status"] == "completed"
    run = approve(lab, create(lab, "real_only", rehearsal_run_id=rehearsal["run_id"]))
    lab.pump(60)
    assert read(lab, run["run_id"])["status"] == "completed"
    rows = lab.api.get("/api/instruments/flex-a/dataset").json()["rows"]
    assert {r["sim_source"] for r in rows if r["operation_id"] != "initial"} == {"rehearsal"}


def test_external_orchestrator_lease_predict_claim_and_report(lab, tmp_path):
    token, _ = issue_orchestrator(lab.store, "lab-orch", instruments=["flex-a"])
    headers = {"Authorization": f"Bearer {token}"}
    assert (
        lab.machine.post(
            "/external/v1/instruments/flex-a/lease", json={"seconds": 600}, headers=headers
        ).status_code
        == 200
    )
    # A Lab Onboarding real run cannot be approved while the external lease is held.
    run = create(lab, "real_only")
    reply = lab.api.post(
        f"/api/pair-runs/{run['run_id']}/approve",
        json={"expected_version": run["version"], "confirmation": confirm()},
    )
    assert reply.status_code == 409
    start = observation(Evidence.HARDWARE, False)
    reply = lab.machine.post(
        "/external/v1/instruments/flex-a/predictions",
        json={
            "prediction_id": "pred-0001",
            "operation_id": "01-pickup",
            "start_observation": start,
        },
        headers=headers,
    )
    assert reply.status_code == 201, reply.text
    lab.pump()
    prediction = lab.machine.get("/external/v1/predictions/pred-0001", headers=headers).json()
    assert prediction["status"] == "completed" and prediction["steps"][0]["gate"] == "passed"
    op = prediction["steps"][0]["operation"]
    changed = observation(Evidence.HARDWARE, True)
    assert (
        lab.machine.post(
            "/external/v1/predictions/pred-0001/claim",
            json={"operation": op, "current_observation": changed},
            headers=headers,
        ).status_code
        == 409
    )
    # A rejected claim consumes the receipt: a new prediction is required.
    assert (
        lab.machine.post(
            "/external/v1/predictions/pred-0001/claim",
            json={"operation": op, "current_observation": start},
            headers=headers,
        ).status_code
        == 409
    )
    lab.machine.post(
        "/external/v1/instruments/flex-a/predictions",
        json={
            "prediction_id": "pred-0002",
            "operation_id": "01-pickup",
            "start_observation": start,
        },
        headers=headers,
    )
    lab.pump()
    op = lab.machine.get("/external/v1/predictions/pred-0002", headers=headers).json()["steps"][0][
        "operation"
    ]
    claim = lab.machine.post(
        "/external/v1/predictions/pred-0002/claim",
        json={"operation": op, "current_observation": start},
        headers=headers,
    )
    assert claim.status_code == 200 and claim.json()["claimed"]
    real = plain(
        Outcome(
            Status.SUCCEEDED,
            Observation(
                "orchestrator", {"pipette.tip_attached": Fact(True, Evidence.HARDWARE)}, "x", "t"
            ),
        )
    )
    reported = lab.machine.post(
        "/external/v1/predictions/pred-0002/outcome", json={"outcome": real}, headers=headers
    )
    assert reported.status_code == 200
    rows = [
        r
        for r in lab.api.get("/api/instruments/flex-a/dataset").json()["rows"]
        if r["run_id"] == "pred-0002"
    ]
    assert any(r["real"] and r["real"]["reported_by"] == "external:lab-orch" for r in rows)
    assert lab.device.executed == []  # the gateway never acted for the external orchestrator


def test_calibration_revision_needs_evidence_and_a_second_operator(lab):
    lab.device.x_offset = 0.4
    lab.api.put(
        "/api/instruments/flex-a/validation",
        json={"expected_version": 1, "tolerances": {"position.x": 1.0}},
    )
    for _ in range(2):
        run = approve(lab, create(lab, "paired"))
        lab.pump(60)
        assert read(lab, run["run_id"])["status"] == "completed"
    proposal = lab.api.post(
        "/api/instruments/flex-a/calibrations", json={"revision_id": "cal-2", "min_samples": 3}
    )
    assert proposal.status_code == 201, proposal.text
    [offset] = [o for o in proposal.json()["corrections"] if o["field"] == "position.x"]
    assert offset["offset"] == pytest.approx(0.4)
    instrument = lab.api.get("/api/instruments/flex-a").json()
    profile = copy.deepcopy(instrument["profile"])
    profile["real"]["calibration_revision"] = "cal-2"
    body = {"expected_version": instrument["version"], "profile": profile}
    assert (
        lab.api.post("/api/instruments/flex-a/calibrations/cal-2/approve", json=body).status_code
        == 409
    )
    approved = lab.second.post("/api/instruments/flex-a/calibrations/cal-2/approve", json=body)
    assert approved.status_code == 200, approved.text
    assert approved.json()["calibration_revision"] == "cal-2"
    assert approved.json()["qualified_profile_sha256"] != instrument["qualified_profile_sha256"]
    # The old gateway profile no longer matches the qualified identity.
    stale = FakeAgent(
        lab.machine, "/internal/gateway", lab.gateway_token, {"profile": flex_profile()}, lab.device
    )
    reply = stale.post(
        "register",
        {"profile": flex_profile(), "instance": "instance-new", "protocol": 2, "results": []},
    )
    assert reply.status_code in {400, 409}
    # New runs carry the approved corrections to the twin.
    run = create(lab, "sim_only")
    lab.pump()
    assert read(lab, run["run_id"])["status"] == "completed"
    assert lab.sim.begins[-1]["corrections"] == proposal.json()["corrections"]
    assert lab.sim.begins[-1]["plan"]["profile"]["real"]["calibration_revision"] == "cal-2"


def test_broker_ttl_reaper_and_offline_refusal(store):
    now = [1000.0]
    broker = CommandBroker(store, clock=lambda: now[0])
    with pytest.raises(Offline):
        broker.enqueue("device:x", "inspect")
    registration = broker.register("device:x", credential=["g", 1], instance="instance-1")
    queued = broker.enqueue("device:x", "snapshot", "r", ttl=5)
    now[0] += 6
    assert broker.reap() == 1 and broker.command(queued["command_id"])["state"] == "not-dispatched"
    assert broker.target("device:x")["fault"] == ""  # never delivered: no hold
    sent = broker.enqueue("device:x", "execute", {"op": 1}, ttl=5)
    command = broker.exchange("device:x", registration["session"], seq=1)["command"]
    assert command["id"] == sent["command_id"]
    assert broker.exchange("device:x", registration["session"], seq=1)["stale"]
    now[0] += 20
    broker.reap()
    assert broker.command(sent["command_id"])["state"] == "unknown"
    assert "unknown" in broker.target("device:x")["fault"]
    with pytest.raises(Held):
        broker.enqueue("device:x", "execute", {"op": 2})
    stop = broker.enqueue("device:x", "stop")
    late = {"id": sent["command_id"], "value": {"status": "succeeded"}, "error": ""}
    reply = broker.exchange("device:x", registration["session"], seq=2, results=[late])
    assert reply["command"]["id"] == stop["command_id"]  # stop first
    assert broker.late_results("device:x")[0]["command_id"] == sent["command_id"]
    assert json.dumps(broker.status("device:x"))


def test_pair_run_records_are_system_scoped(lab):
    run = create(lab, "sim_only")
    lab.pump()
    record = lab.store.get(PAIR_RUNS, run["run_id"])
    assert record["requested_by"].startswith("local-")


def test_ot2_home_readback_never_compares_firmware_mm_with_joint_metres(lab):
    ot2 = workflows.profile_template("opentrons_ot2")
    ot2["device_id"] = "ot2-a"
    ot2["real"]["server_uuid"] = "ot2-uuid"
    instruments = InstrumentService(lab.store)
    instruments.register("ot2-a", "OT-2 A", ot2)
    token, _ = instruments.issue_gateway("ot2-a", "ot2-a-mac")
    worker = lab.store.get(WORKERS, "sim-1")
    lab.store.put(
        WORKERS,
        "sim-1",
        revised(worker, pair_models=["opentrons_flex", "opentrons_ot2"]),
        worker["version"],
    )

    def firmware(kind, payload):
        if kind == "inspect":
            return {"server_uuid": "ot2-uuid", "is_simulating": False}
        facts = {f"axis.{a}": Fact(0.0, Evidence.HARDWARE, "mm", "ot2.machine") for a in "XYZA"}
        if kind == "snapshot":
            return plain(Observation("ot2-firmware", facts, "r", "t"))
        if kind == "execute":
            return plain(Outcome(Status.SUCCEEDED, Observation("ot2-firmware", facts, "r", "t")))
        return {"ok": True}

    def native(kind, payload):
        facts = {
            f"joint.{i}": Fact(0.0, Evidence.SIMULATED, "m", "matterix.joint") for i in range(4)
        }
        if kind == "snapshot":
            return plain(Observation("matterix", facts, "r", "t"))
        if kind == "execute":
            return plain(Outcome(Status.SUCCEEDED, Observation("matterix", facts, "r", "t")))
        return {"ready": True}

    gateway = FakeAgent(lab.machine, "/internal/gateway", token, {"profile": ot2}, firmware)
    gateway.register()
    lab.simulator.model = native
    lab.api.put(
        "/api/instruments/ot2-a/validation",
        json={"expected_version": 1, "tolerances": {"axis.X": 0.5}},
    )
    reply = lab.api.post(
        "/api/pair-runs",
        json={"run_id": "ot2-paired-01", "instrument_id": "ot2-a", "mode": "paired"},
    )
    run = reply.json()
    run = lab.api.post(
        f"/api/pair-runs/{run['run_id']}/approve",
        json={"expected_version": run["version"], "confirmation": confirm()},
    ).json()
    for _ in range(30):
        gateway.poll()
        lab.simulator.poll()
    run = read(lab, "ot2-paired-01")
    assert run["status"] == "completed", run["reason"]
    assert [s["operation"]["action"] for s in run["steps"]] == ["home", "read_position"]
    assert {c["status"] for s in run["steps"] for c in s["comparisons"]} == {"unavailable"}
    rows = lab.api.get("/api/instruments/ot2-a/dataset").json()
    assert rows["summary"]["residuals"] == []
