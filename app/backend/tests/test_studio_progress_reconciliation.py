"""Synthetic contract fixtures; these do not establish native GPU acceptance."""

from copy import deepcopy
from uuid import uuid4

import pytest
from academy.models import Action, Experiment
from academy.remote_run import (
    RemoteRunRequest,
    RemoteRunSnapshot,
    check_run_snapshot,
    workflow_digest,
)
from test_remote_run import report


def observations(completed=1):
    experiment = Experiment(
        course_id="workflow-sandbox",
        instrument="flex",
        source_volume=1000,
        diluent_volume=0,
        actions=[
            Action(kind="pickup"),
            Action(kind="aspirate", well="stock", volume=100),
            Action(kind="dispense", well="A1", volume=100),
            Action(kind="drop"),
        ],
    )
    session_id = uuid4()
    request = RemoteRunRequest(
        run_id=uuid4(),
        expected_revision=1,
        experiment=experiment,
        plan_hash=workflow_digest(experiment),
    )
    body = report(session_id, request, completed=completed, sequence=1)
    body["native_state"].update(
        tip_attached=bool(completed),
        pipette_volume_ul=40 if completed else 0,
        well_volumes_ul={"stock": 960 if completed else 1000, "A1": 0, "A2": 0, "A3": 0},
        studio={
            "instrument": "flex",
            "scene": "workflow-studio-flex",
            "observation_model": "native-semantic",
            "labware_slots": experiment.layout,
            "waste_volume_ul": 0,
            "native_action_index": 6 if completed else 2,
            "native_action_count": 21,
            "native_action": "Aspirating stock" if completed else "Approaching tip",
        },
    )
    previous = RemoteRunSnapshot.model_validate(body)
    newer = deepcopy(body)
    newer.update(sequence=2, session_revision=3, observed_at="2026-10-01T14:00:01Z")
    newer["native_state"].update(
        revision=3, simulation_tick=110, observed_at="2026-10-01T14:00:01Z"
    )
    return session_id, request, previous, newer


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("native_action_index", 5, "progress cannot move backward"),
        ("native_action_count", 20, "workflow identity cannot change"),
        ("native_action_count", 22, "workflow identity cannot change"),
    ],
)
def test_newer_studio_observation_cannot_rewind_or_redefine_native_workflow(field, value, message):
    session_id, request, previous, body = observations()
    body["native_state"]["studio"][field] = value
    newer = RemoteRunSnapshot.model_validate(body)
    # Both are valid standalone observations of the same confirmed prefix.
    # Reconciliation must additionally preserve the native execution history.
    check_run_snapshot(previous, session_id, request)
    check_run_snapshot(newer, session_id, request)
    with pytest.raises(ValueError, match=message):
        check_run_snapshot(newer, session_id, request, previous)


@pytest.mark.parametrize("index", [6, 7])
def test_newer_studio_observation_can_wait_or_advance_with_fixed_action_count(index):
    session_id, request, previous, body = observations()
    body["native_state"]["studio"]["native_action_index"] = index
    check_run_snapshot(previous, session_id, request, previous)
    check_run_snapshot(RemoteRunSnapshot.model_validate(body), session_id, request, previous)


def test_studio_motion_evidence_cannot_disappear_on_failure_before_first_confirmed_step():
    session_id, request, previous, body = observations(completed=0)
    body.update(status="failed", error="Runtime stopped before pickup completed")
    body["native_state"]["studio"] = None
    newer = RemoteRunSnapshot.model_validate(body)
    check_run_snapshot(newer, session_id, request)
    with pytest.raises(ValueError, match="workflow identity cannot change"):
        check_run_snapshot(newer, session_id, request, previous)
