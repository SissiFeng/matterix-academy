"""Dedicated machine-only HTTP API and zero-cache Lambda authorizer.

No Cognito identity, learner routes or browser cookies are accepted here.
"""

import json
import os
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from mangum import Mangum
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import external, protocol_api
from .instruments import gateway_credential
from .media import MediaService
from .models import StrictModel
from .pairing import PairRunService
from .runs import (
    BindRequest,
    CleanupRequest,
    LeaseRequest,
    RunService,
    SnapshotRequest,
    StartRequest,
    UnknownRequest,
    revised,
    worker_credential,
)
from .store import Conflict, DynamoStore, SQLiteStore


class HostProbe(StrictModel):
    observed_at: str
    hostname: str
    display: str | None
    environments: list[dict]
    repositories: list[dict]
    gpu: str


def machine_store():
    if os.getenv("ACADEMY_RUNTIME") == "aws":
        table = os.environ["ACADEMY_TABLE"]
        if not table:
            raise ValueError("Worker API requires a DynamoDB table")
        return DynamoStore(table)
    return SQLiteStore(os.getenv("ACADEMY_DATA_PATH", ".data/academy.sqlite"))


def authorize(event, context):
    """Simulation-worker authorizer: worker registry only, never gateway credentials."""
    worker = worker_credential(machine_store(), event.get("headers", {}).get("authorization", ""))
    if not worker or worker.get("worker_class", "simulation") != "simulation":
        return {"isAuthorized": False}
    return {
        "isAuthorized": True,
        "context": {
            "worker_id": worker["worker_id"],
            "credential_version": str(worker["credential_version"]),
            "worker_class": "simulation",
        },
    }


def authorize_gateway(event, context):
    """Device-gateway authorizer: gateway registry only, never simulation credentials."""
    gateway = gateway_credential(machine_store(), event.get("headers", {}).get("authorization", ""))
    if not gateway:
        return {"isAuthorized": False}
    return {
        "isAuthorized": True,
        "context": {
            "gateway_id": gateway["gateway_id"],
            "credential_version": str(gateway["credential_version"]),
            "worker_class": "device",
        },
    }


def authorize_orchestrator(event, context):
    """External-orchestrator authorizer: orchestrator registry only."""
    client = external.orchestrator_credential(
        machine_store(), event.get("headers", {}).get("authorization", "")
    )
    if not client:
        return {"isAuthorized": False}
    return {
        "isAuthorized": True,
        "context": {
            "client_id": client["client_id"],
            "credential_version": str(client["credential_version"]),
            "worker_class": "orchestrator",
        },
    }


def flag(name):
    return os.getenv(name, "false").lower() == "true"


