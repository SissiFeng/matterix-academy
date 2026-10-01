"""Dedicated machine-only HTTP API and zero-cache Lambda authorizer.

No Cognito identity, learner routes or browser cookies are accepted here.
"""

import os
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from mangum import Mangum
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .runs import (
    BindRequest,
    CleanupRequest,
    LeaseRequest,
    RunService,
    SnapshotRequest,
    StartRequest,
    UnknownRequest,
    worker_credential,
)
from .store import Conflict, DynamoStore, SQLiteStore


def machine_store():
    if os.getenv("ACADEMY_RUNTIME") == "aws":
        table = os.environ["ACADEMY_TABLE"]
        if not table:
            raise ValueError("Worker API requires a DynamoDB table")
        return DynamoStore(table)
    return SQLiteStore(os.getenv("ACADEMY_DATA_PATH", ".data/academy.sqlite"))


def authorize(event, context):
    worker = worker_credential(machine_store(), event.get("headers", {}).get("authorization", ""))
    if not worker:
        return {"isAuthorized": False}
    return {
        "isAuthorized": True,
        "context": {
            "worker_id": worker["worker_id"],
            "credential_version": str(worker["credential_version"]),
        },
    }


def create_worker_app(store=None, *, runtime=None, enabled=None, clock=None):
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
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.runs = service
    if runtime == "local":
        app.add_middleware(
            TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"]
        )

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse(
            {"detail": "State changed; recover the saved run before continuing"}, status_code=409
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

    return app


app = create_worker_app()
handler = Mangum(app, lifespan="off")


def reap_handler(event, context):
    return {"expired_runs": RunService(machine_store()).reap()}
