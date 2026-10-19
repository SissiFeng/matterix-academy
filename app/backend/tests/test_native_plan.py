"""Learner-plan translation and scene preflight. Capabilities here are synthetic fixtures."""

from uuid import uuid4

import pytest
from academy.models import Experiment
from academy.native_plan import TransferCapability, intent_for, preflight
from academy.runs import QUEUE, RunService, SubmitRun
from academy.worker_admin import QUALIFICATION_CHECKS, qualification_changes
from fastapi import HTTPException
from pydantic import ValidationError
from test_dispatch import FIXTURE_CAPABILITY, saved, worker
from test_learning import lesson

NARROW = dict(
    FIXTURE_CAPABILITY,
    slots={"tips": ["B1"], "stock": ["D1"], "plate": ["D2"], "waste": ["D3"]},
    volume_ul={"min": 50, "max": 100},
)


def test_intent_preserves_learner_values_and_logical_labware():
    experiment = Experiment.model_validate(lesson(volume=50))
    intent = intent_for(experiment)
    assert intent.labware == experiment.layout
    assert [(s.kind, s.labware, s.well, s.volume_ul) for s in intent.steps] == [
        ("pickup", "tips", None, None),
        ("aspirate", "stock", None, 50),
        ("dispense", "plate", "A1", 50),
        ("drop", "waste", None, None),
    ]
    assert intent.initial_volume_ul["stock"] == experiment.source_volume
    assert intent.initial_volume_ul["A1"] == 0


def test_preflight_reports_every_mismatch_without_adjusting_values():
    data = lesson(volume=200)
    data["layout"] = {"stock": "A1", "plate": "D2", "tips": "B1", "waste": "D3"}
    intent = intent_for(Experiment.model_validate(data))
    issues = preflight(intent, TransferCapability.model_validate(NARROW))
    assert {(i.code, i.step) for i in issues} == {("slot", None), ("volume", 1), ("volume", 2)}
    assert intent.steps[1].volume_ul == 200
    assert preflight(intent, TransferCapability.model_validate(FIXTURE_CAPABILITY)) == []


def test_capability_requires_every_logical_labware():
    with pytest.raises(ValidationError):
        TransferCapability.model_validate(dict(FIXTURE_CAPABILITY, slots={"tips": ["B1"]}))


def test_submit_rejects_plan_no_scene_supports(store):
    service = RunService(store, enabled=True)
    session = saved(store)
    request = SubmitRun(
        run_id=uuid4(), session_id=session["id"], expected_version=session["version"]
    )
    with pytest.raises(HTTPException) as error:
        service.submit("alice", request)
    assert error.value.status_code == 503
    worker(store, capabilities={"flex-first-transfer": dict(NARROW, wells=["A2"])})
    with pytest.raises(HTTPException) as error:
        service.submit("alice", request)
    assert error.value.status_code == 422
    assert error.value.detail["issues"][0]["code"] == "well"
    assert store.partition(QUEUE) == []


def test_claim_skips_scene_that_cannot_run_plan(store):
    service = RunService(store, enabled=True)
    worker(store)
    worker(store, "narrow", capabilities={"flex-first-transfer": dict(NARROW, wells=["A2"])})
    worker(store, "undeclared", capabilities={})
    session = saved(store)
    request = SubmitRun(
        run_id=uuid4(), session_id=session["id"], expected_version=session["version"]
    )
    service.submit("alice", request)
    assert service.claim("narrow") is None
    assert service.claim("undeclared") is None
    assert service.claim("lab-1")["run_id"] == str(request.run_id)


def evidence(**changes):
    record = {
        "evidence": "native",
        "checks": {name: True for name in QUALIFICATION_CHECKS},
        "worker_id": "lab-1",
        "engine_version": "e",
        "asset_version": "a",
        "report_uri": "s3://fixture/report.json",
        "scenes": ["flex-first-transfer"],
        "capabilities": {"flex-first-transfer": FIXTURE_CAPABILITY},
    }
    record.update(changes)
    return record


def test_qualification_requires_explicit_scenes_and_capabilities():
    old = {"worker_id": "lab-1", "engine_version": "e", "asset_version": "a"}
    granted = qualification_changes(old, evidence())
    assert granted["capabilities"]["flex-first-transfer"]["wells"] == ["A1", "A2", "A3"]
    for bad in (evidence(scenes=None), evidence(capabilities={}), evidence(checks={})):
        with pytest.raises(ValueError):
            qualification_changes(old, bad)
