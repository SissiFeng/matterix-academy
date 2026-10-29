"""Offline connector model. No transport, GPU, machine token or physical authority.

The browser uses this in-process adapter. The optional SiLA2 server exposes the
same model over actual loopback SiLA2; neither path imports a hardware driver.
"""

import time
from copy import deepcopy
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from .auth import identify
from .models import Experiment, StrictModel
from .remote_run import workflow_digest
from .store import Write
from .teaching import InvalidTransition, control, execute_step, new_session

PREFIX = "mock-connector-run#"
router = APIRouter(prefix="/api/connector-mock")


class CreateMockRun(StrictModel):
    run_id: UUID
    session_id: UUID
    expected_version: int = Field(ge=1, strict=True)


class MockCommand(StrictModel):
    expected_version: int = Field(ge=1, strict=True)
    command: Literal["step", "run", "reset"]


def initial_mock(plan: Experiment) -> dict:
    if plan.course_id != "workflow-sandbox" or not plan.actions:
        raise ValueError("Choose a saved Studio workflow with at least one action")
    simulation = new_session(plan)
    return {
        "engine": "mock-sila2",
        "evidence": "synthetic",
        "simulation_mode": True,
        "physical_execution": False,
        "simulation": simulation,
        "trace": [],
    }


def advance_mock(value: dict, command: str) -> dict:
    result = deepcopy(value)
    simulation = result["simulation"]
    if command == "reset":
        result["simulation"] = control(simulation, "reset")
        result["trace"] = []
        return result
    if simulation["status"] == "draft":
        simulation = control(simulation, "start")
    if simulation["status"] != "running":
        raise InvalidTransition("Reset the offline connector before running again")
    while simulation["status"] == "running":
        simulation = execute_step(simulation)
        result["trace"].append(
            {
                "step": simulation["cursor"],
                "status": simulation["status"],
                "state": deepcopy(simulation["state"]),
            }
        )
        if command == "step":
            break
    result["simulation"] = simulation
    return result


def run_mock(plan: Experiment) -> dict:
    """Same bounded model for the actual local SiLA command and the web adapter."""
    return advance_mock(initial_mock(plan), "run")


def get_run(store, owner, run_id):
    result = store.get(owner, PREFIX + str(run_id))
    if not result:
        raise HTTPException(404, "Offline connector run not found")
    return result


@router.post("/runs")
def create(data: CreateMockRun, request: Request, owner: str = Depends(identify)):
    store = request.app.state.store
    existing = store.get(owner, PREFIX + str(data.run_id))
    binding = {"session_id": str(data.session_id), "session_version": data.expected_version}
    if existing:
        if any(existing.get(k) != v for k, v in binding.items()):
            raise HTTPException(409, "This offline run ID belongs to another saved revision")
        return existing
    key = "session#" + str(data.session_id)
    session = store.get(owner, key)
    if not session:
        raise HTTPException(404, "Saved workflow not found")
    if session["version"] != data.expected_version:
        raise HTTPException(409, "Reload the saved workflow before starting the offline connector")
    try:
        plan = Experiment.model_validate(session["experiment"])
        value = initial_mock(plan)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    result = {
        **value,
        **binding,
        "run_id": str(data.run_id),
        "version": 1,
        "transport": "in-process-mock",
        "plan_hash": workflow_digest(plan),
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    # Atomic version check binds the snapshot without changing learner progress.
    store.transact(
        [
            Write(owner, key, session, data.expected_version),
            Write(owner, PREFIX + str(data.run_id), result, None),
        ]
    )
    return result


@router.get("/runs/{run_id}")
def get(run_id: UUID, request: Request, owner: str = Depends(identify)):
    return get_run(request.app.state.store, owner, run_id)


@router.post("/runs/{run_id}/commands")
def command(run_id: UUID, data: MockCommand, request: Request, owner: str = Depends(identify)):
    store = request.app.state.store
    old = get_run(store, owner, run_id)
    if old["version"] != data.expected_version:
        raise HTTPException(409, "Reload the offline run before issuing another command")
    result = advance_mock(old, data.command)
    result.update(version=old["version"] + 1, updated_at=time.time())
    store.put(owner, PREFIX + str(run_id), result, old["version"])
    return result
