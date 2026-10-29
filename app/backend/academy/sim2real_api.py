"""Learner/operator routes for instruments, sim-to-real runs, evidence and calibration.

Learners may request runs only on instruments an operator linked to one of
their device declarations; anything that can touch hardware waits for an
operator approval. Operators are Cognito group members (see ``auth.py``).
"""

from __future__ import annotations

import time
from typing import Literal

from fastapi import Depends, HTTPException, Request
from labtwin import workflows
from labtwin.dataset import propose_offsets, summarize
from pydantic import Field

from .auth import identify, identify_operator, operator_claims
from .instruments import device_target
from .models import StrictModel
from .pairing import (
    PAIR_RUNS,
    ApprovePairRun,
    CreatePairRun,
    RejectPairRun,
    StopPairRun,
    uses_real,
)
from .store import Conflict

CALIBRATIONS = "system#calibrations"


class ValidationConfig(StrictModel):
    expected_version: int = Field(ge=1)
    checks: dict[str, list[dict]] = Field(default_factory=dict)
    tolerances: dict[str, float] = Field(default_factory=dict)
    require_rehearsal: bool = False


class ReconcileRequest(StrictModel):
    note: str = Field(min_length=8, max_length=500)


class ProposeCalibration(StrictModel):
    revision_id: str = Field(pattern=r"^[A-Za-z0-9._-]{3,64}$")
    min_samples: int = Field(default=3, ge=1, le=1000)


class ApproveCalibration(StrictModel):
    expected_version: int = Field(ge=1)
    profile: dict
    decision: Literal["approve"] = "approve"


def physical_checks(pairing, instrument_id):
    """Derive the seven physical evidence gaps from real records only."""
    instrument = pairing.instruments.get(instrument_id)
    status = pairing.broker.status(device_target(instrument_id))
    runs = [r for r in pairing.list(instrument_id, limit=50) if uses_real(r["mode"])]
    completed = [r for r in runs if r["status"] == "completed"]
    profile = instrument["profile"]
    actions = [op["action"] for op in workflows.make_plan(profile, "evidence")["operations"]]
    latest_real = None
    for run in runs:
        for step in reversed(run["steps"]):
            if step.get("real") and step["real"].get("observation"):
                latest_real = step["real"]["observation"]
                break
        if latest_real is None and run["initial"].get("real"):
            latest_real = run["initial"]["real"]
        if latest_real:
            break
    compared = [c for r in completed for s in r["steps"] for c in s.get("comparisons", [])]

    def check(key, label, state, detail):
        return {"id": key, "label": label, "status": state, "detail": detail, "scope": "physical"}

    real = profile["real"]
    geometry_ready = (
        all(real.get(k) for k in ("pickup", "drop", "park")) if "pickup" in real else False
    )
    calibration = instrument.get("calibration_revision") or real.get("calibration_revision")
    return [
        check(
            "connection",
            "Device connectivity",
            "passed"
            if status["online"] and status["inspected"] and not status["fault"]
            else "missing",
            "Gateway online and connector identity verified."
            if status["online"] and status["inspected"]
            else f"Held: {status['fault']}"
            if status["fault"]
            else "Start the device gateway and verify the connector identity.",
        ),
        check(
            "hardware",
            "Physical capabilities",
            "passed" if status["inspected"] else "missing",
            f"Registered workflow on the verified connector: {', '.join(actions)}."
            if status["inspected"]
            else "No connector identity has been verified yet.",
        ),
        check(
            "geometry",
            "Geometry and reachability",
            "passed" if geometry_ready else "missing",
            "Reviewed deck coordinates are pinned in the qualified profile."
            if geometry_ready
            else "This workflow has no calibrated deck geometry (home/readback only).",
        ),
        check(
            "resources",
            "Physical resources",
            "passed" if latest_real else "missing",
            f"Latest physical observation from {latest_real['source']}."
            if latest_real
            else "No physical observation has been recorded.",
        ),
        check(
            "calibration",
            "Calibration",
            "passed" if calibration else "missing",
            f"Calibration revision {calibration}."
            if calibration
            else "No calibration revision is pinned.",
        ),
        check(
            "sync",
            "State consistency",
            "failed"
            if any(c["status"] == "different" for c in compared)
            else "passed"
            if compared and all(c["status"] == "match" for c in compared)
            else "missing",
            "Real and simulated states differ beyond tolerance in a completed run."
            if any(c["status"] == "different" for c in compared)
            else "Every compared field matched within tolerance."
            if compared and all(c["status"] == "match" for c in compared)
            else "No comparable real/simulated fields yet (different units or frames are never compared).",
        ),
        check(
            "authorization",
            "Physical execution",
            "passed" if completed else "missing",
            f"{len(completed)} operator-approved physical run(s) completed."
            if completed
            else "No operator-approved physical run has completed.",
        ),
    ]


