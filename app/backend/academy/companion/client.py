"""Outbound Academy machine protocol. No inbound web service is started."""

import json
import time
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import httpx
from pydantic import AwareDatetime, Field

from academy.connections import ConnectorResolution
from academy.models import Experiment, StrictModel

from .compiler import compile_plan
from .config import COMMIT, DIGEST, LocalConfig, RobotProfile, canonical
from .journal import Journal
from .protocol import ProtocolEngine


class Credentials(StrictModel):
    installation_id: UUID
    secret: str = Field(pattern=r"^[A-Za-z0-9_-]{43,128}$")
    academy_url: str


class Command(StrictModel):
    run_id: UUID
    connection_id: UUID
    installation_id: UUID
    version: int = Field(ge=1)
    plan_hash: str = Field(pattern=DIGEST)
    plan: Experiment
    instrument: Literal["flex", "ot2"]
    serial: str
    release_id: str
    artifact_sha256: str = Field(pattern=DIGEST)
    profile_sha256: str = Field(pattern=DIGEST)
    source_commit: str = Field(pattern=COMMIT)
    firmware: str
    runtime_contract_id: str
    runtime_release_id: str
    runtime_bundle_sha256: str = Field(pattern=DIGEST)
    expires_at: AwareDatetime
    status: Literal["claimed"]
    stop_requested: bool
    resolution: dict | None = None

    def validate_binding(self, profile: RobotProfile, credentials: Credentials):
        profile.assert_current()
        for name in (
            "instrument",
            "serial",
            "release_id",
            "artifact_sha256",
            "source_commit",
            "firmware",
            "runtime_contract_id",
            "runtime_release_id",
            "runtime_bundle_sha256",
        ):
            if getattr(self, name) != getattr(profile, name):
                raise ValueError(f"Command {name} differs from qualified installation")
        if (
            self.profile_sha256 != profile.sha256
            or self.installation_id != credentials.installation_id
        ):
            raise ValueError("Command profile or installation binding mismatch")
        if self.expires_at <= datetime.now(UTC):
            raise ValueError("Physical execution authorization has expired")


def receipt_for(command: dict, **result) -> dict:
    fields = (
        "connection_id",
        "installation_id",
        "plan_hash",
        "instrument",
        "serial",
        "release_id",
        "artifact_sha256",
        "profile_sha256",
        "source_commit",
        "firmware",
        "runtime_contract_id",
        "runtime_release_id",
        "runtime_bundle_sha256",
    )
    return {"command_id": command["run_id"], **{key: command[key] for key in fields}, **result}


def unknown_receipt(row: dict, detail: str) -> dict:
    return receipt_for(
        json.loads(row["command"]),
        outcome="unknown",
        protocol_id=row["protocol_id"],
        robot_run_id=row["robot_run_id"],
        completed_actions=0,
        stop_confirmed=False,
        detail=detail,
    )


