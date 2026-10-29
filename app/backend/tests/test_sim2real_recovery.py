"""Regression tests for crash, race and authority edge cases of the sim-to-real control plane."""

import pytest
from academy.broker import CommandBroker, Held
from academy.external import issue_orchestrator
from academy.instruments import INSTRUMENTS
from academy.pairing import PAIR_RUNS
from academy.worker_api import create_worker_app
from fastapi.testclient import TestClient
from labtwin.models import Evidence, Fact, Observation, Outcome, Status
from labtwin.wire import plain
from tests.sim2real_support import approve, create, observation, read


def expire_lease(store):
    record = store.get(INSTRUMENTS, "flex-a")
    lease = {**record["lease"], "expires": 0}
    store.put(
        INSTRUMENTS,
        "flex-a",
        {**record, "lease": lease, "version": record["version"] + 1},
        record["version"],
    )


def machine_pairing(lab):
    return lab.machine.app.state.pairing


def test_an_expired_lease_stops_the_old_run_instead_of_sharing_the_device(lab):
    a = approve(lab, create(lab, "real_only"))
    lab.gateway.poll()  # A's inspect delivered
    expire_lease(lab.store)
    b = approve(lab, create(lab, "real_only"))
    lab.pump(120)
    executed = lab.device.executed
    assert len(executed) == len(set(executed)) == 3
    a, b = read(lab, a["run_id"]), read(lab, b["run_id"])
    assert a["status"] == "failed" and "lease" in a["reason"]
    assert b["status"] == "completed"


def test_disabling_physical_execution_stops_an_approved_run(lab):
    run = approve(lab, create(lab, "real_only"))
    off = TestClient(
        create_worker_app(
            lab.store,
            runtime="local",
            enabled=False,
            pairing_enabled=True,
            real_enabled=False,
            poll_wait=0,
        )
    )
    lab.gateway.client = off
    lab.pump(60)
    run = read(lab, run["run_id"])
    assert run["status"] == "failed" and "disabled" in run["reason"]
    assert lab.device.executed == []


def test_a_crash_before_recording_a_failed_step_still_leaves_the_device_held(lab):
    lab.device.fail_step = "01-pickup"
    run = approve(lab, create(lab, "real_only"))
    pairing = machine_pairing(lab)
    original = pairing.broker.hold
    crashed = []

    def crashing(target, reason):
        if "physical step" in reason.lower() and not crashed:
            crashed.append(reason)
            raise RuntimeError("lambda crashed")
        return original(target, reason)

    pairing.broker.hold = crashing
    with pytest.raises(RuntimeError):
        lab.pump(60)  # the API crashed while settling the failed step
    pairing.broker.hold = original
    assert crashed
    pairing.reap()
    lab.pump(60)
    run = read(lab, run["run_id"])
    assert run["status"] == "failed"
    assert lab.api.get("/api/instruments/flex-a").json()["gateway"]["fault"]


def test_a_stop_racing_the_real_dispatch_keeps_the_dispatched_step_accounted_for(lab):
    run = approve(lab, create(lab, "sim_first"))
    pairing = machine_pairing(lab)
    original = pairing.broker.enqueue

    def racing(target, kind, payload=None, **kwargs):
        out = original(target, kind, payload, **kwargs)
        if (
            kind == "execute"
            and target.startswith("device:")
            and not getattr(racing, "done", False)
        ):
            racing.done = True
            record = lab.store.get(PAIR_RUNS, run["run_id"])
            lab.store.put(
                PAIR_RUNS,
                run["run_id"],
                {**record, "stop_requested": True, "version": record["version"] + 1},
                record["version"],
            )
        return out

    pairing.broker.enqueue = racing
    lab.pump(120)
    record = lab.store.get(PAIR_RUNS, run["run_id"])
    assert lab.device.executed == ["01-pickup"]
    assert record["steps"][0]["real"]["status"] == "succeeded"
    assert record["status"] == "cancelled" and record["released"]


def test_an_interrupted_queueing_is_repeated_once_by_the_reaper(lab):
    run = approve(lab, create(lab, "real_only"))
    pairing = machine_pairing(lab)
    original = pairing.broker.enqueue

    def crash_once(target, kind, payload=None, **kwargs):
        if kind == "begin" and not getattr(crash_once, "done", False):
            crash_once.done = True
            raise RuntimeError("lambda crashed after persisting the intent")
        return original(target, kind, payload, **kwargs)

    pairing.broker.enqueue = crash_once
    lab.pump(10)  # the settlement handler crashed; the run awaits a command never queued
    pairing.broker.enqueue = original
    assert lab.device.executed == []
    pairing.repair(run["run_id"], grace_s=0)
    lab.pump(60)
    assert read(lab, run["run_id"])["status"] == "completed"
    assert lab.device.executed == ["01-pickup", "02-drop", "03-park"]


