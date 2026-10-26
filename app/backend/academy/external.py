"""External-orchestrator gate API: lease, validate-next-step, claim and report.

An external orchestrator that executes real steps itself (not through a Lab
Onboarding device gateway) may use the twin as a gate:

1. ``POST /external/v1/instruments/{id}/lease``: become the instrument's single
   control source. Lab Onboarding runs cannot approve while it is held.
2. ``POST /external/v1/instruments/{id}/predictions``: one-step twin prediction
   seeded with the orchestrator's current observation.
3. ``POST /external/v1/predictions/{id}/claim``: consume the receipt once,
   immediately before dispatch, with a fresh observation of the same state.
4. ``POST /external/v1/predictions/{id}/outcome``: report the real outcome so it
   becomes sim-to-real evidence (with the reporter recorded as provenance).

Credentials are a third, separate class: ``orc.<client_id>.<secret>``.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import time

from fastapi import Depends, HTTPException, Request
from pydantic import Field

from .models import StrictModel
from .store import Write

ORCHESTRATORS = "system#orchestrators"
PREFIX = "orc."
CLIENT_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


def orchestrator_credential(store, authorization: str, now=None):
    if not authorization.startswith("Bearer " + PREFIX):
        return None
    token = authorization[7:]
    client_id, separator, secret = token[len(PREFIX) :].partition(".")
    if not separator or len(secret) < 32 or not CLIENT_ID.fullmatch(client_id):
        return None
    record = store.get(ORCHESTRATORS, client_id)
    if (
        not record
        or record.get("revoked", True)
        or record.get("credential_expires", 0) <= (now if now is not None else time.time())
        or not secrets.compare_digest(
            record.get("token_digest", ""), hashlib.sha256(token.encode()).hexdigest()
        )
    ):
        return None
    return record


def issue_orchestrator(store, client_id, *, instruments, clock=time.time):
    """Operator-only: register an external orchestrator for the listed instruments."""
    if not CLIENT_ID.fullmatch(client_id or ""):
        raise ValueError("Invalid client ID")
    if store.get(ORCHESTRATORS, client_id):
        raise ValueError("Client ID was used before; choose a new one")
    if not instruments or any(not CLIENT_ID.fullmatch(i) for i in instruments):
        raise ValueError("List the instruments this orchestrator may lease")
    token = f"{PREFIX}{client_id}.{secrets.token_urlsafe(48)}"
    record = {
        "version": 1,
        "client_id": client_id,
        "instruments": sorted(set(instruments)),
        "credential_version": 1,
        "token_digest": hashlib.sha256(token.encode()).hexdigest(),
        "credential_expires": clock() + 90 * 86400,
        "revoked": False,
        "worker_class": "orchestrator",
    }
    store.transact([Write(ORCHESTRATORS, client_id, record, None)])
    return token, record


class LeaseRequest(StrictModel):
    seconds: float = Field(gt=0, le=3600)


class PredictionRequest(StrictModel):
    prediction_id: str = Field(pattern=r"^[A-Za-z0-9-]{8,64}$")
    operation_id: str = Field(min_length=1, max_length=64)
    start_observation: dict


class ClaimRequest(StrictModel):
    operation: dict
    current_observation: dict


class OutcomeRequest(StrictModel):
    outcome: dict


def install(app, *, store, pairing, runtime):
    def client(request: Request):
        if runtime == "aws":
            claims = (
                request.scope.get("aws.event", {})
                .get("requestContext", {})
                .get("authorizer", {})
                .get("lambda", {})
            )
            if claims.get("worker_class") != "orchestrator" or not claims.get("client_id"):
                raise HTTPException(403, "Orchestrator credential required")
            record = store.get(ORCHESTRATORS, claims["client_id"])
            if (
                not record
                or record.get("revoked", True)
                or record.get("credential_expires", 0) <= pairing.clock()
                or str(record["credential_version"]) != claims.get("credential_version")
            ):
                raise HTTPException(403, "Orchestrator credential is inactive")
        else:
            record = orchestrator_credential(
                store, request.headers.get("authorization", ""), pairing.clock()
            )
            if not record:
                raise HTTPException(403, "Orchestrator credential required")
        return record

    def allowed(record, instrument_id):
        if instrument_id not in record["instruments"]:
            raise HTTPException(403, "This orchestrator is not registered for the instrument")

    @app.post("/external/v1/instruments/{instrument_id}/lease")
    def lease(instrument_id: str, data: LeaseRequest, record=Depends(client)):
        allowed(record, instrument_id)
        status = pairing.broker.status(f"device:{instrument_id}")
        if status["fault"]:
            raise HTTPException(409, f"Instrument is held: {status['fault']}")
        return pairing.instruments.acquire(
            instrument_id, f"external:{record['client_id']}", seconds=data.seconds, kind="external"
        )

    @app.delete("/external/v1/instruments/{instrument_id}/lease")
    def unlease(instrument_id: str, record=Depends(client)):
        allowed(record, instrument_id)
        return {
            "released": pairing.instruments.release(
                instrument_id, f"external:{record['client_id']}"
            )
        }

    @app.post("/external/v1/instruments/{instrument_id}/predictions", status_code=201)
    def predict(instrument_id: str, data: PredictionRequest, record=Depends(client)):
        allowed(record, instrument_id)
        return pairing.create_prediction(
            record["client_id"],
            instrument_id,
            data.prediction_id,
            data.operation_id,
            data.start_observation,
        )

    @app.get("/external/v1/predictions/{prediction_id}")
    def read(prediction_id: str, record=Depends(client)):
        run = pairing.raw(prediction_id)
        if run["requested_by"] != f"external:{record['client_id']}":
            raise HTTPException(404, "Prediction not found")
        return pairing.public(run)

    @app.post("/external/v1/predictions/{prediction_id}/claim")
    def claim(prediction_id: str, data: ClaimRequest, record=Depends(client)):
        return pairing.claim_prediction(
            record["client_id"], prediction_id, data.operation, data.current_observation
        )

    @app.post("/external/v1/predictions/{prediction_id}/outcome")
    def outcome(prediction_id: str, data: OutcomeRequest, record=Depends(client)):
        return pairing.report_outcome(record["client_id"], prediction_id, data.outcome)