def install(app, *, store, pairing, clock=time.time):
    def run_visible(request, owner, run):
        if run["requested_by"] != owner and not operator_claims(request):
            raise HTTPException(404, "Run not found")

    def linked_devices(owner, instrument_id):
        return [
            d for d in store.partition(owner, "device#") if d.get("instrument_id") == instrument_id
        ]

    @app.get("/api/sim2real/status")
    def status(request: Request, owner: str = Depends(identify)):
        return {
            "pairing_enabled": pairing.pairing_enabled,
            "real_enabled": pairing.real_enabled,
            "operator": operator_claims(request),
        }

    @app.get("/api/instruments")
    def instruments(operator: str = Depends(identify_operator)):
        return [
            {
                **record,
                "gateway": pairing.broker.status(device_target(record["instrument_id"])),
                "lease_holder": pairing.instruments.lease_holder(record["instrument_id"]),
            }
            for record in pairing.instruments.list()
        ]

    @app.get("/api/instruments/{instrument_id}")
    def instrument(instrument_id: str, operator: str = Depends(identify_operator)):
        record = pairing.instruments.get(instrument_id)
        return {
            **record,
            "gateway": pairing.broker.status(device_target(instrument_id)),
            "lease_holder": pairing.instruments.lease_holder(instrument_id),
            "checks_physical": physical_checks(pairing, instrument_id),
        }

    @app.put("/api/instruments/{instrument_id}/validation")
    def validation(
        instrument_id: str, data: ValidationConfig, operator: str = Depends(identify_operator)
    ):
        changed = pairing.instruments.configure_validation(
            instrument_id,
            expected_version=data.expected_version,
            checks=data.checks,
            tolerances=data.tolerances,
        )
        if changed.get("require_rehearsal") != data.require_rehearsal:
            updated = {
                **changed,
                "require_rehearsal": data.require_rehearsal,
                "version": changed["version"] + 1,
            }
            store.put("system#instruments", instrument_id, updated, changed["version"])
            changed = updated
        return changed

    @app.post("/api/instruments/{instrument_id}/reconcile")
    def reconcile(
        instrument_id: str, data: ReconcileRequest, operator: str = Depends(identify_operator)
    ):
        return start_reconcile(
            device_target(instrument_id), data.note, operator, instrument_id=instrument_id
        )

    @app.post("/api/sim-workers/{worker_id}/reconcile")
    def reconcile_sim(
        worker_id: str, data: ReconcileRequest, operator: str = Depends(identify_operator)
    ):
        return start_reconcile(f"sim:{worker_id}", data.note, operator)

    def start_reconcile(target, note, operator, instrument_id=None):
        status = pairing.broker.status(target)
        if not status["online"]:
            raise HTTPException(409, "Start the worker first; reconciliation inspects it")
        if status["pending"]:
            raise HTTPException(409, "Wait for pending commands to settle before reconciling")
        if instrument_id and pairing.instruments.lease_holder(instrument_id):
            raise HTTPException(
                409, "An active run or external lease still controls this instrument"
            )
        if status["reservation"]:
            raise HTTPException(409, "An active run still owns this worker")
        stamp = f"{clock():.6f}"
        ref = f"reconcile:{target}:{operator}"
        pairing.broker.enqueue(
            target, "inspect", None, ttl=30, ref=ref, command_id=f"rc.{target}.{stamp}.i"
        )
        pairing.broker.enqueue(
            target,
            "reconcile",
            {"note": note},
            ttl=30,
            ref=ref,
            command_id=f"rc.{target}.{stamp}.r",
        )
        return {"requested": True, "target": target}

    @app.get("/api/instruments/{instrument_id}/dataset")
    def dataset(instrument_id: str, operator: str = Depends(identify_operator)):
        rows = pairing.dataset(instrument_id)
        return {"rows": rows, "summary": summarize(rows)}

    @app.get("/api/instruments/{instrument_id}/calibrations")
    def calibrations(instrument_id: str, operator: str = Depends(identify_operator)):
        pairing.instruments.get(instrument_id)
        return store.partition(CALIBRATIONS, f"{instrument_id}#", limit=100)

    @app.post("/api/instruments/{instrument_id}/calibrations", status_code=201)
    def propose(
        instrument_id: str, data: ProposeCalibration, operator: str = Depends(identify_operator)
    ):
        instrument = pairing.instruments.get(instrument_id)
        key = f"{instrument_id}#{data.revision_id}"
        if store.get(CALIBRATIONS, key):
            raise HTTPException(409, "Revision ID already exists")
        rows = [
            r
            for r in pairing.dataset(instrument_id)
            if r["qualified_profile_sha256"] == instrument["qualified_profile_sha256"]
        ]
        summary = summarize(rows)
        offsets = propose_offsets(summary, min_samples=data.min_samples)
        if not offsets:
            raise HTTPException(422, "Not enough comparable residuals for a calibration proposal")
        record = {
            "version": 1,
            "instrument_id": instrument_id,
            "revision_id": data.revision_id,
            "status": "proposed",
            "basis_profile_sha256": instrument["qualified_profile_sha256"],
            "basis_runs": sorted({r["run_id"] for r in rows}),
            "summary": summary,
            "corrections": offsets,
            "proposed_by": operator,
            "proposed_at": clock(),
        }
        store.put(CALIBRATIONS, key, record, None)
        return record

    @app.post("/api/instruments/{instrument_id}/calibrations/{revision_id}/approve")
    def approve_calibration(
        instrument_id: str,
        revision_id: str,
        data: ApproveCalibration,
        operator: str = Depends(identify_operator),
    ):
        key = f"{instrument_id}#{revision_id}"
        proposal = store.get(CALIBRATIONS, key)
        if not proposal or proposal["status"] != "proposed":
            raise HTTPException(409, "Only a proposed revision can be approved")
        if proposal["proposed_by"] == operator:
            raise HTTPException(409, "A different operator must approve a calibration revision")
        instrument = pairing.instruments.get(instrument_id)
        if instrument["qualified_profile_sha256"] != proposal["basis_profile_sha256"]:
            raise HTTPException(409, "The instrument changed since this proposal; propose again")
        if pairing.instruments.lease_holder(instrument_id):
            raise HTTPException(409, "Wait for the active run or lease to end")
        try:
            changed = pairing.instruments.apply_calibration(
                instrument_id,
                expected_version=data.expected_version,
                revision_id=revision_id,
                corrections=proposal["corrections"],
                profile=data.profile,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        store.put(
            CALIBRATIONS,
            key,
            {
                **proposal,
                "status": "approved",
                "approved_by": operator,
                "approved_at": clock(),
                "version": 2,
            },
            1,
        )
        return changed

    @app.post("/api/pair-runs", status_code=201)
    def create(request: Request, data: CreatePairRun, owner: str = Depends(identify)):
        operator = operator_claims(request)
        if not operator and not linked_devices(owner, data.instrument_id):
            raise HTTPException(403, "Ask an operator to link this instrument to your device first")
        return pairing.create(owner, data, operator=operator)

    @app.get("/api/pair-runs")
    def list_runs(
        request: Request, instrument_id: str | None = None, owner: str = Depends(identify)
    ):
        runs = pairing.list(instrument_id)
        if not operator_claims(request):
            runs = [r for r in runs if r["requested_by"] == owner]
        return runs

    @app.get("/api/pair-runs/{run_id}")
    def read(request: Request, run_id: str, owner: str = Depends(identify)):
        run = pairing.raw(run_id)
        run_visible(request, owner, run)
        return pairing.public(run)

    @app.post("/api/pair-runs/{run_id}/approve")
    def approve(run_id: str, data: ApprovePairRun, operator: str = Depends(identify_operator)):
        return pairing.approve(operator, run_id, data)

    @app.post("/api/pair-runs/{run_id}/reject")
    def reject(run_id: str, data: RejectPairRun, operator: str = Depends(identify_operator)):
        return pairing.reject(operator, run_id, data)

    @app.post("/api/pair-runs/{run_id}/stop")
    def stop(request: Request, run_id: str, data: StopPairRun, owner: str = Depends(identify)):
        run = pairing.raw(run_id)
        run_visible(request, owner, run)
        return pairing.stop(owner, run_id, data)

    @app.get("/api/devices/{device_id}/pair-runs")
    def device_runs(device_id: str, owner: str = Depends(identify)):
        record = store.get(owner, f"device#{device_id}")
        if record is None:
            raise HTTPException(404, "Device not found")
        if not record.get("instrument_id"):
            return []
        return [r for r in pairing.list(record["instrument_id"]) if r["requested_by"] == owner]

    return pairing


__all__ = ["install", "physical_checks", "PAIR_RUNS", "Conflict"]
