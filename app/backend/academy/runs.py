"""Durable dispatch authority. Simulator outcomes only come from qualified workers.

Claims never automatically requeue in v1. A missing report is not evidence that
the simulator did nothing. Terminal outcomes retain the session lock until an
explicit, version-bound cleanup receipt verifies reset.
"""

import copy
import hashlib
import secrets
import time
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, model_validator

from .learning import readiness
from .models import StrictModel
from .native_plan import FIRST_TRANSFER, TransferCapability, intent_for, preflight
from .recipes import MIXING, parse_plan
from .remote_run import RemoteRunRequest, RemoteRunSnapshot, check_run_snapshot, workflow_digest
from .store import Conflict, Write

RUNS = "system#runs"
WORKERS = "system#workers"
QUEUE = "system#queue"
TERMINAL = {"completed", "failed", "cancelled", "outcome_unknown"}
LEASE_SECONDS = 60
MAX_RUN_SECONDS = 1800


class SubmitRun(StrictModel):
    run_id: UUID
    session_id: UUID
    expected_version: int = Field(ge=1)


class RunControl(StrictModel):
    command_id: UUID
    expected_version: int = Field(ge=1)
    action: Literal["pause", "resume", "cancel"]


class LeaseRequest(StrictModel):
    claim_token: str = Field(min_length=32, max_length=128)


class StartRequest(LeaseRequest):
    command_id: UUID


class BindRequest(LeaseRequest):
    native_session_id: UUID
    expected_revision: int = Field(ge=1)
    engine_version: str = Field(min_length=1, max_length=100)
    asset_version: str = Field(min_length=1, max_length=100)


class SnapshotRequest(LeaseRequest):
    snapshot: RemoteRunSnapshot
    control_id: UUID | None = None


class UnknownRequest(LeaseRequest):
    reason: str = Field(min_length=1, max_length=500)


class CleanupRequest(LeaseRequest):
    command_id: UUID
    reset_verified: bool
    native_session_id: UUID | None
    engine_version: str = Field(min_length=1, max_length=100)
    asset_version: str = Field(min_length=1, max_length=100)
    checks: dict[Literal["objects", "liquids", "tips", "controllers", "stopped"], bool]

    @model_validator(mode="after")
    def complete_reset_evidence(self):
        if self.reset_verified and (
            set(self.checks) != {"objects", "liquids", "tips", "controllers", "stopped"}
            or not all(self.checks.values())
        ):
            raise ValueError("Verified reset requires every native cleanup check")
        return self


def revised(record: dict, **changes) -> dict:
    return {**copy.deepcopy(record), **changes, "version": record["version"] + 1}


def transfer_issues(worker, plan) -> list | None:
    """Preflight issues for this worker's declared scene, or None when it declares none."""
    declared = (worker.get("capabilities") or {}).get(FIRST_TRANSFER)
    if not declared:
        return None
    return preflight(intent_for(plan), TransferCapability.model_validate(declared))


def worker_credential(store, authorization: str, now=None):
    """Bind a high-entropy token to its registered machine, without logging it."""
    if not authorization.startswith("Bearer "):
        return None
    token = authorization[7:]
    worker_id, separator, secret = token.partition(".")
    if not separator or len(secret) < 32 or len(worker_id) > 64:
        return None
    worker = store.get(WORKERS, worker_id)
    if (
        not worker
        or worker.get("revoked", True)
        or worker.get("credential_expires", 0) <= (now if now is not None else time.time())
        or not secrets.compare_digest(
            worker.get("token_digest", ""), hashlib.sha256(token.encode()).hexdigest()
        )
    ):
        return None
    return worker


