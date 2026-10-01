"""Contract client for a future Ubuntu gateway; not a native Matterix API.

Kept outside the teaching runner. No fallback from remote failure to synthetic state.
The platform does not expose this until a deployed gateway passes qualification.
"""

from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

import httpx
from pydantic import AwareDatetime, Field, model_validator

from .models import StrictModel
from .remote_run import RemoteRunRequest, RemoteRunSnapshot, check_run_snapshot


class GatewayCapabilities(StrictModel):
    contract_version: str
    engine: str
    simulation_only: bool
    supports_isolated_sessions: bool
    actions: list[str] = Field(default_factory=list)


class GatewayUnavailable(RuntimeError):
    pass


class RemoteOutcomeUnknown(GatewayUnavailable):
    """A submitted mutation may have executed. Reconcile; do not retry it blindly."""


class RemoteOperationPending(GatewayUnavailable):
    """A recorded operation is still in flight; only read its original IDs."""


class RemoteCommand(StrictModel):
    command_id: UUID
    expected_revision: int = Field(ge=1)
    action: Literal["pickup", "aspirate", "dispense", "drop"]
    object_id: Literal["tips", "stock", "plate", "waste"]
    well_id: str = Field(default="", max_length=16, pattern=r"^[A-Za-z0-9]*$")
    volume_ul: float | None = Field(default=None, gt=0, le=300, allow_inf_nan=False)


class RemoteSnapshot(StrictModel):
    id: UUID
    revision: int = Field(ge=1)
    status: Literal["loading", "ready", "running", "paused", "faulted", "closed"]
    engine: Literal["matterix"]
    simulation_only: Literal[True]
    engine_version: str = Field(min_length=1, max_length=100)
    asset_version: str = Field(min_length=1, max_length=100)
    lease_expires_at: AwareDatetime
    observed_at: AwareDatetime


class RemoteOperation(StrictModel):
    command_id: UUID
    operation_id: UUID
    status: Literal["accepted", "running", "completed", "failed", "unknown"]


class RemoteAllocation(StrictModel):
    allocation_id: UUID
    status: Literal["pending", "allocated", "failed", "unknown"]
    session_id: UUID | None = None

    @model_validator(mode="after")
    def allocated_requires_identity(self):
        if self.status == "allocated" and self.session_id is None:
            raise ValueError("An allocated lease must identify its session")
        return self