def test_the_twin_prediction_is_held_when_the_device_changed_before_dispatch(lab):
    original = lab.device.__call__

    def drifting(kind, payload):
        if kind == "snapshot" and str(payload).startswith("pre-02"):
            return observation(Evidence.HARDWARE, False)  # someone removed the tip by hand
        return original(kind, payload)

    lab.gateway.model = drifting
    run = approve(lab, create(lab, "sim_first"))
    lab.pump(120)
    run = read(lab, run["run_id"])
    assert run["status"] == "sim_rejected" and "Starting state" in run["reason"]
    assert lab.device.executed == ["01-pickup"]


def test_validation_cannot_change_while_a_run_controls_the_instrument(lab):
    run = approve(lab, create(lab, "real_only"))
    reply = lab.api.put(
        "/api/instruments/flex-a/validation", json={"expected_version": 1, "tolerances": {"x": 1}}
    )
    assert reply.status_code == 409
    lab.pump(60)
    assert read(lab, run["run_id"])["status"] == "completed"


def test_failed_connector_inspection_is_a_clean_failure(lab):
    def unreachable(kind, payload):
        if kind == "inspect":
            raise ConnectionError("connector unreachable")
        return {"ok": True}

    lab.gateway.model = unreachable
    run = approve(lab, create(lab, "real_only"))
    lab.pump(30)
    run = read(lab, run["run_id"])
    assert run["status"] == "failed" and "nothing was dispatched" in run["reason"]


def test_stop_is_recorded_even_when_a_worker_is_offline(lab):
    run = approve(lab, create(lab, "paired"))
    target = lab.store.get("system#targets", "sim:sim-1")
    lab.store.put(
        "system#targets",
        "sim:sim-1",
        {**target, "seen_at": 0, "version": target["version"] + 1},
        target["version"],
    )
    fresh = read(lab, run["run_id"])
    reply = lab.api.post(
        f"/api/pair-runs/{run['run_id']}/stop", json={"expected_version": fresh["version"]}
    )
    assert reply.status_code == 200 and reply.json()["stop_requested"]


def test_external_failure_reports_hold_the_instrument(lab):
    token, _ = issue_orchestrator(lab.store, "orch-2", instruments=["flex-a"])
    headers = {"Authorization": f"Bearer {token}"}
    lab.machine.post(
        "/external/v1/instruments/flex-a/lease", json={"seconds": 600}, headers=headers
    )
    start = observation(Evidence.HARDWARE, False)
    lab.machine.post(
        "/external/v1/instruments/flex-a/predictions",
        json={
            "prediction_id": "pred-fail-1",
            "operation_id": "01-pickup",
            "start_observation": start,
        },
        headers=headers,
    )
    lab.pump()
    op = lab.machine.get("/external/v1/predictions/pred-fail-1", headers=headers).json()["steps"][
        0
    ]["operation"]
    lab.machine.post(
        "/external/v1/predictions/pred-fail-1/claim",
        json={"operation": op, "current_observation": start},
        headers=headers,
    )
    failed = plain(
        Outcome(
            Status.FAILED,
            Observation("o", {"pipette.tip_attached": Fact(False, Evidence.HARDWARE)}),
            "jam",
        )
    )
    assert (
        lab.machine.post(
            "/external/v1/predictions/pred-fail-1/outcome",
            json={"outcome": failed},
            headers=headers,
        ).status_code
        == 200
    )
    assert lab.api.get("/api/instruments/flex-a").json()["gateway"]["fault"]


def test_fencing_holds_before_settling_and_a_retry_cannot_lose_the_hold(store):
    now = [1000.0]
    broker = CommandBroker(store, clock=lambda: now[0])
    session = broker.register("device:x", credential=["g", 1], instance="instance-A")["session"]
    first = broker.enqueue("device:x", "execute", {"a": 1}, ttl=170)
    broker.enqueue("device:x", "execute", {"a": 2}, ttl=170)
    assert broker.exchange("device:x", session, seq=1)["command"]["id"] == first["command_id"]
    now[0] += 40
    original = broker._terminal

    def racing(command, state, result=None, **kwargs):
        raise RuntimeError("crash while fencing")

    broker._terminal = racing
    with pytest.raises(RuntimeError):
        broker.register("device:x", credential=["g", 1], instance="instance-B")
    broker._terminal = original
    assert broker.target("device:x")["fault"]  # held before any fencing transition
    broker.register("device:x", credential=["g", 1], instance="instance-B")
    assert broker.target("device:x")["fault"]