def create_worker_app(
    store=None,
    *,
    runtime=None,
    enabled=None,
    clock=None,
    pairing_enabled=None,
    real_enabled=None,
    poll_wait=None,
):
    runtime = runtime or os.getenv("ACADEMY_RUNTIME", "local")
    if runtime not in {"local", "aws"}:
        raise ValueError("Invalid worker API runtime")
    store = store or machine_store()
    enabled = (
        enabled
        if enabled is not None
        else os.getenv("ACADEMY_REMOTE_ENABLED", "false").lower() == "true"
    )
    service = RunService(store, enabled, **({"clock": clock} if clock else {}))
    pairing_enabled = (
        flag("ACADEMY_PAIRING_ENABLED") if pairing_enabled is None else pairing_enabled
    )
    real_enabled = flag("ACADEMY_REAL_ENABLED") if real_enabled is None else real_enabled
    if real_enabled and not pairing_enabled:
        raise ValueError("Physical execution requires sim-to-real coordination to be enabled")
    pairing = PairRunService(
        store,
        pairing_enabled=pairing_enabled,
        real_enabled=real_enabled,
        **({"clock": clock} if clock else {}),
    )
    poll_wait = float(os.getenv("ACADEMY_POLL_WAIT_S", "8")) if poll_wait is None else poll_wait
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.runs = service
    app.state.pairing = pairing
    app.state.media = MediaService(service)
    if runtime == "local":
        app.add_middleware(
            TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"]
        )

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse(
            {"detail": "State changed; recover the saved run before continuing"}, status_code=409
        )

    @app.exception_handler(StarletteHTTPException)
    async def coded(request, exc):
        # Worker agents choose recovery from ``code``: a rejected credential stops them.
        code = {401: "credential", 403: "credential", 409: "conflict"}.get(
            exc.status_code, "invalid"
        )
        return JSONResponse(
            {"detail": exc.detail, "code": code, "error": str(exc.detail)},
            status_code=exc.status_code,
        )

    @app.middleware("http")
    async def no_browser(request, call_next):
        if request.headers.get("origin"):
            return JSONResponse({"detail": "Browser origins are not accepted"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    def identify_worker(request: Request):
        if runtime == "aws":
            claims = (
                request.scope.get("aws.event", {})
                .get("requestContext", {})
                .get("authorizer", {})
                .get("lambda", {})
            )
            worker_id = claims.get("worker_id")
            if not isinstance(worker_id, str) or not worker_id:
                raise HTTPException(403, "Machine authorizer context is required")
            worker = service.worker(worker_id)
            if str(worker["credential_version"]) != claims.get("credential_version"):
                raise HTTPException(403, "Machine credential was rotated")
        else:
            worker = worker_credential(
                store, request.headers.get("authorization", ""), service.clock()
            )
            if not worker:
                raise HTTPException(403, "Machine credential is required")
        return worker["worker_id"]

    @app.get("/internal/workers/me")
    def status(worker_id: str = Depends(identify_worker)):
        worker = service.worker(worker_id)
        return {
            k: worker.get(k)
            for k in (
                "worker_id",
                "state",
                "active_run",
                "qualified",
                "engine_version",
                "asset_version",
                "controls",
            )
        }

    @app.get("/internal/workers/configuration")
    def configuration(worker_id: str = Depends(identify_worker)):
        worker = service.worker(worker_id)
        return {
            "enabled": service.enabled,
            "qualified": worker.get("qualified", False),
            "configuration": worker.get("native_config"),
        }

    @app.post("/internal/workers/probe")
    def probe(data: HostProbe, worker_id: str = Depends(identify_worker)):
        payload = data.model_dump(mode="json")
        if len(json.dumps(payload).encode()) > 32000:
            raise HTTPException(413, "Environment report is too large")
        old = store.get("system#host-probes", worker_id)
        record = revised(old, report=payload) if old else {"version": 1, "report": payload}
        store.put("system#host-probes", worker_id, record, old["version"] if old else None)
        return {"received": True, "worker_id": worker_id}

    @app.post("/internal/runs/claim")
    def claim(worker_id: str = Depends(identify_worker)):
        result = service.claim(worker_id)
        return result if result else Response(status_code=204)

    @app.get("/internal/runs/{run_id}")
    def read(run_id: UUID, worker_id: str = Depends(identify_worker)):
        return service.machine_view(service.raw(run_id), worker_id)

    @app.post("/internal/runs/{run_id}/start")
    def start(run_id: UUID, data: StartRequest, worker_id: str = Depends(identify_worker)):
        return service.start(worker_id, run_id, data)

    @app.post("/internal/runs/{run_id}/binding")
    def bind(run_id: UUID, data: BindRequest, worker_id: str = Depends(identify_worker)):
        return service.bind(worker_id, run_id, data)

    @app.post("/internal/runs/{run_id}/heartbeat")
    def heartbeat(run_id: UUID, data: LeaseRequest, worker_id: str = Depends(identify_worker)):
        return service.heartbeat(worker_id, run_id, data)

    @app.post("/internal/runs/{run_id}/snapshots")
    def snapshot(run_id: UUID, data: SnapshotRequest, worker_id: str = Depends(identify_worker)):
        return service.snapshot(worker_id, run_id, data)

    @app.post("/internal/runs/{run_id}/unknown")
    def unknown(run_id: UUID, data: UnknownRequest, worker_id: str = Depends(identify_worker)):
        return service.unknown(worker_id, run_id, data)

    @app.post("/internal/runs/{run_id}/cleanup")
    def cleanup(run_id: UUID, data: CleanupRequest, worker_id: str = Depends(identify_worker)):
        return service.cleanup(worker_id, run_id, data)

    @app.post("/internal/runs/{run_id}/publisher")
    def publisher(run_id: UUID, data: LeaseRequest, worker_id: str = Depends(identify_worker)):
        return app.state.media.publisher(worker_id, run_id, data.claim_token)

    @app.post("/internal/runs/{run_id}/viewers")
    def viewers(run_id: UUID, data: LeaseRequest, worker_id: str = Depends(identify_worker)):
        return app.state.media.viewers(worker_id, run_id, data.claim_token)

    protocol_api.install(
        app, store=store, runs=service, pairing=pairing, runtime=runtime, poll_wait=poll_wait
    )
    external.install(app, store=store, pairing=pairing, runtime=runtime)
    return app


app = create_worker_app()
handler = Mangum(app, lifespan="off")


def reap_handler(event, context):
    store = machine_store()
    runs = RunService(store, enabled=flag("ACADEMY_REMOTE_ENABLED"))
    pairing = PairRunService(
        store,
        pairing_enabled=flag("ACADEMY_PAIRING_ENABLED"),
        real_enabled=flag("ACADEMY_REAL_ENABLED"),
    )
    return {
        "expired_runs": runs.reap(),
        "closed_viewports": MediaService(runs).reap(),
        "expired_commands": pairing.reap(),
    }
