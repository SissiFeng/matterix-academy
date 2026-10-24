"""Owner-scoped connector pairing and fail-closed physical command authority.

Pairing and read-only probes never grant motion authority. An operator qualification,
an approved connector release, and cleaned-up native evidence for the unchanged plan
are independent gates. Claimed commands are never automatically dispatched again.
"""

import hashlib
import secrets
import time
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, model_validator

from .models import StrictModel
from .native_studio import STUDIO
from .recipes import parse_plan
from .remote_run import RemoteRunRequest, RemoteRunSnapshot, check_run_snapshot, workflow_digest
from .runs import RUNS, WORKERS, RunService, revised, studio_issues
from .store import Conflict, Write

PAIRINGS = "system#connector-pairings"
INSTALLATIONS = "system#connector-installations"
QUALIFICATIONS = "system#connector-qualifications"
REAL_RUNS = "system#connector-runs"
DEVICE_LOCKS = "system#connector-device-locks"
PAIR_SECONDS = 600
CREDENTIAL_SECONDS = 30 * 86400
PROBE_SECONDS = 300
QUEUE_SECONDS = 300
COMMAND_SECONDS = 1800
BINDINGS = (
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
TERMINAL = {"completed", "failed", "stopped", "unknown"}


class ConnectionUpdate(StrictModel):
    expected_version: int = Field(ge=0, strict=True)
    instrument: Literal["flex", "ot2"]
    display_name: str = Field(min_length=1, max_length=80, pattern=r".*\S.*")
    platform: Literal["macos", "linux", "windows"]


class ConnectionRevision(StrictModel):
    expected_version: int = Field(ge=1, strict=True)


class PairRequest(StrictModel):
    code: str = Field(min_length=43, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    installation_id: UUID
    secret: str = Field(min_length=43, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class ConnectorProbe(StrictModel):
    instrument: Literal["flex", "ot2"]
    serial: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    release_id: str = Field(min_length=1, max_length=100)
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    profile_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    firmware: str = Field(min_length=1, max_length=80)
    runtime_contract_id: str = Field(min_length=1, max_length=128)
    runtime_release_id: str = Field(min_length=1, max_length=128)
    runtime_bundle_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    capabilities: list[Literal["protocol-engine"]] = Field(min_length=1, max_length=1)
    reachable: bool = Field(strict=True)


class RealRunRequest(ConnectionRevision):
    run_id: UUID
    session_id: UUID
    session_version: int = Field(ge=1, strict=True)
    native_run_id: UUID
    acknowledge_physical_motion: bool = Field(strict=True)


class ConnectorReceipt(StrictModel):
    command_id: UUID
    connection_id: UUID
    installation_id: UUID
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    instrument: Literal["flex", "ot2"]
    serial: str = Field(min_length=1, max_length=100)
    release_id: str = Field(min_length=1, max_length=100)
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    profile_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    firmware: str = Field(min_length=1, max_length=80)
    runtime_contract_id: str = Field(min_length=1, max_length=128)
    runtime_release_id: str = Field(min_length=1, max_length=128)
    runtime_bundle_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    outcome: Literal["completed", "failed", "stopped", "unknown"]
    protocol_id: str | None = Field(default=None, max_length=200)
    robot_run_id: str | None = Field(default=None, max_length=200)
    completed_actions: int = Field(ge=0, le=64, strict=True)
    stop_confirmed: bool = Field(
        strict=True, description="Observed terminal quiescence, including successful completion"
    )
    detail: str = Field(min_length=1, max_length=1000)


class ConnectorResolution(StrictModel):
    """Operator-attested offline evidence; deliberately has no learner/machine route."""

    expected_version: int = Field(ge=1, strict=True)
    resolution_id: UUID
    connection_id: UUID
    installation_id: UUID
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    instrument: Literal["flex", "ot2"]
    serial: str = Field(min_length=1, max_length=100)
    release_id: str = Field(min_length=1, max_length=100)
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    profile_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    firmware: str = Field(min_length=1, max_length=80)
    runtime_contract_id: str = Field(min_length=1, max_length=128)
    runtime_release_id: str = Field(min_length=1, max_length=128)
    runtime_bundle_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    protocol_id: str | None = Field(default=None, max_length=200)
    robot_run_id: str | None = Field(default=None, max_length=200)
    no_run_created: bool = Field(strict=True)
    stopped: bool = Field(strict=True)
    released: bool = Field(strict=True)
    operator_id: str = Field(min_length=1, max_length=200)
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    detail: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def observed_quiescence(self):
        if not self.stopped or not self.released:
            raise ValueError("Resolution requires verified stopped and released state")
        if self.no_run_created:
            if self.robot_run_id is not None:
                raise ValueError("A no-run-created report cannot identify an existing robot run")
        elif not self.protocol_id or not self.robot_run_id:
            raise ValueError("Identify the exact stopped Protocol Engine protocol and run")
        return self


def digest(value: str):
    return hashlib.sha256(value.encode()).hexdigest()


def connection_key(connection_id):
    return f"connection#{connection_id}"


class ConnectionService:
    def __init__(self, store, *, enabled=False, approved_release=None, clock=time.time):
        self.store, self.enabled, self.clock = store, enabled, clock
        self.approved_release = approved_release or (lambda instrument, platform: None)
        self.native = RunService(store, clock=clock)

    def raw(self, owner, connection_id):
        record = self.store.get(owner, connection_key(connection_id))
        if record is None:
            raise HTTPException(404, "Connection not found")
        return record

    def release(self, connection):
        release = self.approved_release(connection["instrument"], connection["platform"])
        if (
            not release
            or release.get("status") != "approved"
            or (
                release.get("instrument"),
                release.get("platform"),
                release.get("execution_transport"),
            )
            != (connection["instrument"], connection["platform"], "opentrons-protocol-engine")
        ):
            return None
        return release

    def qualification(self, connection, probe=None):
        probe = probe or connection.get("probe")
        qualification = self.store.get(QUALIFICATIONS, connection["id"])
        release = self.release(connection)
        if not probe or not qualification or not release:
            return None
        if (
            qualification.get("revoked", True)
            or qualification.get("expires_at", 0) <= self.clock()
            or qualification.get("connection_id") != connection["id"]
            or qualification.get("installation_id") != connection.get("installation_id")
            or qualification.get("owner") != connection["owner"]
            or any(qualification.get(key) != probe.get(key) for key in BINDINGS)
            or any(
                release.get(key) != probe.get(key)
                for key in (
                    "release_id",
                    "artifact_sha256",
                    "source_commit",
                    "instrument",
                    "runtime_contract_id",
                    "runtime_release_id",
                    "runtime_bundle_sha256",
                )
            )
            or probe.get("firmware") not in release.get("supported_firmware", [])
            or "protocol-engine" not in qualification.get("capabilities", [])
            or "protocol-engine" not in probe.get("capabilities", [])
        ):
            return None
        return qualification

    def public(self, connection):
        return {
            key: connection.get(key)
            for key in (
                "id",
                "version",
                "instrument",
                "display_name",
                "platform",
                "status",
                "created_at",
                "updated_at",
                "installation_id",
                "probe",
                "active_run_id",
            )
        } | {
            "qualified": self.qualification(connection) is not None,
            "approved_release": self.release(connection),
        }

    def list(self, owner):
        return {
            "connections": [
                self.get(owner, item["id"]) for item in self.store.partition(owner, "connection#")
            ]
        }

    def get(self, owner, connection_id):
        connection = self.raw(owner, connection_id)
        if connection.get("active_run_id"):
            self.expire(self.run_raw(connection["active_run_id"]))
        return self.public(self.raw(owner, connection_id))

    def save(self, owner, connection_id, data: ConnectionUpdate):
        key = connection_key(connection_id)
        old = self.store.get(owner, key)
        if data.expected_version != (old["version"] if old else 0):
            raise Conflict
        if old and (old.get("installation_id") or old.get("active_run_id")):
            raise HTTPException(409, "Revoke the existing installation before changing its setup")
        now = self.clock()
        record = {
            "id": str(connection_id),
            "owner": owner,
            "version": data.expected_version + 1,
            **data.model_dump(exclude={"expected_version"}),
            "status": "unpaired",
            "created_at": old["created_at"] if old else now,
            "updated_at": now,
            "installation_id": None,
            "probe": None,
            "active_run_id": None,
            "pairing_digest": None,
        }
        self.store.put(owner, key, record, old["version"] if old else None)
        return self.public(record)

    def pairing(self, owner, connection_id, data: ConnectionRevision):
        old = self.raw(owner, connection_id)
        if old["version"] != data.expected_version:
            raise Conflict
        if old.get("active_run_id") or old.get("installation_id"):
            raise HTTPException(409, "Revoke the current installation before pairing another")
        code = secrets.token_urlsafe(32)
        code_hash = digest(code)
        expiry = self.clock() + PAIR_SECONDS
        record = revised(old, status="pairing", pairing_digest=code_hash, updated_at=self.clock())
        pair = {
            "version": 1,
            "owner": owner,
            "connection_id": str(connection_id),
            "expires_at": expiry,
            "consumed": False,
        }
        self.store.transact(
            [
                Write(owner, connection_key(connection_id), record, old["version"]),
                Write(PAIRINGS, code_hash, pair, None),
            ]
        )
        return {"connection": self.public(record), "code": code, "expires_at": expiry}

    def redeem(self, data: PairRequest):
        code_hash = digest(data.code)
        pair = self.store.get(PAIRINGS, code_hash)
        installation_id = str(data.installation_id)
        token_hash = digest(f"{installation_id}.{data.secret}")
        if not pair:
            raise HTTPException(403, "Pairing code is invalid or expired")
        connection = self.raw(pair["owner"], pair["connection_id"])
        if pair["consumed"]:
            # Retry with the identical persisted machine secret recovers a lost response.
            existing = self.store.get(INSTALLATIONS, installation_id)
            if (
                pair.get("installation_id") == installation_id
                and existing
                and not existing["revoked"]
                and existing["credential_expires"] > self.clock()
                and connection.get("installation_id") == installation_id
                and secrets.compare_digest(existing["token_digest"], token_hash)
            ):
                return self.machine_public(existing, connection)
            raise HTTPException(403, "Pairing code has already been redeemed")
        if (
            pair["expires_at"] <= self.clock()
            or connection["status"] != "pairing"
            or connection.get("pairing_digest") != code_hash
            or connection.get("active_run_id")
        ):
            raise HTTPException(403, "Pairing code is invalid or expired")
        installation = {
            "version": 1,
            "installation_id": installation_id,
            "owner": pair["owner"],
            "connection_id": pair["connection_id"],
            "token_digest": token_hash,
            "credential_expires": self.clock() + CREDENTIAL_SECONDS,
            "revoked": False,
        }
        changed = revised(
            connection,
            status="paired",
            installation_id=installation_id,
            pairing_digest=None,
            updated_at=self.clock(),
        )
        self.store.transact(
            [
                Write(
                    PAIRINGS,
                    code_hash,
                    revised(pair, consumed=True, installation_id=installation_id),
                    pair["version"],
                ),
                Write(INSTALLATIONS, installation_id, installation, None),
                Write(
                    pair["owner"],
                    connection_key(pair["connection_id"]),
                    changed,
                    connection["version"],
                ),
            ]
        )
        return self.machine_public(installation, changed)

    def authenticate(self, authorization):
        if not authorization.startswith("Bearer "):
            raise HTTPException(403, "Companion credential is required")
        token = authorization[7:]
        installation_id, sep, secret = token.partition(".")
        if not sep or len(secret) < 43 or len(token) > 200:
            raise HTTPException(403, "Companion credential is required")
        installation = self.store.get(INSTALLATIONS, installation_id)
        if (
            not installation
            or installation.get("revoked", True)
            or installation.get("credential_expires", 0) <= self.clock()
            or not secrets.compare_digest(installation.get("token_digest", ""), digest(token))
        ):
            raise HTTPException(403, "Companion credential is invalid or revoked")
        connection = self.raw(installation["owner"], installation["connection_id"])
        if connection["status"] != "paired" or connection.get("installation_id") != installation_id:
            raise HTTPException(403, "Companion installation is no longer paired")
        return installation

    def machine_public(self, installation, connection=None):
        connection = connection or self.raw(installation["owner"], installation["connection_id"])
        return {
            "connection": self.public(connection),
            "installation_id": installation["installation_id"],
            "credential_expires": installation["credential_expires"],
        }

    def probe(self, installation, data: ConnectorProbe):
        old = self.raw(installation["owner"], installation["connection_id"])
        if data.instrument != old["instrument"]:
            raise HTTPException(409, "The observed instrument differs from this connection")
        changed = revised(
            old, probe={**data.model_dump(), "observed_at": self.clock()}, updated_at=self.clock()
        )
        self.store.transact(
            [
                Write(old["owner"], connection_key(old["id"]), changed, old["version"]),
                Write(
                    INSTALLATIONS,
                    installation["installation_id"],
                    installation,
                    installation["version"],
                ),
            ]
        )
        return self.machine_public(installation, changed)

    def revoke(self, owner, connection_id, data: ConnectionRevision):
        old = self.raw(owner, connection_id)
        if old["version"] != data.expected_version:
            raise Conflict
        changed = revised(
            old,
            status="revoked",
            installation_id=None,
            pairing_digest=None,
            probe=None,
            updated_at=self.clock(),
        )
        writes = [Write(owner, connection_key(connection_id), changed, old["version"])]
        if old.get("installation_id"):
            installation = self.store.get(INSTALLATIONS, old["installation_id"])
            writes.append(
                Write(
                    INSTALLATIONS,
                    old["installation_id"],
                    revised(installation, revoked=True),
                    installation["version"],
                )
            )
        if old.get("active_run_id"):
            run = self.run_raw(old["active_run_id"])
            if run["status"] not in TERMINAL:
                writes.append(
                    Write(
                        REAL_RUNS,
                        run["run_id"],
                        revised(
                            run,
                            status="unknown",
                            stop_requested=True,
                            reason="Installation revoked; physical outcome requires operator reconciliation",
                            updated_at=self.clock(),
                        ),
                        run["version"],
                    )
                )
        self.store.transact(writes)
        return self.public(changed)

    def native_evidence(self, owner, session, plan, native_run_id):
        """Return trusted durable evidence plus records to transactionally bind its gate."""
        if not native_run_id or plan.course_id != STUDIO:
            return None
        try:
            native = self.native.raw(native_run_id)
            worker = (
                self.store.get(WORKERS, native["worker_id"]) if native.get("worker_id") else None
            )
            pointer = self.store.get(owner, f"remote#{session['id']}")
            cleanup, binding = native.get("cleanup") or {}, native.get("binding") or {}
            if (
                native.get("owner") != owner
                or native.get("session_id") != session["id"]
                or native.get("status") != "completed"
                or native.get("plan_hash") != workflow_digest(plan)
                or native.get("plan") != plan.model_dump(mode="json")
                or not worker
                or not worker.get("qualified")
                or worker.get("revoked", True)
                or worker.get("credential_expires", 0) <= self.clock()
                or studio_issues(worker, plan) != []
                or not pointer
                or pointer.get("run_id") != str(native_run_id)
                or not pointer.get("released")
                or session.get("remote_active_run") is not None
                or not cleanup.get("reset_verified")
                or set(cleanup.get("checks", {}))
                != {"objects", "liquids", "tips", "controllers", "stopped"}
                or not all(cleanup["checks"].values())
                or cleanup.get("native_session_id") != binding.get("native_session_id")
                or cleanup.get("engine_version") != worker.get("engine_version")
                or cleanup.get("asset_version") != worker.get("asset_version")
                or not binding.get("native_session_id")
            ):
                return None
            snapshot = RemoteRunSnapshot.model_validate(native["snapshot"])
            if (
                snapshot.status != "completed"
                or snapshot.engine_version != worker["engine_version"]
                or snapshot.asset_version != worker["asset_version"]
            ):
                return None
            check_run_snapshot(
                snapshot,
                UUID(binding["native_session_id"]),
                RemoteRunRequest(
                    run_id=native_run_id,
                    expected_revision=binding["expected_revision"],
                    experiment=plan,
                    plan_hash=workflow_digest(plan),
                ),
            )
            return native, worker, pointer
        except (HTTPException, KeyError, TypeError, ValueError):
            return None

    def preflight(self, owner, connection_id, session_id, native_run_id=None):
        connection = self.raw(owner, connection_id)
        session = self.store.get(owner, f"session#{session_id}")
        if not session:
            raise HTTPException(404, "Experiment not found")
        plan = parse_plan(session["experiment"])
        pointer = self.store.get(owner, f"remote#{session_id}")
        native_run_id = str(native_run_id) if native_run_id else (pointer or {}).get("run_id")
        issues = []

        def issue(code, message):
            issues.append({"code": code, "message": message})

        if not self.enabled:
            issue("execution_disabled", "Physical execution has not been enabled by the operator")
        instrument = getattr(plan, "instrument", "flex")
        if connection["instrument"] != "flex" or instrument != "flex":
            issue("native_unsupported", "OT-2 native workflow acceptance is not available yet")
        if plan.course_id != STUDIO or instrument != connection["instrument"]:
            issue("workflow", "Save a matching Workflow Studio plan for this instrument")
        if connection["status"] != "paired":
            issue("not_paired", "Pair the local companion with this connection")
        installation = (
            self.store.get(INSTALLATIONS, connection["installation_id"])
            if connection.get("installation_id")
            else None
        )
        if (
            not installation
            or installation.get("revoked", True)
            or installation.get("credential_expires", 0) <= self.clock()
        ):
            issue("credential", "The paired installation needs a current companion credential")
        if not self.release(connection):
            issue("release", "No approved connector release is available for this platform")
        probe = connection.get("probe") or {}
        if not probe.get("reachable") or self.clock() - probe.get("observed_at", 0) > PROBE_SECONDS:
            issue("probe", "Run a fresh read-only connection check on the lab computer")
        if not self.qualification(connection):
            issue(
                "qualification",
                "An operator must qualify the exact robot, connector and local profile",
            )
        if connection.get("active_run_id"):
            self.expire(self.run_raw(connection["active_run_id"]))
            issue("device_locked", "This connection has an active or unresolved physical run")
        if probe.get("serial"):
            lock = self.store.get(
                DEVICE_LOCKS, digest(f"{connection['instrument']}:{probe['serial']}")
            )
            if lock and lock.get("active_run_id"):
                issue("device_locked", "This robot has an active or unresolved physical run")
        if session.get("status") == "running" or session.get("remote_active_run"):
            issue(
                "session_busy", "Finish and reset the current simulation before physical execution"
            )
        if not self.native_evidence(owner, session, plan, native_run_id):
            issue(
                "native_evidence",
                "The unchanged plan needs completed qualified Matterix native evidence and verified reset",
            )
        return {
            "ready": not issues,
            "enabled": self.enabled,
            "connection_id": str(connection_id),
            "session_id": str(session_id),
            "session_version": session["version"],
            "plan_hash": workflow_digest(plan),
            "native_run_id": native_run_id,
            "issues": issues,
        }

    def run_raw(self, run_id):
        run = self.store.get(REAL_RUNS, str(run_id))
        if not run:
            raise HTTPException(404, "Physical run not found")
        return run

    def expire(self, run):
        reason = None
        if run["status"] in {"queued", "claimed"}:
            if run["expires_at"] <= self.clock():
                reason = "Companion command expired; do not replay it"
            else:
                connection = self.raw(run["owner"], run["connection_id"])
                probe = connection.get("probe") or {}
                if (
                    not self.enabled
                    or connection.get("installation_id") != run["installation_id"]
                    or not self.qualification(connection)
                    or any(probe.get(key) != run[key] for key in BINDINGS)
                ):
                    reason = "Physical authorization changed; stop requested and operator reconciliation required"
        if reason:
            changed = revised(
                run,
                status="unknown",
                stop_requested=True,
                reason=reason,
                updated_at=self.clock(),
            )
            try:
                self.store.put(REAL_RUNS, run["run_id"], changed, run["version"])
                return changed
            except Conflict:
                return self.run_raw(run["run_id"])
        return run

    def run_public(self, run):
        return {
            key: run.get(key)
            for key in (
                "run_id",
                "connection_id",
                "version",
                "status",
                "session_id",
                "native_run_id",
                "plan_hash",
                "instrument",
                "created_at",
                "updated_at",
                "stop_requested",
                "receipt",
                "reason",
                "resolution",
            )
        }

    def get_run(self, owner, connection_id, run_id):
        self.raw(owner, connection_id)
        run = self.run_raw(run_id)
        if run["owner"] != owner or run["connection_id"] != str(connection_id):
            raise HTTPException(404, "Physical run not found")
        return self.run_public(self.expire(run))

    def submit(self, owner, connection_id, data: RealRunRequest):
        connection = self.raw(owner, connection_id)
        old = self.store.get(REAL_RUNS, str(data.run_id))
        request = data.model_dump(mode="json")
        if old:
            if (
                old["owner"] == owner
                and old["connection_id"] == str(connection_id)
                and old["request"] == request
            ):
                return self.run_public(self.expire(old))
            raise Conflict
        session = self.store.get(owner, f"session#{data.session_id}")
        if (
            connection["version"] != data.expected_version
            or not session
            or session["version"] != data.session_version
        ):
            raise Conflict
        if not data.acknowledge_physical_motion:
            raise HTTPException(422, "Explicit acknowledgement of physical motion is required")
        report = self.preflight(owner, connection_id, data.session_id, data.native_run_id)
        if not report["ready"]:
            raise HTTPException(
                409, {"message": "Physical execution is blocked", "issues": report["issues"]}
            )
        plan = parse_plan(session["experiment"])
        native, worker, pointer = self.native_evidence(
            owner, session, plan, str(data.native_run_id)
        )
        qualification = self.qualification(connection)
        probe = connection["probe"]
        installation = self.store.get(INSTALLATIONS, connection["installation_id"])
        lock_key = digest(f"{connection['instrument']}:{probe['serial']}")
        lock = self.store.get(DEVICE_LOCKS, lock_key)
        if lock and lock.get("active_run_id"):
            raise Conflict
        now = self.clock()
        run = {
            "version": 1,
            "run_id": str(data.run_id),
            "owner": owner,
            "connection_id": str(connection_id),
            "installation_id": connection["installation_id"],
            "request": request,
            "session_id": str(data.session_id),
            "native_run_id": str(data.native_run_id),
            "plan": plan.model_dump(mode="json"),
            "plan_hash": report["plan_hash"],
            **{key: probe[key] for key in BINDINGS},
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "expires_at": now + QUEUE_SECONDS,
            "stop_requested": False,
            "receipt": None,
            "reason": None,
            "lock_key": lock_key,
        }
        changed = revised(connection, active_run_id=run["run_id"], updated_at=now)
        self.store.transact(
            [
                Write(owner, connection_key(connection_id), changed, connection["version"]),
                Write(REAL_RUNS, run["run_id"], run, None),
                Write(
                    DEVICE_LOCKS,
                    lock_key,
                    {
                        "version": (lock["version"] if lock else 0) + 1,
                        "active_run_id": run["run_id"],
                    },
                    lock["version"] if lock else None,
                ),
                Write(owner, f"session#{data.session_id}", session, session["version"]),
                Write(RUNS, native["run_id"], native, native["version"]),
                Write(WORKERS, worker["worker_id"], worker, worker["version"]),
                Write(owner, f"remote#{data.session_id}", pointer, pointer["version"]),
                Write(QUALIFICATIONS, connection["id"], qualification, qualification["version"]),
                Write(
                    INSTALLATIONS,
                    installation["installation_id"],
                    installation,
                    installation["version"],
                ),
            ]
        )
        return self.run_public(run)

    def command_public(self, run):
        return {
            key: run.get(key)
            for key in (
                "run_id",
                "connection_id",
                "installation_id",
                "version",
                "plan_hash",
                "plan",
                *BINDINGS,
                "expires_at",
                "status",
                "stop_requested",
                "resolution",
            )
        }

    def machine_run(self, installation, run_id):
        run = self.run_raw(run_id)
        if (
            run["installation_id"] != installation["installation_id"]
            or run["owner"] != installation["owner"]
        ):
            raise HTTPException(404, "Physical run not found")
        return self.expire(run)

    def claim(self, installation):
        connection = self.raw(installation["owner"], installation["connection_id"])
        if not connection.get("active_run_id"):
            return None
        run = self.machine_run(installation, connection["active_run_id"])
        if run["status"] != "queued":
            return None
        # Recheck revocable authority at dispatch, not only at browser submission.
        qualification = self.qualification(connection)
        session = self.store.get(run["owner"], f"session#{run['session_id']}")
        probe = connection.get("probe") or {}
        native = (
            self.native_evidence(
                run["owner"], session, parse_plan(run["plan"]), run["native_run_id"]
            )
            if session
            else None
        )
        if (
            not self.enabled
            or not qualification
            or not native
            or not probe.get("reachable")
            or self.clock() - probe.get("observed_at", 0) > PROBE_SECONDS
            or any(probe.get(key) != run[key] for key in BINDINGS)
            or workflow_digest(parse_plan(session["experiment"])) != run["plan_hash"]
        ):
            changed = revised(
                run,
                status="unknown",
                reason="Dispatch authority changed; operator reconciliation is required",
                updated_at=self.clock(),
            )
            self.store.put(REAL_RUNS, run["run_id"], changed, run["version"])
            return None
        changed = revised(
            run,
            status="claimed",
            expires_at=self.clock() + COMMAND_SECONDS,
            updated_at=self.clock(),
        )
        native_run, worker, pointer = native
        try:
            self.store.transact(
                [
                    Write(REAL_RUNS, run["run_id"], changed, run["version"]),
                    Write(
                        INSTALLATIONS,
                        installation["installation_id"],
                        installation,
                        installation["version"],
                    ),
                    Write(
                        run["owner"],
                        connection_key(connection["id"]),
                        connection,
                        connection["version"],
                    ),
                    Write(
                        QUALIFICATIONS, connection["id"], qualification, qualification["version"]
                    ),
                    Write(
                        run["owner"], f"session#{run['session_id']}", session, session["version"]
                    ),
                    Write(RUNS, native_run["run_id"], native_run, native_run["version"]),
                    Write(WORKERS, worker["worker_id"], worker, worker["version"]),
                    Write(run["owner"], f"remote#{run['session_id']}", pointer, pointer["version"]),
                ]
            )
        except Conflict:
            return None
        return self.command_public(changed)

    def unlock_writes(self, run):
        connection = self.raw(run["owner"], run["connection_id"])
        lock = self.store.get(DEVICE_LOCKS, run["lock_key"])
        if (
            connection.get("active_run_id") != run["run_id"]
            or not lock
            or lock.get("active_run_id") != run["run_id"]
        ):
            raise Conflict
        return [
            Write(
                run["owner"],
                connection_key(run["connection_id"]),
                revised(connection, active_run_id=None, updated_at=self.clock()),
                connection["version"],
            ),
            Write(
                DEVICE_LOCKS, run["lock_key"], revised(lock, active_run_id=None), lock["version"]
            ),
        ]

    def stop(self, owner, connection_id, run_id, data: ConnectionRevision):
        self.get_run(owner, connection_id, run_id)
        run = self.run_raw(run_id)
        if run["version"] != data.expected_version:
            raise Conflict
        if run["status"] in {"completed", "failed", "stopped"}:
            return self.run_public(run)
        changed = revised(run, stop_requested=True, updated_at=self.clock())
        writes = []
        if run["status"] == "queued":
            changed.update(
                status="stopped", reason="Cancelled before the companion claimed the command"
            )
            writes = self.unlock_writes(run)
        self.store.transact([Write(REAL_RUNS, run["run_id"], changed, run["version"]), *writes])
        return self.run_public(changed)

    def receipt(self, installation, run_id, data: ConnectorReceipt):
        run = self.machine_run(installation, run_id)
        payload = data.model_dump(mode="json")
        if run.get("receipt"):
            if run["receipt"] == payload:
                return self.run_public(run)
            raise Conflict
        if (
            run["status"] not in {"claimed", "unknown"}
            or str(data.command_id) != str(run_id)
            or str(data.connection_id) != run["connection_id"]
            or str(data.installation_id) != run["installation_id"]
            or data.plan_hash != run["plan_hash"]
            or any(payload[key] != run[key] for key in BINDINGS)
        ):
            raise Conflict
        if data.completed_actions > len(run["plan"]["actions"]) or (
            data.outcome == "completed"
            and (
                data.completed_actions != len(run["plan"]["actions"])
                or not data.protocol_id
                or not data.robot_run_id
                or not data.stop_confirmed
            )
        ):
            raise HTTPException(
                422, "Completion requires all planned actions and stopped Protocol Engine evidence"
            )
        status = data.outcome if data.stop_confirmed and data.outcome != "unknown" else "unknown"
        # A late receipt is useful for reconciliation but cannot automatically clear
        # an unknown lock after loss of command liveness.
        if run["status"] == "unknown":
            status = "unknown"
        changed = revised(run, status=status, receipt=payload, updated_at=self.clock())
        writes = self.unlock_writes(run) if status != "unknown" else []
        self.store.transact(
            [
                Write(REAL_RUNS, run["run_id"], changed, run["version"]),
                Write(
                    INSTALLATIONS,
                    installation["installation_id"],
                    installation,
                    installation["version"],
                ),
                *writes,
            ]
        )
        return self.run_public(changed)

    def resolve_unknown(self, run_id, data: ConnectorResolution):
        """Administrative CLI only: preserve unknown history while releasing its lock.

        The privileged caller must inspect the physical instrument and validate the
        local evidence report before invoking this method. Hashing an assertion is
        not hardware verification. No browser or companion endpoint calls this.
        """
        run = self.run_raw(run_id)
        payload = data.model_dump(mode="json")
        if run.get("resolution"):
            if run["resolution"]["request"] == payload:
                return self.run_public(run)
            raise Conflict
        if run["version"] != data.expected_version or run["status"] != "unknown":
            raise Conflict
        if (
            str(data.connection_id) != run["connection_id"]
            or str(data.installation_id) != run["installation_id"]
            or data.plan_hash != run["plan_hash"]
            or any(payload[key] != run[key] for key in BINDINGS)
        ):
            raise Conflict
        receipt = run.get("receipt") or {}
        for field in ("protocol_id", "robot_run_id"):
            if receipt.get(field) is not None and receipt[field] != payload[field]:
                raise Conflict
        audit = {
            "request": payload,
            "resolved_at": self.clock(),
            "historical_status": "unknown",
            "replay_authorized": False,
        }
        changed = revised(run, resolution=audit, updated_at=self.clock())
        self.store.transact(
            [
                Write(REAL_RUNS, run["run_id"], changed, run["version"]),
                *self.unlock_writes(run),
            ]
        )
        return self.run_public(changed)
