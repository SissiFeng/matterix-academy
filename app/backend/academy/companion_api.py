"""Dedicated companion API; no browser identity, cookies or native-worker tokens."""

import os
from uuid import UUID

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from mangum import Mangum
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .connections import ConnectionService, ConnectorProbe, ConnectorReceipt, PairRequest
from .models import StrictModel
from .store import Conflict, DynamoStore, SQLiteStore


class CommandPoll(StrictModel):
    pass


def companion_store():
    if os.getenv("ACADEMY_RUNTIME") == "aws":
        table = os.environ["ACADEMY_TABLE"]
        if not table:
            raise ValueError("Companion API requires a DynamoDB table")
        return DynamoStore(table)
    return SQLiteStore(os.getenv("ACADEMY_DATA_PATH", ".data/academy.sqlite"))


def create_companion_app(
    store=None, *, runtime=None, enabled=None, approved_release=None, clock=None
):
    runtime = runtime or os.getenv("ACADEMY_RUNTIME", "local")
    if runtime not in {"local", "aws"}:
        raise ValueError("Invalid companion API runtime")
    enabled = (
        enabled
        if enabled is not None
        else os.getenv("ACADEMY_CONNECTOR_REAL_ENABLED", "false").lower() == "true"
    )
    if approved_release is None:
        # The catalog is optional during packaging; absent catalog always blocks motion.
        try:
            from .connector_catalog import approved_release
        except ImportError:
            approved_release = None
    service = ConnectionService(
        store or companion_store(),
        enabled=enabled,
        approved_release=approved_release,
        **({"clock": clock} if clock else {}),
    )
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.connections = service
    if runtime == "local":
        app.add_middleware(
            TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"]
        )

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse(
            {"detail": "State changed; recover the saved command before continuing"},
            status_code=409,
        )

    @app.middleware("http")
    async def no_browser(request, call_next):
        if "origin" in request.headers:
            return JSONResponse({"detail": "Browser origins are not accepted"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def machine(request: Request):
        return service.authenticate(request.headers.get("authorization", ""))

    @app.post("/companion/pair")
    def pair(data: PairRequest):
        return service.redeem(data)

    @app.get("/companion/me")
    def me(installation=Depends(machine)):
        return service.machine_public(installation)

    @app.post("/companion/probe")
    def probe(data: ConnectorProbe, installation=Depends(machine)):
        return service.probe(installation, data)

    @app.post("/companion/command")
    def claim(data: CommandPoll | None = None, installation=Depends(machine)):
        result = service.claim(installation)
        return result if result else Response(status_code=204)

    @app.get("/companion/commands/{run_id}")
    def get_command(run_id: UUID, installation=Depends(machine)):
        return service.command_public(service.machine_run(installation, run_id))

    @app.post("/companion/commands/{run_id}/receipt")
    def receipt(run_id: UUID, data: ConnectorReceipt, installation=Depends(machine)):
        return service.receipt(installation, run_id, data)

    return app


app = create_companion_app()
handler = Mangum(app, lifespan="off")
