"""Record-driven sim↔real run coordinator (rehearsal, sim-first and paired runs).

Each transition is a conditional write of the run record, triggered by a
settled worker command (``CommandBroker.on_settled``), an operator action or
the scheduled reaper. Commands carry deterministic IDs derived from the run,
phase and step, so repeating an interrupted transition can never queue a
second physical command for the same step.

Authority boundaries:

* A simulation success is only a *prediction*. In ``sim_first`` mode the real
  step is queued only after a single-use receipt (``labtwin.checks``) bound to
  that exact operation, starting state and configuration passes.
* Any run that can touch hardware starts ``awaiting_approval``. An operator
  approval with an explicit physical-site confirmation, an instrument lease and
  the real-execution switch are all required before anything is queued.
* A failed or unknown physical outcome holds the instrument for reconciliation.
"""

from __future__ import annotations

import copy
import logging
import time
from typing import Literal

from fastapi import HTTPException
from labtwin import compare, workflows
from labtwin.checks import ValidationRejected, issue_receipt, state_revision, verify_receipt
from labtwin.dataset import pair_row, side
from labtwin.wire import fingerprint, outcome_from_dict, plain
from pydantic import Field, model_validator

from .broker import CommandBroker, Held, Offline
from .instruments import RECONCILIATIONS, InstrumentService, device_target
from .models import StrictModel
from .runs import WORKERS
from .store import Conflict

LOG = logging.getLogger(__name__)
PAIR_RUNS = "system#pair-runs"
PAIRS = "system#pairs"
MODES = ("sim_only", "real_only", "sim_first", "paired")
TERMINAL = {
    "completed",
    "failed",
    "sim_rejected",
    "diverged",
    "outcome_unknown",
    "cancelled",
    "rejected",
}
COMMAND_TTL = {
    "inspect": 30,
    "begin": 120,
    "snapshot": 60,
    "execute": 170,
    "finish": 30,
    "stop": 20,
}
RECEIPT_VALIDITY_S = 300
LEASE_S = 1800
MAX_EVENTS = 60


class CreatePairRun(StrictModel):
    run_id: str = Field(pattern=r"^[A-Za-z0-9-]{8,64}$")
    instrument_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    mode: Literal["sim_only", "real_only", "sim_first", "paired"]
    rehearsal_run_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9-]{8,64}$")


class PhysicalConfirmation(StrictModel):
    deck_matches_plan: bool
    workspace_clear: bool
    emergency_stop_reachable: bool
    note: str = Field(min_length=8, max_length=500)

    @model_validator(mode="after")
    def all_confirmed(self):
        if not (self.deck_matches_plan and self.workspace_clear and self.emergency_stop_reachable):
            raise ValueError("Every physical-site confirmation is required before real execution")
        return self


class ApprovePairRun(StrictModel):
    expected_version: int = Field(ge=1)
    confirmation: PhysicalConfirmation


class RejectPairRun(StrictModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)


class StopPairRun(StrictModel):
    expected_version: int = Field(ge=1)


def revised(record, **changes):
    return {**copy.deepcopy(record), **changes, "version": record["version"] + 1}


def uses_sim(mode):
    return mode in {"sim_only", "sim_first", "paired", "predict"}


def uses_real(mode):
    return mode in {"real_only", "sim_first", "paired"}


def sim_target(worker_id):
    return f"sim:{worker_id}"