class AcademyClient:
    def __init__(self, config: LocalConfig, credentials: Credentials, *, transport=None):
        if credentials.academy_url != config.academy_url:
            raise ValueError("Stored credential belongs to a different Academy origin")
        self.credentials = credentials
        self.http = httpx.Client(
            base_url=config.academy_url,
            timeout=15,
            headers={"Authorization": f"Bearer {credentials.installation_id}.{credentials.secret}"},
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def close(self):
        self.http.close()

    def request(self, method, path, **kwargs):
        response = self.http.request(method, path, **kwargs)
        response.raise_for_status()
        return None if response.status_code == 204 else response.json()

    def pair(self, code: str):
        return self.request(
            "POST",
            "/companion/pair",
            json={
                "code": code,
                "installation_id": str(self.credentials.installation_id),
                "secret": self.credentials.secret,
            },
        )

    def probe(self, profile: RobotProfile):
        return self.request(
            "POST",
            "/companion/probe",
            json={
                "instrument": profile.instrument,
                "serial": profile.serial,
                "release_id": profile.release_id,
                "artifact_sha256": profile.artifact_sha256,
                "profile_sha256": profile.sha256,
                "source_commit": profile.source_commit,
                "firmware": profile.firmware,
                "runtime_contract_id": profile.runtime_contract_id,
                "runtime_release_id": profile.runtime_release_id,
                "runtime_bundle_sha256": profile.runtime_bundle_sha256,
                "capabilities": ["protocol-engine"],
                "reachable": True,
            },
        )

    def flush(self, journal: Journal):
        for run_id, receipt in journal.outbox():
            self.request("POST", f"/companion/commands/{run_id}/receipt", json=receipt)
            journal.acknowledged(run_id)


def recover(journal: Journal):
    """A restarted process never replays or promotes a previously attempted command."""
    for row in journal.unfinished():
        journal.finish(
            row["id"],
            unknown_receipt(
                row,
                "Companion restarted during an attempted command; inspect and reconcile locally. No replay.",
            ),
        )


def validate_resolution(row: dict, response: dict, credentials: Credentials) -> dict | None:
    """Only an authenticated server GET may supply this identity-bound audit.

    Resolution is authority to unlock NEW work. The original unknown outcome
    and command ID remain unchanged, and the old command is never executed.
    """
    original = Command.model_validate(json.loads(row["command"]))
    current = Command.model_validate({**response, "status": "claimed"})
    if original.installation_id != credentials.installation_id:
        raise ValueError("Resolution belongs to another local installation")
    original_data, current_data = original.model_dump(mode="json"), current.model_dump(mode="json")
    for key, value in original_data.items():
        if (
            key not in {"status", "version", "stop_requested", "resolution"}
            and current_data[key] != value
        ):
            raise ValueError("Resolution command binding mismatch")
    audit = current.resolution
    if audit is None:
        return None
    if (
        set(audit) != {"request", "resolved_at", "historical_status", "replay_authorized"}
        or response.get("status") != "unknown"
        or audit["historical_status"] != "unknown"
        or audit["replay_authorized"] is not False
    ):
        raise ValueError("Resolution cannot rewrite history or authorize replay")
    resolved_at = audit["resolved_at"]
    if (
        isinstance(resolved_at, bool)
        or not isinstance(resolved_at, (int, float))
        or not 0 < resolved_at <= datetime.now(UTC).timestamp() + 60
    ):
        raise ValueError("Invalid authoritative resolution time")
    request = ConnectorResolution.model_validate(audit["request"])
    if (
        request.expected_version < original.version
        or current.version != request.expected_version + 1
    ):
        raise ValueError("Resolution revision does not bind the authoritative command")
    request_data = request.model_dump(mode="json")
    for key in (
        "connection_id",
        "installation_id",
        "plan_hash",
        "instrument",
        "serial",
        "release_id",
        "artifact_sha256",
        "profile_sha256",
        "source_commit",
        "firmware",
        "runtime_contract_id",
        "runtime_release_id",
        "runtime_bundle_sha256",
    ):
        if request_data[key] != original_data[key]:
            raise ValueError("Resolution request identity mismatch")
    for field in ("protocol_id", "robot_run_id"):
        if row[field] is not None and request_data[field] != row[field]:
            raise ValueError("Resolution physical run identity mismatch")
    return {"command": current_data, "audit": {**audit, "request": request_data}}


def reconcile_resolutions(client: AcademyClient, journal: Journal) -> bool:
    for row in journal.unresolved():
        response = client.request("GET", f"/companion/commands/{row['id']}")
        audit = validate_resolution(row, response, client.credentials)
        if audit is not None:
            journal.record_resolution(row["id"], audit)
    return not journal.unresolved()


def run_supervised(
    client,
    engine,
    journal,
    profile,
    *,
    approve,
    once=False,
    clock=time.monotonic,
    sleep=time.sleep,
    probe_interval=120,
):
    """Refresh a genuinely observed idle probe before its 300-second server TTL."""
    if not 1 <= probe_interval <= 120:
        raise ValueError("Idle probe interval must be at most 120 seconds")
    next_probe = 0
    while True:
        now = clock()
        if now >= next_probe:
            engine.probe()
            client.probe(profile)
            next_probe = clock() + probe_interval
        run_once(client, engine, journal, profile, approve=approve)
        if once:
            return
        sleep(3)


def run_once(
    client: AcademyClient,
    engine: ProtocolEngine,
    journal: Journal,
    profile: RobotProfile,
    *,
    approve,
    poll_seconds=1.0,
) -> bool:
    recover(journal)
    client.flush(journal)
    if not reconcile_resolutions(client, journal):
        return False
    payload = client.request("POST", "/companion/command", json={})
    if payload is None:
        return False
    command = Command.model_validate(payload)
    if command.resolution is not None:
        raise ValueError("A resolved command cannot be claimed for execution")
    saved = command.model_dump(mode="json")
    if not journal.begin(saved):
        client.flush(journal)
        return False
    run_id = str(command.run_id)
    try:
        command.validate_binding(profile, client.credentials)
        compiled = compile_plan(command.plan, command.plan_hash, profile)

        def check_stop():
            try:
                current = client.request("GET", f"/companion/commands/{run_id}")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {401, 403}:
                    # An explicit rejection from the pinned Academy origin ends
                    # authority. Only the already-bound run may be stopped;
                    # receipt upload remains pending until separately reconciled.
                    return True
                raise
            authority_ended = current.get("status") != "claimed"
            current = Command.model_validate({**current, "status": "claimed"}).model_dump(
                mode="json"
            )
            # Reconciliation only grants a stop; it never grants a second dispatch.
            for key, value in saved.items():
                if key in {"stop_requested", "status", "version", "resolution"}:
                    continue
                if canonical({"value": current.get(key)}) != canonical({"value": value}):
                    raise ValueError("Cloud command binding changed while running")
            if (
                authority_ended
                or command.expires_at <= datetime.now(UTC)
                or profile.qualified_until <= datetime.now(UTC)
            ):
                return True
            command.validate_binding(profile, client.credentials)
            return bool(current.get("stop_requested"))

        result = engine.execute(
            compiled,
            approve=lambda: approve(command),
            phase=lambda phase, **ids: journal.phase(run_id, phase, **ids),
            stop_requested=check_stop,
            poll_seconds=poll_seconds,
        )
        journal.finish(run_id, receipt_for(saved, **result))
    except Exception as exc:
        # No raw response/URL/token is logged. Even HTTP errors can follow physical mutation.
        row = next(row for row in journal.unfinished() if row["id"] == run_id)
        if row["phase"] == "claimed":
            receipt = receipt_for(
                saved,
                outcome="failed",
                protocol_id=None,
                robot_run_id=None,
                completed_actions=0,
                stop_confirmed=False,
                detail=f"Local validation/approval failed before robot mutation ({type(exc).__name__})",
            )
        else:
            receipt = unknown_receipt(
                row,
                f"Robot outcome uncertain ({type(exc).__name__}); inspect and reconcile. No replay.",
            )
        journal.finish(run_id, receipt)
    client.flush(journal)
    return True
