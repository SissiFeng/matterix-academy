from typing import Literal
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from mangum import Mangum
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .auth import identify, local_signer
from .discovery import NotebookUpdate
from .gateway import GatewayUnavailable, MatterixGateway
from .learning import present, readiness
from .models import COURSES, Experiment, Guest, Profile, Revision, UpdateExperiment, UpdateLearning
from .settings import Settings
from .store import Conflict, DynamoStore, SQLiteStore
from .teaching import InvalidTransition, control, execute_step, initial_state, new_session


def create_app(settings: Settings | None = None, store=None):
    settings = settings or Settings.from_env()
    app = FastAPI(
        title="Matterix Academy",
        version="0.1.0",
        docs_url="/api/docs" if settings.runtime == "local" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.runtime == "local" else None,
    )
    app.state.settings = settings
    app.state.store = store or (
        DynamoStore(settings.table)
        if settings.runtime == "aws"
        else SQLiteStore(settings.data_path)
    )
    if settings.runtime == "local":
        app.add_middleware(
            TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"]
        )

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        origin = request.headers.get("origin")
        allowed = {settings.app_url}
        if settings.runtime == "local":
            allowed |= {
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:4173",
                "http://127.0.0.1:4173",
            }
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin not in allowed:
            return JSONResponse({"detail": "Origin is not allowed"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    @app.exception_handler(Conflict)
    async def conflict_handler(request, exc):
        return JSONResponse(
            {"detail": "This record changed in another request. Reload its latest state."},
            status_code=409,
        )

    @app.exception_handler(InvalidTransition)
    async def transition_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/api/config")
    def config():
        return {
            "auth": "cognito"
            if settings.runtime == "aws"
            else "local"
            if settings.allow_demo
            else "disabled",
            "issuer": settings.issuer,
            "client_id": settings.client_id,
            "cognito_domain": settings.cognito_domain,
            "app_url": settings.app_url,
            "engines": {
                "teaching": {"available": True, "evidence": "synthetic"},
                "matterix": {
                    "available": False,
                    "reason": "Ubuntu gateway has not been connected and qualified",
                },
            },
        }

    @app.post("/api/auth/guest")
    def guest(data: Guest, response: Response):
        if settings.runtime != "local" or not settings.allow_demo:
            raise HTTPException(404, "Local sign-in is disabled")
        subject = f"local-{uuid4()}"
        app.state.store.put(
            subject,
            "profile",
            {
                "version": 1,
                "name": data.name.strip() or "Learner",
                "experience": "new",
                "onboarded": False,
            },
            None,
        )
        response.set_cookie(
            "academy_local",
            local_signer(settings).dumps({"sub": subject}),
            httponly=True,
            samesite="strict",
            max_age=86400,
            path="/api",
        )
        return {"signed_in": True}

    @app.post("/api/auth/logout")
    def logout(response: Response):
        response.delete_cookie("academy_local", path="/api")
        return {"signed_out": True}

    @app.get("/api/me")
    def me(owner: str = Depends(identify)):
        return app.state.store.get(owner, "profile") or {
            "version": 0,
            "name": "Learner",
            "experience": "new",
            "onboarded": False,
        }

    @app.put("/api/me")
    def update_profile(data: Profile, owner: str = Depends(identify)):
        old = app.state.store.get(owner, "profile")
        version = old["version"] if old else None
        profile = {**data.model_dump(), "version": (version or 0) + 1}
        app.state.store.put(owner, "profile", profile, version)
        return profile

    @app.get("/api/discovery")
    def discovery_notebook(owner: str = Depends(identify)):
        return app.state.store.get(owner, "discovery") or {"version": 0, "briefs": []}

    @app.put("/api/discovery")
    def update_discovery(data: NotebookUpdate, owner: str = Depends(identify)):
        notebook = {
            "version": data.expected_version + 1,
            "briefs": [brief.model_dump(mode="json") for brief in data.briefs],
        }
        app.state.store.put(owner, "discovery", notebook, data.expected_version or None)
        return notebook

    @app.get("/api/courses")
    def courses(owner: str = Depends(identify)):
        return COURSES

    @app.get("/api/remote/status")
    def remote_status(owner: str = Depends(identify)):
        if not settings.gateway_url or not settings.gateway_token:
            return {
                "state": "not_configured",
                "available": False,
                "message": "The Ubuntu simulation connection is not configured yet. Lessons and teaching exercises are still available.",
            }
        try:
            gateway = MatterixGateway(settings.gateway_url, settings.gateway_token)
            try:
                capabilities = gateway.capabilities()
            finally:
                gateway.close()
        except (ValueError, GatewayUnavailable):
            return {
                "state": "unreachable",
                "available": False,
                "message": "The Ubuntu simulation connection could not be verified. Contact your lab administrator. Teaching exercises do not replace remote results.",
            }
        missing = sorted({"pickup", "aspirate", "dispense", "drop"} - set(capabilities.actions))
        return {
            "state": "awaiting_qualification",
            "available": False,
            "message": "The simulator responded, but session isolation, reset and authenticated streaming still need verification. Remote execution is not available yet.",
            "missing_actions": missing,
        }

    @app.get("/api/sessions")
    def sessions(owner: str = Depends(identify)):
        return [present(session) for session in app.state.store.list(owner)]

    @app.post("/api/sessions", status_code=201)
    def create_session(experiment: Experiment, owner: str = Depends(identify)):
        session = new_session(experiment)
        app.state.store.put(owner, f"session#{session['id']}", session, None)
        return present(session)

    def get_session(owner: str, session_id: UUID):
        session = app.state.store.get(owner, f"session#{session_id}")
        if session is None:
            raise HTTPException(404, "Experiment not found")
        return session

    def save(owner, session, expected):
        if session["version"] != expected:
            raise Conflict
        session["version"] += 1
        app.state.store.put(owner, f"session#{session['id']}", session, expected)
        return present(session)

    @app.get("/api/sessions/{session_id}")
    def session_detail(session_id: UUID, owner: str = Depends(identify)):
        return present(get_session(owner, session_id))

    @app.put("/api/sessions/{session_id}")
    def update_session(session_id: UUID, data: UpdateExperiment, owner: str = Depends(identify)):
        session = get_session(owner, session_id)
        if session["status"] != "draft":
            raise InvalidTransition("Reset the experiment before editing it")
        if data.experiment.course_id != session["experiment"]["course_id"]:
            raise InvalidTransition("Create a new experiment to change courses")
        session["experiment"] = data.experiment.model_dump()
        session["state"] = initial_state(session["experiment"])
        if data.experiment.course_id == "flex-first-transfer":
            session["learning"].update(phase="prepare", checks=[], prediction=None, reflection="")
        return save(owner, session, data.version)

    @app.put("/api/sessions/{session_id}/learning")
    def update_learning(session_id: UUID, data: UpdateLearning, owner: str = Depends(identify)):
        session = get_session(owner, session_id)
        if session["experiment"]["course_id"] != "flex-first-transfer":
            raise InvalidTransition("Learning checkpoints belong to the first-transfer lesson")
        if session["status"] == "running":
            raise InvalidTransition("Pause the experiment before changing learning checkpoints")
        session["learning"] = data.learning.model_dump()
        return save(owner, session, data.version)

    @app.post("/api/sessions/{session_id}/advance")
    def advance(session_id: UUID, data: Revision, owner: str = Depends(identify)):
        session = get_session(owner, session_id)
        if session["version"] != data.version:
            raise Conflict
        return save(owner, execute_step(session), data.version)

    @app.post("/api/sessions/{session_id}/{command}")
    def command(
        session_id: UUID,
        command: Literal["start", "pause", "resume", "reset"],
        data: Revision,
        owner: str = Depends(identify),
    ):
        session = get_session(owner, session_id)
        if command in {"start", "resume"}:
            # Legacy draft layouts must be corrected explicitly, never moved silently.
            try:
                Experiment.model_validate(session["experiment"])
            except ValueError as exc:
                raise InvalidTransition(
                    "Review the deck: the Flex waste chute must be fixed at D3, then save the experiment"
                ) from exc
            if (
                session["experiment"]["course_id"] == "flex-first-transfer"
                and not readiness(session)["ready"]
            ):
                raise InvalidTransition(
                    "Complete the equipment tour, preparation checks and liquid prediction before running"
                )
        return save(owner, control(session, command), data.version)

    return app


app = create_app()
handler = Mangum(app, lifespan="off")
