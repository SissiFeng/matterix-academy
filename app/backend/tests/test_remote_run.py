from copy import deepcopy
from uuid import uuid4

import httpx
import pytest
from academy.gateway import GatewayUnavailable, MatterixGateway, RemoteOutcomeUnknown
from academy.models import Experiment
from academy.remote_run import (
    RemoteRunRequest,
    RemoteRunSnapshot,
    check_run_snapshot,
    workflow_digest,
)
from pydantic import ValidationError


def plan():
    experiment = Experiment()
    return RemoteRunRequest(
        run_id=uuid4(),
        expected_revision=1,
        experiment=experiment,
        plan_hash=workflow_digest(experiment),
    )


def report(session_id, request, completed=0, sequence=0):
    timestamp = "2026-10-01T14:00:00Z"
    return {
        "session_id": str(session_id),
        "run_id": str(request.run_id),
        "plan_hash": request.plan_hash,
        "sequence": sequence,
        "session_revision": 2,
        "engine": "matterix",
        "evidence": "native",
        "simulation_only": True,
        "engine_version": "fixture-engine",
        "asset_version": "fixture-assets",
        "status": "completed" if completed == len(request.experiment.actions) else "running",
        "observed_at": timestamp,
        "steps": [
            {
                "index": i,
                "status": "completed",
                "completed_at": timestamp,
                "observation_revision": 2,
            }
            if i < completed
            else {"index": i, "status": "pending"}
            for i in range(len(request.experiment.actions))
        ],
        "native_state": {
            "revision": 2,
            "observed_at": timestamp,
            "simulation_tick": 100,
            "pipette_volume_ul": None,
            "tip_attached": None,
            "well_volumes_ul": {"stock": None, "A1": None, "A2": None, "A3": None},
        },
    }


def test_plan_binds_action_order_layout_and_starting_liquids():
    request = plan()
    for key, value in [
        ("source_volume", 1200),
        ("layout", {**request.experiment.layout, "tips": "C1"}),
        ("actions", request.experiment.actions[1:] + request.experiment.actions[:1]),
    ]:
        changed = request.model_dump()
        changed["experiment"][key] = value
        with pytest.raises(ValidationError):
            RemoteRunRequest.model_validate(changed)
    assert (
        workflow_digest(Experiment.model_validate(request.experiment.model_dump()))
        == request.plan_hash
    )


def test_whole_workflow_progress_is_reported_not_inferred_from_acceptance_or_time():
    session_id, request = uuid4(), plan()
    body = report(session_id, request)
    body.update(status="loading", native_state=None)
    waiting = RemoteRunSnapshot.model_validate(body)
    assert waiting.progress_percent == 0
    first = RemoteRunSnapshot.model_validate(report(session_id, request, completed=1, sequence=1))
    check_run_snapshot(first, session_id, request, waiting)
    assert first.completed_steps == 1
    assert first.progress_percent == pytest.approx(100 / 12)
    assert first.native_state.well_volumes_ul["A1"] is None
    done = RemoteRunSnapshot.model_validate(report(session_id, request, completed=12, sequence=2))
    check_run_snapshot(done, session_id, request, first)
    assert done.progress_percent == 100


@pytest.mark.parametrize(
    "case",
    [
        "no_observation",
        "old_observation",
        "missing_confirmation",
        "future_confirmation",
        "out_of_order_step",
        "premature_completion",
        "wrong_engine",
        "synthetic",
        "nan_volume",
        "negative_volume",
        "missing_well",
    ],
)
def test_invalid_native_progress_cannot_become_confirmed_completion(case):
    request = plan()
    body = report(uuid4(), request, completed=1, sequence=1)
    if case == "no_observation":
        body["native_state"] = None
    if case == "old_observation":
        body["native_state"]["revision"] = 1
    if case == "missing_confirmation":
        body["steps"][0].pop("completed_at")
    if case == "future_confirmation":
        body["steps"][0]["completed_at"] = "2026-10-01T15:00:00Z"
    if case == "out_of_order_step":
        body["steps"][1] = {**body["steps"][0], "index": 1}
        body["steps"][0] = {"index": 0, "status": "pending"}
    if case == "premature_completion":
        body["status"] = "completed"
    if case == "wrong_engine":
        body["engine"] = "teaching"
    if case == "synthetic":
        body["evidence"] = "synthetic"
    if case == "nan_volume":
        body["native_state"]["well_volumes_ul"]["A1"] = float("nan")
    if case == "negative_volume":
        body["native_state"]["well_volumes_ul"]["A1"] = -1
    if case == "missing_well":
        body["native_state"]["well_volumes_ul"].pop("A1")
    with pytest.raises(ValidationError):
        RemoteRunSnapshot.model_validate(body)


@pytest.mark.parametrize(
    "case",
    [
        "session",
        "run",
        "hash",
        "step_count",
        "stale",
        "duplicate_changed",
        "retract",
        "engine_version",
    ],
)
def test_progress_reconciliation_rejects_mismatched_and_regressed_reports(case):
    session_id, request = uuid4(), plan()
    previous = RemoteRunSnapshot.model_validate(
        report(session_id, request, completed=1, sequence=2)
    )
    body = report(session_id, request, completed=1, sequence=3)
    if case == "session":
        body["session_id"] = str(uuid4())
    if case == "run":
        body["run_id"] = str(uuid4())
    if case == "hash":
        body["plan_hash"] = "0" * 64
    if case == "step_count":
        body["steps"].pop()
    if case == "stale":
        body["sequence"] = 1
    if case == "duplicate_changed":
        body.update(sequence=2, status="paused")
    if case == "retract":
        body["steps"][0] = {"index": 0, "status": "pending"}
    if case == "engine_version":
        body["engine_version"] = "changed-engine"
    with pytest.raises(ValueError):
        check_run_snapshot(RemoteRunSnapshot.model_validate(body), session_id, request, previous)
    check_run_snapshot(previous, session_id, request, previous)