class RunService:
    def __init__(self, store, enabled=False, clock=time.time):
        self.store = store
        self.enabled = enabled
        self.clock = clock

    def raw(self, run_id):
        record = self.store.get(RUNS, str(run_id))
        if record is None:
            raise HTTPException(404, "Run not found")
        return record

    def public(self, run):
        snapshot = run.get("snapshot")
        worker = self.store.get(WORKERS, run["worker_id"]) if run.get("worker_id") else None
        return {
            key: run.get(key)
            for key in (
                "run_id",
                "session_id",
                "version",
                "status",
                "plan_hash",
                "created_at",
                "updated_at",
                "snapshot",
                "control",
                "cleanup",
                "reason",
            )
        } | {
            "evidence": "native" if snapshot else "pending",
            "completed_steps": sum(s["status"] == "completed" for s in snapshot["steps"])
            if snapshot
            else 0,
            "total_steps": len(run["plan"]["actions"]),
            "stale_seconds": max(0, int(self.clock() - run["updated_at"])),
            "supported_controls": worker.get("controls", [])
            if worker and not worker.get("revoked")
            else [],
        }

    def get(self, owner, run_id):
        run = self.raw(run_id)
        if run["owner"] != owner:
            raise HTTPException(404, "Run not found")
        return self.public(run)

    def for_session(self, owner, session_id):
        session = self.store.get(owner, f"session#{session_id}")
        if session is None:
            raise HTTPException(404, "Experiment not found")
        pointer = self.store.get(owner, f"remote#{session_id}")
        return self.get(owner, pointer["run_id"]) if pointer else None

    def submit(self, owner, data: SubmitRun):
        run_id, session_id = str(data.run_id), str(data.session_id)
        existing = self.store.get(RUNS, run_id)
        if existing:
            if (existing["owner"], existing["session_id"], existing["submitted_version"]) != (
                owner,
                session_id,
                data.expected_version,
            ):
                raise Conflict
            return self.public(existing)
        if not self.enabled:
            raise HTTPException(503, "Native execution awaits Ubuntu qualification")
        session = self.store.get(owner, f"session#{session_id}")
        if not session:
            raise HTTPException(404, "Experiment not found")
        if session["version"] != data.expected_version or session["status"] == "running":
            raise Conflict
        plan = parse_plan(session["experiment"])
        if plan.course_id not in {"flex-first-transfer", MIXING}:
            raise HTTPException(422, "Only the qualified first-transfer scene is supported")
        if plan.course_id == "flex-first-transfer" and not readiness(session)["ready"]:
            raise HTTPException(
                409, "Complete lesson preparation and prediction before native execution"
            )
        if plan.course_id == FIRST_TRANSFER:
            self.check_supported(plan)
        pointer = self.store.get(owner, f"remote#{session_id}")
        if pointer and not pointer["released"]:
            raise HTTPException(
                409, "The previous run still owns this session; verified cleanup is required"
            )
        now = self.clock()
        run = {
            "version": 1,
            "run_id": run_id,
            "session_id": session_id,
            "owner": owner,
            "submitted_version": data.expected_version,
            "plan": plan.model_dump(mode="json"),
            "plan_hash": workflow_digest(plan),
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "snapshot": None,
            "control": None,
            "cleanup": None,
            "queue_key": f"{now:020.6f}#{run_id}",
        }
        lock = {
            "version": (pointer["version"] if pointer else 0) + 1,
            "run_id": run_id,
            "released": False,
        }
        self.store.transact(
            [
                Write(
                    owner,
                    f"session#{session_id}",
                    revised(session, remote_active_run=run_id),
                    session["version"],
                ),
                Write(owner, f"remote#{session_id}", lock, pointer["version"] if pointer else None),
                Write(RUNS, run_id, run, None),
                Write(QUEUE, run["queue_key"], {"version": 1, "run_id": run_id}, None),
            ]
        )
        return self.public(run)

    def check_supported(self, plan):
        """Reject a learner plan no qualified scene can run exactly as saved."""
        declared = [
            worker
            for worker in self.store.partition(WORKERS)
            if worker.get("qualified")
            and not worker.get("revoked", True)
            and FIRST_TRANSFER in worker.get("scenes", [])
        ]
        if not declared:
            raise HTTPException(503, "No qualified simulation host supports this lesson yet")
        closest = None
        for worker in declared:
            issues = transfer_issues(worker, plan)
            if issues == []:
                return
            if issues and (closest is None or len(issues) < len(closest)):
                closest = issues
        if closest is None:
            raise HTTPException(503, "No qualified simulation host declares this lesson's scene")
        raise HTTPException(
            422,
            {
                "message": "The simulation scene cannot run this plan exactly as saved",
                "issues": [issue.model_dump() for issue in closest],
            },
        )

    def worker(self, worker_id):
        worker = self.store.get(WORKERS, worker_id)
        if (
            not worker
            or worker.get("revoked", True)
            or worker.get("credential_expires", 0) <= self.clock()
        ):
            raise HTTPException(403, "Worker credential is inactive")
        return worker

    def claim(self, worker_id):
        worker = self.worker(worker_id)
        if not self.enabled or not worker.get("qualified"):
            raise HTTPException(403, "Native worker qualification is required")
        if worker.get("active_run"):
            # Recover a lost claim response; never assign a second instance/run.
            return self.machine_view(self.raw(worker["active_run"]), worker_id)
        if worker["state"] != "ready":
            return None
        target = self.store.get("system#targets", f"sim:{worker_id}")
        if target and target.get("reservation"):
            # Reserved by a sim-to-real run; never interleave a learner run on that runtime.
            return None
        for candidate in self.store.partition(QUEUE):
            run = self.raw(candidate["run_id"])
            if run["status"] != "queued":
                continue
            if run["plan"]["course_id"] not in worker.get("scenes", []):
                continue
            if run["plan"]["course_id"] == FIRST_TRANSFER and (
                transfer_issues(worker, parse_plan(run["plan"])) != []
            ):
                # Another qualified scene may support this exact plan; never adapt it here.
                continue
            now = self.clock()
            claimed = revised(
                run,
                status="claimed",
                worker_id=worker_id,
                claim_token=secrets.token_urlsafe(32),
                lease_expires=now + LEASE_SECONDS,
                deadline=now + MAX_RUN_SECONDS,
                updated_at=now,
                runtime_manifest={
                    "engine_version": worker["engine_version"],
                    "asset_version": worker["asset_version"],
                },
            )
            updated_worker = revised(worker, state="busy", active_run=run["run_id"], last_seen=now)
            try:
                self.store.transact(
                    [
                        Write(RUNS, run["run_id"], claimed, run["version"]),
                        Write(WORKERS, worker_id, updated_worker, worker["version"]),
                        Write(QUEUE, run["queue_key"], None, 1),
                    ]
                )
            except Conflict:
                # Caller repeats a read/claim; no simulator call has happened.
                raise HTTPException(
                    409, "Claim changed; read worker state before continuing"
                ) from None
            return self.machine_view(claimed, worker_id)
        return None

    def machine_view(self, run, worker_id):
        if run.get("worker_id") != worker_id:
            raise HTTPException(403, "This run belongs to a different worker")
        return {
            key: value
            for key, value in run.items()
            if key not in {"owner", "submitted_version", "queue_key"}
        }

    def owned(self, worker_id, run_id, token, live=True):
        worker, run = self.worker(worker_id), self.raw(run_id)
        if run.get("worker_id") != worker_id or not secrets.compare_digest(
            run.get("claim_token", ""), token
        ):
            raise HTTPException(403, "Invalid run lease")
        if live and (run["lease_expires"] <= self.clock() or run["deadline"] <= self.clock()):
            raise HTTPException(409, "Lease expired; do not start or resume simulator actions")
        return worker, run

    def commit_machine(self, worker, old, new, **worker_changes):
        self.store.transact(
            [
                Write(RUNS, old["run_id"], new, old["version"]),
                Write(
                    WORKERS,
                    worker["worker_id"],
                    revised(worker, **worker_changes),
                    worker["version"],
                ),
            ]
        )
        return self.machine_view(new, worker["worker_id"])

    def start(self, worker_id, run_id, data: StartRequest):
        worker, run = self.owned(worker_id, run_id, data.claim_token)
        if not self.enabled or not worker.get("qualified"):
            raise HTTPException(403, "Native execution is not qualified")
        if run.get("start_command_id") == str(data.command_id):
            return self.machine_view(run, worker_id)
        if run["status"] != "claimed":
            raise HTTPException(409, "A run can receive only one start grant")
        return self.commit_machine(
            worker,
            run,
            revised(
                run,
                status="starting",
                start_command_id=str(data.command_id),
                updated_at=self.clock(),
            ),
        )

    def bind(self, worker_id, run_id, data: BindRequest):
        worker, run = self.owned(worker_id, run_id, data.claim_token)
        if not worker.get("qualified") or (data.engine_version, data.asset_version) != (
            worker["engine_version"],
            worker["asset_version"],
        ):
            raise HTTPException(409, "Observed runtime does not match worker qualification")
        binding = {
            "native_session_id": str(data.native_session_id),
            "expected_revision": data.expected_revision,
        }
        if run.get("binding") == binding:
            return self.machine_view(run, worker_id)
        if run["status"] != "starting" or run.get("binding"):
            raise Conflict
        return self.commit_machine(
            worker, run, revised(run, binding=binding, updated_at=self.clock())
        )

    def heartbeat(self, worker_id, run_id, data: LeaseRequest):
        worker, run = self.owned(worker_id, run_id, data.claim_token)
        if run["status"] in TERMINAL:
            return self.machine_view(run, worker_id)
        now = self.clock()
        return self.commit_machine(
            worker,
            run,
            revised(run, lease_expires=min(now + LEASE_SECONDS, run["deadline"])),
            last_seen=now,
        )

    def snapshot(self, worker_id, run_id, data: SnapshotRequest):
        worker, run = self.owned(worker_id, run_id, data.claim_token, live=False)
        payload = data.snapshot.model_dump(mode="json")
        # A lost acknowledgement of the final write must remain recoverable.
        duplicate_ack = not data.control_id or (
            run.get("control")
            and run["control"]["command_id"] == str(data.control_id)
            and run["control"]["acknowledged"]
        )
        saved = (
            RemoteRunSnapshot.model_validate(run["snapshot"]).model_dump(mode="json")
            if run.get("snapshot")
            else None
        )
        if payload == saved and duplicate_ack:
            return self.machine_view(run, worker_id)
        self.owned(worker_id, run_id, data.claim_token)
        if run["status"] in TERMINAL or not run.get("binding"):
            raise Conflict
        if (
            data.snapshot.engine_version != worker["engine_version"]
            or data.snapshot.asset_version != worker["asset_version"]
        ):
            raise HTTPException(409, "Worker runtime differs from its qualified manifest")
        request = RemoteRunRequest(
            run_id=run_id,
            expected_revision=run["binding"]["expected_revision"],
            experiment=run["plan"],
            plan_hash=run["plan_hash"],
        )
        previous = (
            RemoteRunSnapshot.model_validate(run["snapshot"]) if run.get("snapshot") else None
        )
        try:
            check_run_snapshot(
                data.snapshot, UUID(run["binding"]["native_session_id"]), request, previous
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        status = {"loading": "starting", "queued": "starting", "unknown": "outcome_unknown"}.get(
            data.snapshot.status, data.snapshot.status
        )
        control = run.get("control")
        if data.control_id:
            if not control or control["command_id"] != str(data.control_id):
                raise Conflict
            if control["action"] == "cancel":
                # Cancellation may only be acknowledged after runtime is stopped.
                if status not in {"paused", "completed", "failed"}:
                    raise Conflict
                status = "cancelled" if status == "paused" else status
            elif status not in {"completed", "failed"} and (control["action"], status) not in {
                ("pause", "paused"),
                ("resume", "running"),
            }:
                raise Conflict
            control = {**control, "acknowledged": True}
        elif control and not control["acknowledged"] and status not in TERMINAL:
            status = f"{control['action']}_requested"
        return self.commit_machine(
            worker,
            run,
            revised(run, snapshot=payload, status=status, control=control, updated_at=self.clock()),
        )

    def control(self, owner, run_id, data: RunControl):
        run = self.raw(run_id)
        if run["owner"] != owner:
            raise HTTPException(404, "Run not found")
        command_key = f"control#{run_id}#{data.command_id}"
        receipt = self.store.get(owner, command_key)
        fingerprint = data.model_dump(mode="json")
        if receipt:
            if receipt["request"] != fingerprint:
                raise Conflict
            return self.public(run)
        if run["version"] != data.expected_version or run["status"] in TERMINAL:
            raise Conflict
        if run.get("control") and not run["control"]["acknowledged"]:
            raise Conflict
        allowed = {
            "pause": {"running"},
            "resume": {"paused"},
            "cancel": {"queued", "running", "paused"},
        }
        if run["status"] not in allowed[data.action]:
            raise Conflict
        if run.get("worker_id"):
            worker = self.worker(run["worker_id"])
            if data.action not in worker.get("controls", []):
                raise HTTPException(422, "This runtime has not qualified this control")
        queued = run["status"] == "queued"
        command = {
            "command_id": str(data.command_id),
            "action": data.action,
            "acknowledged": queued,
        }
        changed = revised(
            run,
            status="cancelled" if queued else f"{data.action}_requested",
            control=command,
            updated_at=self.clock(),
        )
        writes = [
            Write(RUNS, run["run_id"], changed, run["version"]),
            Write(owner, command_key, {"version": 1, "request": fingerprint}, None),
        ]
        if queued:
            writes.append(Write(QUEUE, run["queue_key"], None, 1))
            writes.extend(self.release_lock(run))
            changed["cleanup"] = {
                "reset_verified": True,
                "reason": "Never claimed; no runtime allocated",
            }
        self.store.transact(writes)
        return self.public(changed)

    def unknown(self, worker_id, run_id, data: UnknownRequest):
        worker, run = self.owned(worker_id, run_id, data.claim_token, live=False)
        if run["status"] in TERMINAL:
            if worker["state"] == "quarantined":
                return self.machine_view(run, worker_id)
            return self.commit_machine(
                worker, run, revised(run, reason=data.reason), state="quarantined"
            )
        return self.commit_machine(
            worker,
            run,
            revised(run, status="outcome_unknown", reason=data.reason, updated_at=self.clock()),
            state="quarantined",
        )

    def release_lock(self, run):
        owner, session_id = run["owner"], run["session_id"]
        lock = self.store.get(owner, f"remote#{session_id}")
        session = self.store.get(owner, f"session#{session_id}")
        if (
            not lock
            or lock["run_id"] != run["run_id"]
            or lock["released"]
            or not session
            or session.get("remote_active_run") != run["run_id"]
        ):
            raise Conflict
        return [
            Write(owner, f"remote#{session_id}", revised(lock, released=True), lock["version"]),
            Write(
                owner,
                f"session#{session_id}",
                revised(session, remote_active_run=None),
                session["version"],
            ),
        ]

    def cleanup(self, worker_id, run_id, data: CleanupRequest):
        worker, run = self.owned(worker_id, run_id, data.claim_token, live=False)
        receipt = data.model_dump(mode="json", exclude={"claim_token"})
        if run.get("cleanup"):
            if run["cleanup"] == receipt:
                return self.machine_view(run, worker_id)
            if (
                run["cleanup"].get("reset_verified")
                or run["cleanup"]["command_id"] == receipt["command_id"]
            ):
                raise Conflict
        if run["status"] not in TERMINAL or worker.get("active_run") != str(run_id):
            raise Conflict
        if (data.engine_version, data.asset_version) != (
            worker["engine_version"],
            worker["asset_version"],
        ):
            raise Conflict
        if str(data.native_session_id) != str(run.get("binding", {}).get("native_session_id")):
            raise Conflict
        verified = (
            data.reset_verified
            and set(data.checks) == {"objects", "liquids", "tips", "controllers", "stopped"}
            and all(data.checks.values())
        )
        changed = revised(run, cleanup=receipt, updated_at=self.clock())
        writes = [
            Write(RUNS, run["run_id"], changed, run["version"]),
            Write(
                WORKERS,
                worker_id,
                revised(
                    worker,
                    state="ready" if verified else "quarantined",
                    active_run=None if verified else run["run_id"],
                ),
                worker["version"],
            ),
        ]
        if verified:
            writes.extend(self.release_lock(run))
        self.store.transact(writes)
        return self.machine_view(changed, worker_id)

    def reap(self):
        changed = 0
        for worker in self.store.partition(WORKERS):
            if not worker.get("active_run"):
                continue
            run = self.raw(worker["active_run"])
            if run["status"] not in TERMINAL and (
                worker.get("revoked") or min(run["lease_expires"], run["deadline"]) <= self.clock()
            ):
                try:
                    self.commit_machine(
                        worker,
                        run,
                        revised(
                            run,
                            status="outcome_unknown",
                            reason="Worker lease expired or was revoked; operator reconciliation required",
                            updated_at=self.clock(),
                        ),
                        state="quarantined",
                    )
                    changed += 1
                except Conflict:
                    continue
        return changed