class MatterixGateway:
    def __init__(self, base_url: str, token: str, transport=None):
        parsed = urlparse(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("An operator-configured HTTPS gateway URL is required")
        if not token:
            raise ValueError("A gateway service credential is required")
        self.client = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
            follow_redirects=False,
            transport=transport,
        )

    def capabilities(self):
        try:
            response = self.client.get("v1/capabilities")
            response.raise_for_status()
            capabilities = GatewayCapabilities.model_validate(response.json())
            if (
                capabilities.contract_version != "1"
                or capabilities.engine != "matterix"
                or not capabilities.simulation_only
                or not capabilities.supports_isolated_sessions
            ):
                raise ValueError("Gateway does not meet the Academy simulation contract")
            return capabilities
        except (httpx.HTTPError, ValueError) as exc:
            raise GatewayUnavailable("Matterix gateway qualification failed") from exc

    def close(self):
        self.client.close()

    def _exchange(self, method, path, model, payload=None):
        mutation = method != "GET"
        try:
            response = self.client.request(method, path, json=payload)
            if mutation and response.status_code >= 500:
                raise RemoteOutcomeUnknown(
                    "Remote result is unknown; reconcile the operation before continuing"
                )
            response.raise_for_status()
        except httpx.TransportError as exc:
            error = RemoteOutcomeUnknown if mutation else GatewayUnavailable
            raise error("Remote connection failed; do not automatically repeat a command") from exc
        except httpx.HTTPStatusError as exc:
            raise GatewayUnavailable("Remote request was rejected") from exc
        try:
            return model.model_validate(response.json())
        except ValueError as exc:
            error = RemoteOutcomeUnknown if mutation else GatewayUnavailable
            raise error("Remote response did not match the expected contract") from exc

    def allocate(self, allocation_id: UUID):
        allocation_id = UUID(str(allocation_id))
        result = self._exchange(
            "POST",
            "v1/sessions",
            RemoteSnapshot,
            {
                "allocation_id": str(allocation_id),
                "scene_id": "flex-first-transfer-v1",
            },
        )
        try:
            allocation = self.allocation(allocation_id)
        except GatewayUnavailable as exc:
            raise RemoteOutcomeUnknown(
                "Allocation acknowledgement could not be associated"
            ) from exc
        if allocation.status == "pending":
            raise RemoteOperationPending("Allocation is still pending")
        if allocation.status != "allocated" or allocation.session_id != result.id:
            raise RemoteOutcomeUnknown("Allocation acknowledgement belongs to a different session")
        return result

    def allocation(self, allocation_id: UUID):
        allocation_id = UUID(str(allocation_id))
        result = self._exchange("GET", f"v1/allocations/{allocation_id}", RemoteAllocation)
        if result.allocation_id != allocation_id:
            raise GatewayUnavailable("Remote allocation identity did not match")
        return result

    def snapshot(self, session_id: UUID):
        session_id = UUID(str(session_id))
        result = self._exchange("GET", f"v1/sessions/{session_id}", RemoteSnapshot)
        if result.id != session_id:
            raise GatewayUnavailable("Remote session identity did not match")
        return result

    def start_run(self, session_id: UUID, request: RemoteRunRequest):
        """Submit a saved whole workflow once; receipt is not step completion."""
        session_id = UUID(str(session_id))
        request = RemoteRunRequest.model_validate(request.model_dump())
        result = self._exchange(
            "POST",
            f"v1/sessions/{session_id}/runs",
            RemoteRunSnapshot,
            request.model_dump(mode="json"),
        )
        try:
            check_run_snapshot(result, session_id, request)
        except ValueError as exc:
            raise RemoteOutcomeUnknown(
                "Remote run acknowledgement did not match the saved plan"
            ) from exc
        return result

    def run_snapshot(
        self,
        session_id: UUID,
        request: RemoteRunRequest,
        previous: RemoteRunSnapshot | None = None,
    ):
        """Recover progress by the original run ID, including after a lost response."""
        session_id = UUID(str(session_id))
        request = RemoteRunRequest.model_validate(request.model_dump())
        result = self._exchange(
            "GET", f"v1/sessions/{session_id}/runs/{request.run_id}", RemoteRunSnapshot
        )
        try:
            check_run_snapshot(result, session_id, request, previous)
        except ValueError as exc:
            raise GatewayUnavailable(
                "Remote progress could not be reconciled with this run"
            ) from exc
        return result

    def submit(self, session_id: UUID, command: RemoteCommand):
        result = self._exchange(
            "POST",
            f"v1/sessions/{UUID(str(session_id))}/commands",
            RemoteOperation,
            command.model_dump(mode="json"),
        )
        if result.command_id != command.command_id:
            raise RemoteOutcomeUnknown("Remote acknowledgement did not match the submitted command")
        return result

    def command_result(self, session_id: UUID, command_id: UUID):
        command_id = UUID(str(command_id))
        result = self._exchange(
            "GET", f"v1/sessions/{UUID(str(session_id))}/commands/{command_id}", RemoteOperation
        )
        if result.command_id != command_id:
            raise GatewayUnavailable("Remote command identity did not match")
        return result

    def operation(self, session_id: UUID, operation_id: UUID):
        operation_id = UUID(str(operation_id))
        result = self._exchange(
            "GET", f"v1/sessions/{UUID(str(session_id))}/operations/{operation_id}", RemoteOperation
        )
        if result.operation_id != operation_id:
            raise GatewayUnavailable("Remote operation identity did not match")
        return result

    def reset(self, session_id: UUID, command_id: UUID, expected_revision: int):
        if expected_revision < 1:
            raise ValueError("A positive expected revision is required")
        result = self._exchange(
            "POST",
            f"v1/sessions/{UUID(str(session_id))}/reset",
            RemoteOperation,
            {"command_id": str(UUID(str(command_id))), "expected_revision": expected_revision},
        )
        if result.command_id != UUID(str(command_id)):
            raise RemoteOutcomeUnknown("Remote reset acknowledgement did not match")
        return result

    def release(self, session_id: UUID, command_id: UUID, expected_revision: int):
        if expected_revision < 1:
            raise ValueError("A positive expected revision is required")
        result = self._exchange(
            "DELETE",
            f"v1/sessions/{UUID(str(session_id))}",
            RemoteOperation,
            {"command_id": str(UUID(str(command_id))), "expected_revision": expected_revision},
        )
        if result.command_id != UUID(str(command_id)):
            raise RemoteOutcomeUnknown("Remote release acknowledgement did not match")
        return result