def test_a_lost_run_acknowledgement_recovers_without_restarting_the_workflow():
    import json

    session_id, request = uuid4(), plan()
    requests = []

    def handler(http_request):
        requests.append(http_request)
        if http_request.method == "POST":
            assert json.loads(http_request.content) == request.model_dump(mode="json")
            raise httpx.ReadTimeout("Run started but acknowledgement was lost")
        assert http_request.url.path == f"/v1/sessions/{session_id}/runs/{request.run_id}"
        return httpx.Response(200, json=report(session_id, request, completed=2, sequence=4))

    gateway = MatterixGateway("https://gateway.example", "secret", httpx.MockTransport(handler))
    with pytest.raises(RemoteOutcomeUnknown):
        gateway.start_run(session_id, request)
    assert gateway.run_snapshot(session_id, request).completed_steps == 2
    assert [r.method for r in requests] == ["POST", "GET"]
    gateway.close()


def test_wrong_plan_acknowledgement_is_unknown_and_wrong_lookup_is_unavailable():
    session_id, request = uuid4(), plan()
    body = report(session_id, request)
    body["plan_hash"] = "f" * 64
    gateway = MatterixGateway(
        "https://gateway.example",
        "secret",
        httpx.MockTransport(lambda _: httpx.Response(200, json=deepcopy(body))),
    )
    with pytest.raises(RemoteOutcomeUnknown):
        gateway.start_run(session_id, request)
    with pytest.raises(GatewayUnavailable):
        gateway.run_snapshot(session_id, request)
    gateway.close()


def test_pause_waits_for_confirmation_and_a_terminal_run_cannot_advance():
    session_id, request = uuid4(), plan()
    body = report(session_id, request, completed=1, sequence=1)
    body["steps"][1]["status"] = "running"
    body["status"] = "pause_requested"
    assert RemoteRunSnapshot.model_validate(body).status == "pause_requested"
    body["status"] = "paused"
    with pytest.raises(ValidationError):
        RemoteRunSnapshot.model_validate(body)
    body["status"] = "failed"
    body["error"] = "Runtime stopped"
    body["steps"][1]["status"] = "failed"
    failed = RemoteRunSnapshot.model_validate(body)
    later = report(session_id, request, completed=2, sequence=2)
    later.update(status="failed", error="Runtime stopped")
    with pytest.raises(ValueError):
        check_run_snapshot(RemoteRunSnapshot.model_validate(later), session_id, request, failed)


def test_new_progress_cannot_replace_a_newer_native_observation_with_an_older_one():
    session_id, request = uuid4(), plan()
    previous_body = report(session_id, request, completed=1, sequence=1)
    previous_body["session_revision"] = 3
    previous_body["native_state"]["revision"] = 3
    previous = RemoteRunSnapshot.model_validate(previous_body)
    next_body = report(session_id, request, completed=1, sequence=2)
    next_body["session_revision"] = 3
    with pytest.raises(ValueError):
        check_run_snapshot(
            RemoteRunSnapshot.model_validate(next_body), session_id, request, previous
        )


def test_same_native_revision_cannot_replace_confirmed_values():
    session_id, request = uuid4(), plan()
    body = report(session_id, request, completed=1, sequence=1)
    body["native_state"]["pipette_volume_ul"] = 0
    previous = RemoteRunSnapshot.model_validate(body)
    body["sequence"] = 2
    body["native_state"]["pipette_volume_ul"] = 200
    with pytest.raises(ValueError):
        check_run_snapshot(RemoteRunSnapshot.model_validate(body), session_id, request, previous)
    body["native_state"]["revision"] = 3
    body["session_revision"] = 3
    check_run_snapshot(RemoteRunSnapshot.model_validate(body), session_id, request, previous)


@pytest.mark.parametrize("field", ["completed_at", "observation_revision"])
def test_ordered_actions_cannot_have_reversed_completion_evidence(field):
    session_id, request = uuid4(), plan()
    body = report(session_id, request, completed=2, sequence=1)
    body["steps"][1][field] = "2026-10-01T13:59:00Z" if field == "completed_at" else 1
    with pytest.raises(ValidationError):
        RemoteRunSnapshot.model_validate(body)


@pytest.mark.parametrize("status", ["completed", "failed", "unknown"])
@pytest.mark.parametrize("change", ["native_state", "sequence", "status"])
def test_terminal_native_evidence_is_frozen_including_unknown(status, change):
    session_id, request = uuid4(), plan()
    body = report(session_id, request, completed=len(request.experiment.actions), sequence=1)
    body.update(status=status, error="Synthetic stopped outcome" if status == "failed" else None)
    previous = RemoteRunSnapshot.model_validate(body)
    check_run_snapshot(previous, session_id, request, previous)
    body["sequence"] += 1
    if change == "native_state":
        body["session_revision"] += 1
        body["native_state"]["revision"] += 1
        body["native_state"]["pipette_volume_ul"] = 100
    elif change == "status":
        body["status"] = "running" if status == "unknown" else "unknown"
    with pytest.raises(ValueError, match="immutable"):
        check_run_snapshot(RemoteRunSnapshot.model_validate(body), session_id, request, previous)
