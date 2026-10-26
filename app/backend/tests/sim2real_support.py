"""Shared fakes for sim-to-real control-plane tests (no device, GPU or AWS)."""

import secrets

from academy.instruments import InstrumentService
from academy.main import create_app
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


def build_lab(store, tmp_path):
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