def test_a_stale_inspection_cannot_clear_a_newer_hold(store):
    now = [1000.0]
    broker = CommandBroker(store, clock=lambda: now[0])
    session = broker.register("device:x", credential=["g", 1], instance="instance-A")["session"]
    broker.hold("device:x", "F1")
    now[0] += 1
    inspect = broker.enqueue("device:x", "inspect", ttl=30)
    broker.exchange("device:x", session, seq=1)
    broker.exchange(
        "device:x",
        session,
        seq=2,
        results=[{"id": inspect["command_id"], "value": {}, "error": ""}],
    )
    assert broker.target("device:x")["inspected"]
    broker.enqueue("device:x", "reconcile", {"note": "x"}, ttl=30)
    broker.exchange("device:x", session, seq=3)  # delivered; result lost
    now[0] += 36
    broker.reap()  # unknown: the hold is re-armed, the old inspection no longer counts
    assert not broker.target("device:x")["inspected"]
    with pytest.raises(Held):
        broker.clear_hold("device:x")


def test_resuming_requires_the_same_credential(store):
    broker = CommandBroker(store)
    broker.register("device:x", credential=["old", 1], instance="instance-A")
    with pytest.raises(Exception, match="already online"):
        broker.register("device:x", credential=["new", 1], instance="instance-A")


def test_a_failing_settlement_handler_does_not_hide_other_expiries(store):
    now = [1000.0]
    seen = []

    def handler(command):
        seen.append(command["command_id"])
        if len(seen) == 1:
            raise RuntimeError("handler bug")

    broker = CommandBroker(store, clock=lambda: now[0], on_settled=handler)
    broker.register("device:x", credential=["g", 1], instance="instance-A")
    broker.enqueue("device:x", "snapshot", "a", ttl=5)
    broker.enqueue("device:x", "snapshot", "b", ttl=5)
    now[0] += 10
    assert broker.reap() == 2 and len(seen) == 2


def test_leaked_simulation_reservations_are_released(lab):
    pairing = machine_pairing(lab)
    pairing.broker.reserve("sim:sim-1", "run:does-not-exist")
    pairing.reap()
    assert pairing.broker.status("sim:sim-1")["reservation"] is None


def test_repair_never_queues_a_physical_step_for_a_failed_run(lab):
    from academy.broker import Offline

    run = approve(lab, create(lab, "paired"))
    pairing = machine_pairing(lab)
    original = pairing.broker.enqueue

    def sim_offline(target, kind, payload=None, **kwargs):
        if kind == "execute" and target.startswith("sim:"):
            raise Offline("sim offline")
        return original(target, kind, payload, **kwargs)

    pairing.broker.enqueue = sim_offline
    lab.pump(60)
    pairing.broker.enqueue = original
    pairing.repair(run["run_id"], grace_s=0)
    lab.pump(60)
    record = lab.store.get(PAIR_RUNS, run["run_id"])
    assert record["status"] == "failed" and lab.device.executed == []
    assert not any(e["kind"] == "execute" for e in record["waiting"].values())


def test_repair_reapplies_the_physical_gates(lab):
    run = approve(lab, create(lab, "real_only"))
    pairing = machine_pairing(lab)
    original = pairing.broker.enqueue

    def crash(target, kind, payload=None, **kwargs):
        if kind == "execute":
            raise RuntimeError("lambda crashed after persisting intent")
        return original(target, kind, payload, **kwargs)

    pairing.broker.enqueue = crash
    lab.pump(60)
    pairing.broker.enqueue = original
    pairing.real_enabled = False  # an operator switched physical execution off meanwhile
    pairing.repair(run["run_id"], grace_s=0)
    lab.pump(30)
    assert lab.device.executed == []
    assert read(lab, run["run_id"])["status"] == "failed"


def test_a_crash_between_approval_and_start_is_restarted_by_repair(lab):
    pairing = machine_pairing(lab)
    run = create(lab, "real_only")
    original = pairing.__class__._start
    record = lab.store.get(PAIR_RUNS, run["run_id"])
    approved = {
        **record,
        "status": "queued",
        "approval": {"by": "op", "at": 0, "confirmation": {}},
        "version": record["version"] + 1,
    }
    lab.store.put(PAIR_RUNS, run["run_id"], approved, record["version"])
    pairing.instruments.acquire("flex-a", f"run:{run['run_id']}", seconds=600, kind="run")
    pairing.repair(run["run_id"], grace_s=0)
    lab.pump(60)
    assert read(lab, run["run_id"])["status"] == "completed"
    assert original is pairing.__class__._start