class PairRunService:
    def __init__(
        self,
        store,
        *,
        pairing_enabled=False,
        real_enabled=False,
        clock=time.time,
        broker: CommandBroker | None = None,
    ):
        self.store, self.clock = store, clock
        self.pairing_enabled, self.real_enabled = pairing_enabled, real_enabled
        self.instruments = InstrumentService(store, clock=clock)
        self.broker = broker or make_broker(store, clock=clock)
        self.broker.on_settled = self.on_settled

    # ------------------------------------------------------------------ reads

    def raw(self, run_id):
        record = self.store.get(PAIR_RUNS, run_id)
        if record is None:
            raise HTTPException(404, "Run not found")
        return record

    def public(self, run):
        hidden = {"waiting"}
        view = {k: v for k, v in run.items() if k not in hidden}
        sides = [
            name
            for name, used in (("sim", uses_sim(run["mode"])), ("real", uses_real(run["mode"])))
            if used
        ]
        view["completed_steps"] = sum(
            1
            for s in run["steps"]
            if all((s.get(name) or {}).get("status") == "succeeded" for name in sides)
        )
        view["total_steps"] = len(run["plan"]["operations"])
        view["evidence"] = {
            "sim": "simulated" if uses_sim(run["mode"]) else None,
            "real": "physical" if uses_real(run["mode"]) else None,
        }
        return view

    def list(self, instrument_id=None, limit=50):
        rows = self.store.partition(PAIR_RUNS, limit=200)
        if instrument_id:
            rows = [r for r in rows if r["instrument_id"] == instrument_id]
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        return [self.public(r) for r in rows[:limit]]

    # ------------------------------------------------------------------ creation

    def create(self, requester, data: CreatePairRun, *, operator=False):
        existing = self.store.get(PAIR_RUNS, data.run_id)
        if existing:
            if (existing["requested_by"], existing["instrument_id"], existing["mode"]) != (
                requester,
                data.instrument_id,
                data.mode,
            ):
                raise Conflict
            return self.public(existing)
        if not self.pairing_enabled:
            raise HTTPException(503, "Sim-to-real runs are not enabled in this deployment")
        if uses_real(data.mode) and not self.real_enabled:
            raise HTTPException(503, "Physical execution is not enabled in this deployment")
        instrument = self.instruments.get(data.instrument_id)
        plan = workflows.make_plan(instrument["profile"], data.run_id)
        identity = workflows.plan_identity(plan)
        rehearsal = None
        if data.rehearsal_run_id:
            if data.mode != "real_only":
                raise HTTPException(422, "Only a real-only run references a separate rehearsal")
            rehearsal = self.raw(data.rehearsal_run_id)
            if (
                rehearsal["mode"] != "sim_only"
                or rehearsal["status"] != "completed"
                or rehearsal["instrument_id"] != data.instrument_id
                or rehearsal["identity"]["workflow_sha256"] != identity["workflow_sha256"]
                or rehearsal["identity"]["qualified_profile_sha256"]
                != identity["qualified_profile_sha256"]
            ):
                raise HTTPException(
                    409,
                    "The rehearsal must be a completed sim-only run of the same workflow and qualified profile",
                )
        elif data.mode == "real_only" and instrument.get("require_rehearsal"):
            raise HTTPException(
                409, "This instrument requires a successful sim-only rehearsal first"
            )
        now = self.clock()
        run = {
            "version": 1,
            "run_id": data.run_id,
            "instrument_id": data.instrument_id,
            "model": instrument["model"],
            "mode": data.mode,
            "requested_by": requester,
            "requested_as": "operator" if operator else "learner",
            "rehearsal_run_id": data.rehearsal_run_id,
            "plan": plan,
            "identity": identity,
            "calibration_revision": instrument.get("calibration_revision"),
            "checks": copy.deepcopy(instrument.get("validation_checks") or {}),
            "tolerances": copy.deepcopy(instrument.get("tolerances") or {}),
            "configuration_revision": fingerprint(
                {
                    "qualified": identity["qualified_profile_sha256"],
                    "calibration": instrument.get("calibration_revision"),
                    "checks": instrument.get("validation_checks") or {},
                    "tolerances": instrument.get("tolerances") or {},
                }
            ),
            "sim_corrections": copy.deepcopy(instrument.get("sim_corrections") or []),
            "status": "awaiting_approval" if uses_real(data.mode) else "queued",
            "approval": None,
            "sim_target": None,
            "phase": "start",
            "step": 0,
            "waiting": {},
            "initial": {"real": None, "sim": None},
            "steps": [
                {
                    "operation": op,
                    "sim": None,
                    "real": None,
                    "receipt": None,
                    "gate": None,
                    "comparisons": [],
                }
                for op in plan["operations"]
            ],
            "finished": {},
            "reason": "",
            "created_at": now,
            "updated_at": now,
            "events": [{"at": now, "event": "created"}],
        }
        self.store.put(PAIR_RUNS, data.run_id, run, None)
        if not uses_real(data.mode):
            run = self._start(run)
        return self.public(run)

    # ------------------------------------------------------------------ operator decisions

    def approve(self, operator, run_id, data: ApprovePairRun):
        run = self.raw(run_id)
        if run["status"] != "awaiting_approval":
            if run.get("approval") and run["approval"]["by"] == operator:
                return self.public(run)
            raise HTTPException(409, "This run is not awaiting approval")
        if run["version"] != data.expected_version:
            raise Conflict
        if not self.real_enabled:
            raise HTTPException(503, "Physical execution is not enabled in this deployment")
        instrument = self.instruments.get(run["instrument_id"])
        if instrument["qualified_profile_sha256"] != run["identity"]["qualified_profile_sha256"]:
            raise HTTPException(409, "The instrument profile changed after this run was requested")
        status = self.broker.status(device_target(run["instrument_id"]))
        if status["fault"]:
            raise HTTPException(409, f"Instrument is held: {status['fault']}")
        self.instruments.acquire(run["instrument_id"], f"run:{run_id}", seconds=LEASE_S, kind="run")
        approved = revised(
            run,
            approval={
                "by": operator,
                "at": self.clock(),
                "confirmation": data.confirmation.model_dump(),
            },
            status="queued",
            updated_at=self.clock(),
            events=self._event(run, "approved"),
        )
        try:
            self.store.put(PAIR_RUNS, run_id, approved, run["version"])
        except Conflict:
            self.instruments.release(run["instrument_id"], f"run:{run_id}")
            raise
        return self.public(self._start(approved))

    def reject(self, operator, run_id, data: RejectPairRun):
        run = self.raw(run_id)
        if run["status"] != "awaiting_approval" or run["version"] != data.expected_version:
            raise Conflict
        rejected = revised(
            run,
            status="rejected",
            reason=data.reason,
            updated_at=self.clock(),
            events=self._event(run, f"rejected by {operator}"),
        )
        self.store.put(PAIR_RUNS, run_id, rejected, run["version"])
        return self.public(rejected)

    def stop(self, requester, run_id, data: StopPairRun):
        """Request a stop. Stop is delivered first; it never asserts physical stoppage."""
        run = self.raw(run_id)
        if run["status"] in TERMINAL:
            return self.public(run)
        if run["version"] != data.expected_version:
            raise Conflict
        if run["status"] == "awaiting_approval":
            cancelled = revised(
                run,
                status="cancelled",
                updated_at=self.clock(),
                events=self._event(run, "cancelled"),
            )
            self.store.put(PAIR_RUNS, run_id, cancelled, run["version"])
            return self.public(cancelled)
        # Record the request first; delivery to an offline worker must not prevent it.
        stopped = revised(
            run,
            stop_requested=True,
            updated_at=self.clock(),
            events=self._event(run, "stop requested"),
        )
        self.store.put(PAIR_RUNS, run_id, stopped, run["version"])
        for side_name, used in (
            ("real", uses_real(run["mode"]) and run.get("approval")),
            ("sim", run.get("sim_target")),
        ):
            if used:
                try:
                    self._enqueue(run, side_name, "stop", None, f"{run_id}.stop.{side_name}")
                except (Offline, Held):
                    pass  # Nothing more can be sent; the run closes when the worker returns.
        return self.public(stopped)

    # ------------------------------------------------------------------ transitions

    def _event(self, run, text):
        return (run.get("events") or [])[-(MAX_EVENTS - 1) :] + [
            {"at": self.clock(), "event": text}
        ]

    def _target(self, run, side_name):
        return (
            device_target(run["instrument_id"])
            if side_name == "real"
            else sim_target(run["sim_target"])
        )

    def _enqueue(self, run, side_name, kind, payload, command_id):
        return self.broker.enqueue(
            self._target(run, side_name),
            kind,
            payload,
            ttl=COMMAND_TTL[kind],
            ref=f"pair:{run['run_id']}",
            command_id=command_id,
            holder=f"run:{run['run_id']}" if side_name == "sim" else None,
        )

    def _authorize_physical(self, run):
        """Every physical command re-checks the switch and renews this run's lease.

        Returns a reason when the run may no longer move hardware.
        """
        if not self.real_enabled:
            return "Physical execution was disabled in this deployment"
        if not run.get("approval"):
            return "Physical execution requires an operator approval"
        holder = f"run:{run['run_id']}"
        if self.instruments.lease_holder(run["instrument_id"]) != holder:
            return "The instrument lease expired or belongs to another control source"
        try:
            self.instruments.acquire(run["instrument_id"], holder, seconds=LEASE_S, kind="run")
        except (HTTPException, Conflict):
            return "The instrument lease could not be renewed"
        return ""

    def _configuration_now(self, run):
        """Configuration revision from the instrument as it is now (not as it was at creation)."""
        instrument = self.instruments.get(run["instrument_id"])
        return fingerprint(
            {
                "qualified": instrument["qualified_profile_sha256"],
                "calibration": instrument.get("calibration_revision"),
                "checks": instrument.get("validation_checks") or {},
                "tolerances": instrument.get("tolerances") or {},
            }
        )

    def _choose_sim(self, run):
        for worker in self.store.partition(WORKERS, limit=100):
            if (
                worker.get("worker_class", "simulation") != "simulation"
                or worker.get("revoked", True)
                or not worker.get("qualified")
                or run["model"] not in worker.get("pair_models", [])
                or worker.get("active_run")
            ):
                continue
            target = sim_target(worker["worker_id"])
            status = self.broker.status(target)
            if not status["online"] or status["fault"] or status["reservation"]:
                continue
            try:
                self.broker.reserve(target, f"run:{run['run_id']}")
            except Exception:
                continue
            return worker["worker_id"]
        return None

    def _start(self, run):
        """Bind workers and issue the first command; failures before any dispatch fail cleanly."""
        changes = {"status": "running", "updated_at": self.clock()}
        worker_id = None
        if uses_sim(run["mode"]):
            worker_id = self._choose_sim(run)
            if worker_id is None:
                return self._fail(
                    run, "failed", "No qualified, online simulation worker supports this instrument"
                )
            changes["sim_target"] = worker_id
        started = revised(run, **changes, events=self._event(run, "started"))
        try:
            self.store.put(PAIR_RUNS, run["run_id"], started, run["version"])
        except Conflict:
            if worker_id:
                self.broker.release(sim_target(worker_id), f"run:{run['run_id']}")
            raise
        return self.advance(run["run_id"])

    def _fail(self, run, status, reason, *, hold=False):
        """Persist a terminal status, then close whatever was begun."""
        if hold:
            self.broker.hold(device_target(run["instrument_id"]), reason)
        failed = revised(
            run,
            status=status,
            reason=reason,
            updated_at=self.clock(),
            events=self._event(run, f"{status}: {reason}"),
        )
        try:
            self.store.put(PAIR_RUNS, run["run_id"], failed, run["version"])
        except Conflict:
            return self.raw(run["run_id"])
        return self._advance(failed)

    def _release(self, run):
        self.instruments.release(run["instrument_id"], f"run:{run['run_id']}")
        if run.get("sim_target"):
            self.broker.release(sim_target(run["sim_target"]), f"run:{run['run_id']}")

    def on_settled(self, command):
        ref = command.get("ref") or ""
        if ref.startswith("reconcile:"):
            self._reconciled(command)
            return
        if ref.startswith("pair:"):
            for _ in range(5):
                try:
                    self.consume(ref[5:], command)
                    return
                except Conflict:
                    continue

    def _reconciled(self, command):
        """An operator reconciliation clears the hold only after a verified inspection."""
        if command["kind"] != "reconcile" or command["state"] != "returned":
            return
        if (command.get("result") or {}).get("error"):
            return
        target = command["target"]
        try:
            self.broker.clear_hold(target)
        except Held:
            return  # Inspection failed or a command is still pending: the hold remains.
        self.store.put(
            RECONCILIATIONS,
            f"{target}#{command['command_id']}",
            {
                "version": 1,
                "target": target,
                "operator": command["ref"].rsplit(":", 1)[-1],
                "note": command["payload"]["note"],
                "at": self.clock(),
            },
            None,
        )

    def consume(self, run_id, command):
        run = self.store.get(PAIR_RUNS, run_id)
        if run is None or command["command_id"] not in run["waiting"]:
            return
        purpose = run["waiting"][command["command_id"]]
        waiting = {k: v for k, v in run["waiting"].items() if k != command["command_id"]}
        updated = revised(run, waiting=waiting, updated_at=self.clock())
        hold = self._record(updated, purpose, command)
        if hold:
            # Hold before the run records the failure: a crash in between can never
            # leave a failed physical step on an unheld instrument.
            self.broker.hold(device_target(run["instrument_id"]), hold)
        self.store.put(PAIR_RUNS, run_id, updated, run["version"])
        self.advance(run_id)

    def _set_status(self, run, status, reason):
        """First terminal reason wins, except that physical uncertainty always surfaces."""
        if run["status"] == "running" or (
            status == "outcome_unknown" and run["status"] != "outcome_unknown"
        ):
            run.update(status=status, reason=reason)
            run["events"] = self._event(run, f"{status}: {reason}")

    def _record(self, run, purpose, command):
        """Fold one settled command into the run. Returns a hold reason for the instrument, if any."""
        side_name, kind, step = purpose["side"], purpose["kind"], purpose["step"]
        result = command.get("result") or {}
        error = result.get("error", "")
        state = command["state"]
        if kind == "finish":
            run["finished"][side_name] = state == "returned" and not error
            return ""
        if state != "returned" or error:
            if side_name == "real" and kind == "inspect" and state == "returned":
                self._set_status(
                    run, "failed", f"Connector inspection failed; nothing was dispatched: {error}"
                )
            elif side_name == "real" and state == "not-dispatched":
                self._set_status(
                    run, "failed", f"Device '{kind}' was never delivered: no physical effect"
                )
            elif side_name == "real":
                # The broker already holds the instrument for errors and unknown outcomes.
                self._set_status(
                    run,
                    "outcome_unknown",
                    f"Device '{kind}' {state}: {error or 'no result'}. The instrument is held.",
                )
            else:
                self._set_status(
                    run, "failed", f"Simulation '{kind}' {state}: {error or 'no result'}"
                )
            return ""
        value = result["value"]
        if kind == "inspect":
            run["inspected"] = True
            return ""
        if kind == "begin":
            run[f"{side_name}_ready"] = True
            return ""
        if kind == "snapshot" and purpose.get("tag") == "presnap":
            run["steps"][step]["pre_real"] = value
            return ""
        if kind == "snapshot":
            run["initial"][side_name] = value
            return ""
        # execute
        hold = ""
        outcome = outcome_from_dict(value)
        step_record = run["steps"][step]
        step_record[side_name] = side(outcome, command["created_at"], command.get("settled_at"))
        if side_name == "real" and outcome.status.value != "succeeded":
            status = "outcome_unknown" if outcome.status.value == "unknown" else "failed"
            reason = (
                f"Physical step {outcome.status.value}: {outcome.error}. The instrument is held."
            )
            self._set_status(run, status, reason)
            hold = f"Run {run['run_id']} ended with a {outcome.status.value} physical step. Reconcile before reuse."
        if side_name == "sim" and run["mode"] in {"sim_first", "predict"}:
            self._gate(run, step)
        elif side_name == "sim" and outcome.status.value != "succeeded":
            self._set_status(run, "failed", f"Simulation step failed: {outcome.error}")
        if step_record.get("real") and step_record.get("sim"):

            def bare(value):
                return {
                    "status": value["status"],
                    "observation": value["observation"],
                    "error": value["error"],
                }

            comparisons = compare(
                outcome_from_dict(bare(step_record["real"])),
                outcome_from_dict(bare(step_record["sim"])),
                run["tolerances"],
            )
            step_record["comparisons"] = [
                {"field": c.field, "status": c.status, "reason": c.reason} for c in comparisons
            ]
            if any(c.status == "different" for c in comparisons):
                self._set_status(
                    run, "diverged", "Real and simulated states differ beyond tolerance"
                )
        return hold

    def _gate(self, run, step):
        """Issue the single-use receipt for the next real step from the twin's prediction."""
        step_record = run["steps"][step]
        previous = (
            run["initial"]["real"]
            if step == 0
            else (run["steps"][step - 1]["real"] or {}).get("observation")
        )
        try:
            state = state_revision(previous)
        except ValidationRejected as exc:
            step_record["gate"] = "held"
            self._set_status(run, "sim_rejected", str(exc))
            return
        sim = step_record["sim"]
        receipt = issue_receipt(
            operation=step_record["operation"],
            sim_outcome={
                "status": sim["status"],
                "observation": sim["observation"],
                "error": sim["error"],
            },
            state=state,
            configuration=run["configuration_revision"],
            specs=run["checks"].get(step_record["operation"]["action"], []),
            now=self.clock(),
            validity_s=RECEIPT_VALIDITY_S,
        )
        step_record["receipt"] = {**receipt, "consumed": False}
        step_record["gate"] = "passed" if receipt["passed"] else "held"
        if not receipt["passed"]:
            self._set_status(
                run,
                "sim_rejected",
                f"Digital twin rejected step {step_record['operation']['operation_id']}: "
                + (sim["error"] or "a required check did not pass"),
            )

    def advance(self, run_id):
        """Issue the next command(s) for the current phase; idempotent and restartable."""
        for _ in range(5):
            run = self.raw(run_id)
            try:
                return self._advance(run)
            except Conflict:
                continue
        raise Conflict

    def _command_id(self, run, side_name, kind, step, tag=None):
        return f"{run['run_id']}.{side_name}.{tag or kind}.{step}"

    def _issue(self, run, purposes, **changes):
        """Persist the intent (awaited commands and their payloads) first, then queue them.

        A queued command is therefore always awaited by its run. Queueing uses
        deterministic IDs, so the reaper can repeat an interrupted queueing
        without ever creating a second command for the same step.
        """
        waiting = dict(run["waiting"])
        new = []
        for purpose in purposes:
            side_name, kind, step, payload = purpose[:4]
            tag = purpose[4] if len(purpose) > 4 else None
            if side_name == "real" and kind not in {"stop", "finish", "inspect"}:
                blocked = self._authorize_physical(run)
                if blocked:
                    return self._fail(run, "failed", blocked, hold=bool(run.get("real_begun")))
            command_id = self._command_id(run, side_name, kind, step, tag)
            if command_id in waiting:
                continue
            waiting[command_id] = {
                "side": side_name,
                "kind": kind,
                "step": step,
                "tag": tag,
                "payload": payload,
            }
            new.append(command_id)
        changed = revised(run, waiting=waiting, updated_at=self.clock(), **changes)
        self.store.put(PAIR_RUNS, run["run_id"], changed, run["version"])
        for command_id in new:
            entry = waiting[command_id]
            try:
                self._enqueue(changed, entry["side"], entry["kind"], entry["payload"], command_id)
            except (Offline, Held) as exc:
                return self._unqueued(changed["run_id"], command_id, exc)
        if not waiting:
            return self._advance(changed)
        return changed

    def _unqueued(self, run_id, command_id, exc):
        """A command that was never queued: drop it from the run and fail or skip cleanly."""
        for _ in range(5):
            run = self.raw(run_id)
            entry = run["waiting"].get(command_id)
            if entry is None or self.broker.command(command_id) is not None:
                return run
            waiting = {k: v for k, v in run["waiting"].items() if k != command_id}
            changed = revised(run, waiting=waiting, updated_at=self.clock())
            if entry["kind"] == "finish":
                changed["finished"][entry["side"]] = False
            try:
                self.store.put(PAIR_RUNS, run_id, changed, run["version"])
            except Conflict:
                continue
            if entry["kind"] == "finish":
                return self._advance(changed) if not waiting else changed
            touched = entry["side"] == "real" and bool(changed.get("real_begun"))
            return self._fail(
                changed,
                "failed",
                f"{entry['side']} worker unavailable before '{entry['kind']}': {exc}",
                hold=touched,
            )
        raise Conflict

    def _advance(self, run):
        if run["waiting"]:
            return run
        mode = run["mode"]
        binding = run["plan"]["binding"]
        if run["status"] in TERMINAL or run.get("stop_requested"):
            # Close every side that was begun, exactly once, then release the lease and worker.
            pending = []
            if run.get("real_begun") and "real" not in run["finished"]:
                pending.append(("real", "finish", 0, binding))
            if run.get("sim_begun") and "sim" not in run["finished"]:
                pending.append(("sim", "finish", 0, binding))
            if pending:
                return self._issue(run, pending)
            if run["status"] not in TERMINAL:
                cancelled = revised(
                    run,
                    status="cancelled",
                    reason="Stopped by request",
                    updated_at=self.clock(),
                    events=self._event(run, "cancelled"),
                )
                self.store.put(PAIR_RUNS, run["run_id"], cancelled, run["version"])
                run = cancelled
            if not run.get("released"):
                self._release(run)
                released = revised(run, released=True)
                self.store.put(PAIR_RUNS, run["run_id"], released, run["version"])
                run = released
            return run
        if run["status"] != "running":
            return run
        # Startup: device identity and initial state first, so the twin can be seeded from it.
        if uses_real(mode) and not run.get("inspected"):
            return self._issue(run, [("real", "inspect", 0, None)])
        if uses_real(mode) and not run.get("real_begun"):
            blocked = self._authorize_physical(run)
            if blocked:
                return self._fail(run, "failed", blocked)
            return self._issue(run, [("real", "begin", 0, run["plan"])], real_begun=True)
        if uses_real(mode) and run["initial"]["real"] is None:
            return self._issue(run, [("real", "snapshot", 0, "initial")])
        if uses_sim(mode) and not run.get("sim_begun"):
            payload = {
                "plan": run["plan"],
                "seed": run["initial"]["real"],
                "corrections": run["sim_corrections"],
                "start_operation_id": run["steps"][0]["operation"]["operation_id"],
            }
            return self._issue(run, [("sim", "begin", 0, payload)], sim_begun=True)
        if uses_sim(mode) and run["initial"]["sim"] is None:
            return self._issue(run, [("sim", "snapshot", 0, "initial")])
        index = next(
            (
                i
                for i, s in enumerate(run["steps"])
                if (uses_real(mode) and s["real"] is None) or (uses_sim(mode) and s["sim"] is None)
            ),
            None,
        )
        if index is None:
            done = revised(
                run,
                status="completed",
                updated_at=self.clock(),
                events=self._event(run, "completed"),
            )
            self.store.put(PAIR_RUNS, run["run_id"], done, run["version"])
            self._record_dataset(done)
            return self._advance(done)
        step = run["steps"][index]
        op = step["operation"]
        if mode in {"sim_only", "predict"}:
            return self._issue(run, [("sim", "execute", index, op)])
        if mode == "real_only":
            return self._issue(run, [("real", "execute", index, op)])
        if mode == "paired":
            purposes = []
            if step["sim"] is None:
                purposes.append(("sim", "execute", index, op))
            if step["real"] is None:
                purposes.append(("real", "execute", index, op))
            return self._issue(run, purposes)
        # sim_first: the twin predicts from the last real state; immediately before
        # dispatch a fresh physical snapshot must still equal that state, and the
        # instrument configuration must be unchanged. The receipt is single use.
        if step["sim"] is None:
            return self._issue(run, [("sim", "execute", index, op)])
        if step.get("pre_real") is None:
            return self._issue(
                run, [("real", "snapshot", index, f"pre-{op['operation_id']}", "presnap")]
            )
        receipt = step.get("receipt")
        try:
            if not receipt or receipt.get("consumed"):
                raise ValidationRejected("Receipt is missing or already consumed")
            verify_receipt(
                receipt,
                operation=op,
                state=state_revision(step["pre_real"]),
                configuration=self._configuration_now(run),
                now=self.clock(),
            )
        except ValidationRejected as exc:
            step["gate"] = "held"
            return self._fail(run, "sim_rejected", f"Real dispatch held: {exc}")
        # Consumption is committed in the same run write that awaits the real step.
        step["receipt"] = {**receipt, "consumed": True}
        return self._issue(run, [("real", "execute", index, op)])

    # ------------------------------------------------------------------ recovery

    def repair(self, run_id, *, grace_s=15):
        """Drive a run whose transition was interrupted (crash, lost notification, conflict)."""
        run = self.store.get(PAIR_RUNS, run_id)
        if run is None or (run["status"] in TERMINAL and run.get("released")):
            return run
        for command_id, entry in list(run["waiting"].items()):
            command = self.broker.command(command_id)
            if command is None:
                if self.clock() - run["updated_at"] >= grace_s:
                    try:
                        self._enqueue(
                            run, entry["side"], entry["kind"], entry["payload"], command_id
                        )
                    except (Offline, Held) as exc:
                        self._unqueued(run_id, command_id, exc)
            elif command["state"] in {"returned", "not-dispatched", "unknown"}:
                self.on_settled(command)
        run = self.raw(run_id)
        if not run["waiting"] and run["status"] != "awaiting_approval":
            return self.advance(run_id)
        return run

    # ------------------------------------------------------------------ external predictions

    def create_prediction(
        self, client, instrument_id, prediction_id, operation_id, start_observation
    ):
        """One-step twin prediction for an external orchestrator that executes the real step itself."""
        existing = self.store.get(PAIR_RUNS, prediction_id)
        holder = f"external:{client}"
        if existing:
            if (existing["requested_by"], existing["instrument_id"], existing["mode"]) != (
                holder,
                instrument_id,
                "predict",
            ) or existing["steps"][0]["operation"]["operation_id"] != operation_id:
                raise Conflict
            return self.public(existing)
        if not self.pairing_enabled:
            raise HTTPException(503, "Sim-to-real runs are not enabled in this deployment")
        if self.instruments.lease_holder(instrument_id) != holder:
            raise HTTPException(409, "Acquire the instrument lease before requesting predictions")
        try:
            state_revision(start_observation)
        except ValidationRejected as exc:
            raise HTTPException(422, str(exc)) from None
        instrument = self.instruments.get(instrument_id)
        plan = workflows.make_plan(instrument["profile"], prediction_id)
        matches = [op for op in plan["operations"] if op["operation_id"] == operation_id]
        if not matches:
            raise HTTPException(
                422, "Operation is not part of this instrument's registered workflow"
            )
        identity = workflows.plan_identity(plan)
        now = self.clock()
        run = {
            "version": 1,
            "run_id": prediction_id,
            "instrument_id": instrument_id,
            "model": instrument["model"],
            "mode": "predict",
            "requested_by": holder,
            "requested_as": "external",
            "rehearsal_run_id": None,
            "plan": plan,
            "identity": identity,
            "calibration_revision": instrument.get("calibration_revision"),
            "checks": copy.deepcopy(instrument.get("validation_checks") or {}),
            "tolerances": copy.deepcopy(instrument.get("tolerances") or {}),
            "configuration_revision": fingerprint(
                {
                    "qualified": identity["qualified_profile_sha256"],
                    "calibration": instrument.get("calibration_revision"),
                    "checks": instrument.get("validation_checks") or {},
                    "tolerances": instrument.get("tolerances") or {},
                }
            ),
            "sim_corrections": copy.deepcopy(instrument.get("sim_corrections") or []),
            "status": "queued",
            "approval": None,
            "sim_target": None,
            "phase": "start",
            "step": 0,
            "waiting": {},
            "initial": {"real": plain(start_observation), "sim": None},
            "steps": [
                {
                    "operation": matches[0],
                    "sim": None,
                    "real": None,
                    "receipt": None,
                    "gate": None,
                    "comparisons": [],
                }
            ],
            "finished": {},
            "reason": "",
            "created_at": now,
            "updated_at": now,
            "events": [{"at": now, "event": "prediction requested"}],
        }
        self.store.put(PAIR_RUNS, prediction_id, run, None)
        return self.public(self._start(run))

    def claim_prediction(self, client, prediction_id, operation, current_observation):
        """Consume the receipt once, immediately before the orchestrator's own real dispatch."""
        run = self.raw(prediction_id)
        if run["requested_by"] != f"external:{client}" or run["mode"] != "predict":
            raise HTTPException(404, "Prediction not found")
        if self.instruments.lease_holder(run["instrument_id"]) != f"external:{client}":
            raise HTTPException(
                409, "The instrument lease expired or belongs to another control source"
            )
        if self.broker.status(device_target(run["instrument_id"]))["fault"]:
            raise HTTPException(409, "The instrument is held for reconciliation")
        step = run["steps"][0]
        receipt = step.get("receipt")
        try:
            if not receipt or receipt.get("consumed"):
                raise ValidationRejected("Receipt is missing or already consumed")
            verify_receipt(
                receipt,
                operation=plain(operation),
                state=state_revision(current_observation),
                configuration=run["configuration_revision"],
                now=self.clock(),
            )
        except ValidationRejected as exc:
            if receipt and not receipt.get("consumed"):
                step["receipt"] = {**receipt, "consumed": True}
                step["gate"] = "held"
                self.store.put(PAIR_RUNS, prediction_id, revised(run), run["version"])
            raise HTTPException(409, f"Real dispatch held: {exc}") from None
        step["receipt"] = {**receipt, "consumed": True}
        claimed = revised(run, updated_at=self.clock(), events=self._event(run, "receipt claimed"))
        self.store.put(PAIR_RUNS, prediction_id, claimed, run["version"])
        return {"claimed": True, "sim": step["sim"], "receipt": step["receipt"]}

    def report_outcome(self, client, prediction_id, outcome):
        """Record the orchestrator-reported real outcome as evidence (provenance kept)."""
        run = self.raw(prediction_id)
        if run["requested_by"] != f"external:{client}" or run["mode"] != "predict":
            raise HTTPException(404, "Prediction not found")
        step = run["steps"][0]
        if not (step.get("receipt") or {}).get("consumed") or step["gate"] != "passed":
            raise HTTPException(409, "Only a claimed, passed prediction can receive a real outcome")
        try:
            parsed = outcome_from_dict(outcome)
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, f"Invalid outcome: {exc}") from None
        real = {**side(parsed), "reported_by": f"external:{client}"}
        if step.get("real"):
            if {k: v for k, v in step["real"].items() if k != "reported_by"} != side(parsed):
                raise Conflict
            return self.public(run)
        if parsed.status.value != "succeeded":
            # An orchestrator-reported failure is still a physical uncertainty.
            self.broker.hold(
                device_target(run["instrument_id"]),
                f"External orchestrator reported a {parsed.status.value} physical step. Reconcile before reuse.",
            )
        step["real"] = real
        bare = {
            "status": step["sim"]["status"],
            "observation": step["sim"]["observation"],
            "error": step["sim"]["error"],
        }
        step["comparisons"] = [
            {"field": c.field, "status": c.status, "reason": c.reason}
            for c in compare(parsed, outcome_from_dict(bare), run["tolerances"])
        ]
        changed = revised(
            run, updated_at=self.clock(), events=self._event(run, "real outcome reported")
        )
        self.store.put(PAIR_RUNS, prediction_id, changed, run["version"])
        self._record_dataset(changed, force=True)
        return self.public(changed)

    # ------------------------------------------------------------------ dataset

    def _record_dataset(self, run, force=False):
        if not uses_real(run["mode"]) and not force:
            return
        sim_steps = {}
        source = "same-run"
        if run["mode"] == "real_only" and run.get("rehearsal_run_id"):
            rehearsal = self.store.get(PAIR_RUNS, run["rehearsal_run_id"])
            if (
                rehearsal
                and rehearsal["identity"]["workflow_sha256"] == run["identity"]["workflow_sha256"]
            ):
                sim_steps = {s["operation"]["operation_id"]: s["sim"] for s in rehearsal["steps"]}
                source = "rehearsal"
        base = {
            "run_id": run["run_id"],
            "mode": run["mode"],
            "run_status": run["status"],
            "device_id": run["instrument_id"],
            "workflow_sha256": run["identity"]["workflow_sha256"],
            "qualified_profile_sha256": run["identity"]["qualified_profile_sha256"],
            "calibration_revision": run.get("calibration_revision"),
            "rehearsal_run_id": run.get("rehearsal_run_id"),
        }
        rows = []
        if run["initial"]["real"] or run["initial"]["sim"]:
            rows.append(
                pair_row(
                    base=base,
                    operation={"operation_id": "initial", "action": "snapshot", "parameters": {}},
                    real={"status": "succeeded", "error": "", "observation": run["initial"]["real"]}
                    if run["initial"]["real"]
                    else None,
                    sim={"status": "succeeded", "error": "", "observation": run["initial"]["sim"]}
                    if run["initial"]["sim"]
                    else None,
                    sim_source="same-run",
                    gate=None,
                )
            )
        for step in run["steps"]:
            sim = step["sim"] or sim_steps.get(step["operation"]["operation_id"])
            rows.append(
                pair_row(
                    base=base,
                    operation=step["operation"],
                    real=step["real"],
                    sim=sim,
                    sim_source=source if not step["sim"] else "same-run",
                    gate=step["gate"],
                )
            )
        for row in rows:
            key = f"{run['instrument_id']}#{run['run_id']}#{row['operation_id']}"
            try:
                self.store.put(PAIRS, key, {"version": 1, **plain(row)}, None)
            except Conflict:
                pass  # Already recorded by an earlier attempt.

    def dataset(self, instrument_id, limit=500):
        rows = self.store.partition(PAIRS, f"{instrument_id}#", limit=limit)
        return [{k: v for k, v in row.items() if k != "version"} for row in rows]

    def reap(self):
        """Expire commands, then repair every unfinished run and release leaked reservations."""
        expired = self.broker.reap()
        repaired = 0
        for run in self.store.partition(PAIR_RUNS, limit=500):
            if run["status"] == "awaiting_approval" or (
                run["status"] in TERMINAL and run.get("released")
            ):
                continue
            try:
                self.repair(run["run_id"])
                repaired += 1
            except Exception:  # noqa: BLE001 - one run must not stop the sweep
                LOG.exception("Could not repair run %s", run["run_id"])
        for target in self.store.partition("system#targets", "sim:", limit=200):
            holder = target.get("reservation") or ""
            if holder.startswith("run:"):
                run = self.store.get(PAIR_RUNS, holder[4:])
                if run is None or (run["status"] in TERMINAL and run.get("released")):
                    self.broker.release(target["target"], holder)
        return {"expired": expired, "repaired": repaired}


def make_broker(store, clock=time.time):
    """Broker with the identity checks for both worker classes."""
    instruments = InstrumentService(store, clock=clock)

    def inspect_check(target, value):
        kind, _, name = target.partition(":")
        if kind == "device":
            return instruments.inspect_check(name, value)
        worker = store.get(WORKERS, name) or {}
        if (
            not isinstance(value, dict)
            or value.get("simulation_only") is not True
            or value.get("engine_version") != worker.get("engine_version")
            or value.get("asset_version") != worker.get("asset_version")
        ):
            return "Simulation runtime differs from its qualified manifest"
        return ""

    return CommandBroker(store, clock=clock, inspect_check=inspect_check)
