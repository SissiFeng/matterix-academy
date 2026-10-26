"""Durable outbound-worker command broker shared by both worker classes.

One API, two worker classes:

* ``sim:<worker_id>`` targets are simulation workers (EC2 GPU hosts). Their
  results are simulation evidence only.
* ``device:<instrument_id>`` targets are lab-side device gateways. Their
  results may describe physical effects.

Both speak protocol 2 of the OT-2/Flex bridge gateway: at-least-once delivery
from this store plus the worker's durable command ledger gives at-most-once
execution. Every transition is committed before it becomes visible. The
command life cycle is::

    queued ──poll──▶ delivered ──ack──▶ acked ──result──▶ returned
      │                 │ (no ack in a later poll ⇒ redeliver same ID)
      └─TTL─▶ not-dispatched      └─TTL / new worker process─▶ unknown (hold)

Only a provably undelivered command (queued) is ever reported as
not-dispatched. Anything that may have reached a worker and has no result is
``unknown`` and holds the target until an operator reconciles it. Results that
arrive after the broker stopped waiting are recorded as late evidence and keep
the hold. Deadlines are measured on this control plane's clock only; workers
receive a relative ``ttl_s`` and use their own monotonic clock.
"""

from __future__ import annotations

import copy
import hashlib
import logging
import secrets
import time
import uuid

from labtwin.wire import fingerprint

from .store import Conflict, Write

LOG = logging.getLogger(__name__)
TARGETS = "system#targets"
COMMANDS = "system#commands"
PENDING = "system#pending"
LATE = "system#late"

PROTOCOL = 2
ONLINE_WINDOW_S = 35
MAX_TTL_S = 180
MIN_DELIVERY_TTL_S = 0.5
UNKNOWN_GRACE_S = 5
RESULT_KEYS = {"id", "value", "error"}
KINDS = {"inspect", "begin", "snapshot", "execute", "finish", "stop", "reconcile"}
ALWAYS_ALLOWED = {"stop", "inspect", "finish", "reconcile"}
TERMINAL_STATES = {"returned", "not-dispatched", "unknown"}


class BrokerError(ValueError):
    """Rejected worker exchange; ``code`` tells the worker how to recover."""

    code = "invalid"


class SessionError(BrokerError):
    code = "session"


class ConflictError(BrokerError):
    code = "conflict"


class Offline(RuntimeError):
    """Refused before queueing: no command can have reached the worker."""


class Held(RuntimeError):
    """The target is held for reconciliation; only recovery commands are accepted."""


def revised(record, **changes):
    return {**copy.deepcopy(record), **changes, "version": record["version"] + 1}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def valid_target(target: str) -> bool:
    kind, _, name = target.partition(":")
    return kind in {"sim", "device"} and 0 < len(name) <= 128


class CommandBroker:
    """Store-backed protocol-2 mailbox. ``on_settled`` runs after each terminal transition.

    ``inspect_check(target, value)`` returns an error string when an inspect
    result does not prove the expected identity (device UUID and physical mode,
    or simulator runtime pins); an empty string records the target as inspected.
    """

    def __init__(
        self, store, clock=time.time, on_settled=None, inspect_check=None, sleep=time.sleep
    ):
        self.store, self.clock, self.sleep = store, clock, sleep
        self.on_settled = on_settled or (lambda command: None)
        self.inspect_check = inspect_check or (lambda target, value: "")

    # ------------------------------------------------------------------ records

    def target(self, target):
        return self.store.get(TARGETS, target)

    def _target_or_new(self, target):
        record = self.target(target)
        return record or {
            "version": 0,
            "target": target,
            "session_digest": None,
            "instance": None,
            "credential": None,
            "poll_seq": 0,
            "seen_at": 0,
            "inspected": False,
            "fault": "",
            "next_order": 0,
            "redeliveries": 0,
            "reservation": None,
        }

    def _put_target(self, old, new):
        new = {**new, "version": old["version"] + 1}
        return Write(TARGETS, new["target"], new, old["version"] or None)

    def command(self, command_id):
        return self.store.get(COMMANDS, command_id)

    def pending(self, target):
        rows = self.store.partition(PENDING, f"{target}#", limit=200)
        commands = [self.command(row["command_id"]) for row in rows]
        return [c for c in commands if c is not None]

    def online(self, record):
        return bool(record and record.get("session_digest")) and (
            self.clock() - record.get("seen_at", 0) < ONLINE_WINDOW_S
        )

    def status(self, target):
        record = self.target(target)
        return {
            "target": target,
            "online": self.online(record),
            "fault": (record or {}).get("fault", ""),
            "inspected": bool((record or {}).get("inspected")),
            "protocol": PROTOCOL if record and record.get("instance") else None,
            "redeliveries": (record or {}).get("redeliveries", 0),
            "pending": len(self.pending(target)),
            "late_results": self.late_results(target),
            "reservation": (record or {}).get("reservation"),
        }

    def late_results(self, target):
        return self.store.partition(LATE, f"{target}#", limit=50)

    # ------------------------------------------------------------------ holds

    def hold(self, target, reason):
        """Hold (or re-arm an existing hold). The first reason is kept; any new
        uncertainty invalidates earlier inspections, so reconciliation needs a
        fresh inspection after the most recent event."""
        for _ in range(8):
            record = self._target_or_new(target)
            changed = {
                **record,
                "fault": record["fault"] or reason,
                "inspected": False,
                "held_at": self.clock(),
            }
            try:
                self.store.transact([self._put_target(record, changed)])
                return
            except Conflict:
                continue
        raise Conflict

    def _hold_once(self, target, reason):
        self.hold(target, reason)

    def clear_hold(self, target):
        """Clear after an accepted reconciliation: no pending commands and an
        inspection that succeeded after the most recent hold event."""
        record = self.target(target)
        if record is None:
            return
        if (
            self.pending(target)
            or not record["inspected"]
            or record.get("inspected_at", 0) < record.get("held_at", 0)
        ):
            raise Held("Wait for pending commands and inspect the target before reconciling")
        self.store.transact([self._put_target(record, {**record, "fault": ""})])

    # ------------------------------------------------------------------ reservation

    def reserve(self, target, holder):
        """Exclusive use of a target by one run or lease holder (conditional write)."""
        record = self._target_or_new(target)
        current = record.get("reservation")
        if current and current != holder:
            raise ConflictError("Target is reserved by another run or lease holder")
        if current == holder:
            return
        self.store.transact([self._put_target(record, {**record, "reservation": holder})])

    def release(self, target, holder):
        record = self.target(target)
        if not record or record.get("reservation") != holder:
            return
        self.store.transact([self._put_target(record, {**record, "reservation": None})])

    # ------------------------------------------------------------------ control-plane side

    def enqueue(self, target, kind, payload=None, *, ttl=120, ref="", holder=None, command_id=None):
        """Queue one command. Refused when offline (never queued) or held.

        A caller-chosen ``command_id`` makes queueing idempotent: repeating the
        same ID with the same content returns the original command and never
        queues a second one; the same ID with different content is rejected.
        """
        if command_id is not None:
            if not isinstance(command_id, str) or not 1 <= len(command_id) <= 128:
                raise ValueError("Invalid command ID")
            existing = self.command(command_id)
            if existing is not None:
                if (existing["target"], existing["kind"], fingerprint(existing["payload"])) != (
                    target,
                    kind,
                    fingerprint(payload),
                ):
                    raise ConflictError("Command ID reused with different content")
                return existing
        if kind not in KINDS:
            raise ValueError("Unknown worker command")
        if not valid_target(target):
            raise ValueError("Invalid target")
        if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not 0 < ttl <= MAX_TTL_S:
            raise ValueError("Command TTL must be within (0, 180] seconds")
        for _ in range(5):
            record = self.target(target)
            if not self.online(record):
                raise Offline("Worker is offline; start it on its host. Nothing was queued.")
            if record["fault"] and kind not in ALWAYS_ALLOWED:
                raise Held(record["fault"])
            reservation = record.get("reservation")
            if reservation and holder is not None and reservation != holder and kind != "stop":
                raise Held("Target is reserved by another run or lease holder")
            order = record["next_order"] + 1
            command_id = command_id or str(uuid.uuid4())
            now = self.clock()
            command = {
                "version": 1,
                "command_id": command_id,
                "target": target,
                "order": order,
                "kind": kind,
                "payload": copy.deepcopy(payload),
                "state": "queued",
                "created_at": now,
                "deadline": now + ttl,
                "delivered_seq": None,
                "ref": ref,
                "result": None,
            }
            try:
                self.store.transact(
                    [
                        self._put_target(record, {**record, "next_order": order}),
                        Write(COMMANDS, command_id, command, None),
                        Write(
                            PENDING,
                            self._pending_key(target, order, command_id),
                            {"version": 1, "command_id": command_id},
                            None,
                        ),
                    ]
                )
            except Conflict:
                existing = self.command(command_id)
                if existing is not None:
                    if (existing["target"], existing["kind"], fingerprint(existing["payload"])) != (
                        target,
                        kind,
                        fingerprint(payload),
                    ):
                        raise ConflictError("Command ID reused with different content") from None
                    return existing
                continue
            return command
        raise Conflict

    @staticmethod
    def _pending_key(target, order, command_id):
        return f"{target}#{order:012d}#{command_id}"

    def _terminal(self, command, state, result=None, *, only_from=None):
        """Commit a terminal command state and drop it from the pending index.

        Returns the committed command, or ``None`` when a concurrent transition
        already settled it (or moved it out of ``only_from``). Never regresses.
        """
        for _ in range(5):
            if command["state"] in TERMINAL_STATES or (
                only_from and command["state"] not in only_from
            ):
                return None
            changed = revised(command, state=state, result=result, settled_at=self.clock())
            try:
                self.store.transact(
                    [
                        Write(COMMANDS, command["command_id"], changed, command["version"]),
                        Write(
                            PENDING,
                            self._pending_key(
                                command["target"], command["order"], command["command_id"]
                            ),
                            None,
                            1,
                        ),
                    ]
                )
                return changed
            except Conflict:
                command = self.command(command["command_id"])
                if command is None:
                    return None
        raise Conflict

    def _notify(self, commands):
        """Each settled command is delivered to the coordinator independently."""
        for command in commands:
            if command is None:
                continue
            try:
                self.on_settled(command)
            except Exception:  # noqa: BLE001 - one run's failure must not hide another's outcome
                LOG.exception(
                    "Settlement handler failed for %s; the reaper retries", command["command_id"]
                )

    def reap(self):
        """Expire commands by control-plane time. Queued ⇒ not-dispatched; delivered ⇒ unknown + hold."""
        count = 0
        now = self.clock()
        for row in self.store.partition(TARGETS, limit=500):
            for command in self.pending(row["target"]):
                settled = None
                try:
                    if command["state"] == "queued" and command["deadline"] <= now:
                        settled = self._terminal(command, "not-dispatched", only_from={"queued"})
                    elif (
                        command["state"] in {"delivered", "acked"}
                        and command["deadline"] + UNKNOWN_GRACE_S <= now
                    ):
                        # Hold first: a crash after this leaves a held target, never an unheld unknown.
                        self.hold(
                            row["target"],
                            f"No result for '{command['kind']}' before its deadline: outcome unknown. "
                            "Verify the worker/device and reconcile before a new run.",
                        )
                        settled = self._terminal(
                            command, "unknown", only_from={"delivered", "acked"}
                        )
                except Conflict:
                    continue
                if settled is not None:
                    count += 1
                    self._notify([settled])
        return count

    # ------------------------------------------------------------------ worker side

    def register(self, target, *, credential, instance, results=()):
        """Open a session. The same process (``instance``) with the same credential
        resumes; anything else is a new worker that fences the old one."""
        if not isinstance(instance, str) or not 8 <= len(instance) <= 128:
            raise BrokerError("Invalid worker instance identity")
        if not isinstance(results, (list, tuple)) or len(results) > 32:
            raise BrokerError("Invalid result batch")
        settled = []
        for _ in range(5):
            record = self._target_or_new(target)
            resumed = (
                bool(record["session_digest"])
                and instance == record["instance"]
                and credential == record["credential"]
            )
            if self.online(record) and not resumed:
                raise ConflictError("A worker session is already online for this target")
            fenced = list(self.pending(target)) if record["session_digest"] and not resumed else []
            if any(c["state"] in {"delivered", "acked"} for c in fenced):
                # Hold before fencing so no retry or crash can leave an unheld unknown.
                self.hold(
                    target,
                    "Previous worker process disconnected with commands in flight. "
                    "Verify they ended before reconciliation.",
                )
                record = self._target_or_new(target)
            session = secrets.token_urlsafe(32)
            changed = {
                **record,
                "session_digest": digest(session),
                "instance": instance,
                "credential": credential,
                "poll_seq": 0,
                "seen_at": self.clock(),
                "inspected": record["inspected"] if resumed else False,
            }
            try:
                self.store.transact([self._put_target(record, changed)])
            except Conflict:
                continue
            for command in fenced:
                if command["state"] == "queued":
                    settled.append(self._terminal(command, "not-dispatched", only_from={"queued"}))
                else:
                    settled.append(
                        self._terminal(command, "unknown", only_from={"delivered", "acked"})
                    )
            if resumed:
                for command in self.pending(target):
                    if command["state"] == "delivered":
                        # Eligible for redelivery to the resumed session's first poll.
                        try:
                            self.store.put(
                                COMMANDS,
                                command["command_id"],
                                revised(command, delivered_seq=0),
                                command["version"],
                            )
                        except Conflict:
                            pass
            confirmed, absorbed = self._absorb(target, (), results)
            settled.extend(absorbed)
            self._notify(settled)
            return {
                "session": session,
                "resumed": resumed,
                "confirmed": confirmed,
                "protocol": PROTOCOL,
            }
        raise Conflict

    def _session(self, target, session, credential=None):
        record = self.target(target)
        if (
            record is None
            or not isinstance(session, str)
            or not record["session_digest"]
            or not secrets.compare_digest(digest(session), record["session_digest"])
        ):
            raise SessionError("Worker session is no longer active")
        if credential is not None and credential != record["credential"]:
            raise SessionError("Worker session belongs to another credential")
        return record

    def _absorb(self, target, acks, results):
        if (
            not isinstance(acks, (list, tuple))
            or not isinstance(results, (list, tuple))
            or len(results) > 32
        ):
            raise BrokerError("Invalid acknowledgement or result batch")
        for command_id in acks:
            if not isinstance(command_id, str):
                raise BrokerError("Invalid acknowledgement")
            command = self.command(command_id)
            if command and command["target"] == target and command["state"] == "delivered":
                try:
                    self.store.put(
                        COMMANDS, command_id, revised(command, state="acked"), command["version"]
                    )
                except Conflict:
                    pass  # A concurrent transition already moved it; never regress state.
        confirmed, settled = [], []
        for data in results:
            item = self._accept(target, data)
            if item is not None:
                settled.append(item)
            confirmed.append(data["id"])
        return confirmed, settled

    def _accept(self, target, data):
        if (
            not isinstance(data, dict)
            or set(data) != RESULT_KEYS
            or not isinstance(data["id"], str)
        ):
            raise BrokerError("Invalid worker result")
        if not isinstance(data["error"], str):
            raise BrokerError("Invalid worker result")
        identity = fingerprint(data)
        command = self.command(data["id"])
        if command is None or command["target"] != target:
            self._late(target, data, "unknown")
            return None
        if command["state"] in {"delivered", "acked"}:
            return self._settle(target, command, data, identity)
        if command["state"] in {"queued", "not-dispatched"}:
            raise BrokerError("Result for a command that was never delivered")
        if command.get("result_fingerprint") == identity:
            return None  # Idempotent duplicate from the worker's outbox.
        if command["state"] == "returned":
            raise BrokerError("Conflicting result for an already returned command")
        # Unknown (deadline passed or session fenced): keep as late evidence and the hold.
        self._late(target, data, command["kind"])
        return None

    def _late(self, target, data, kind):
        now = self.clock()
        key = f"{target}#{now:020.6f}#{data['id']}"
        self.store.put(
            LATE,
            key,
            {"version": 1, "command_id": data["id"], "kind": kind, "result": data, "at": now},
            None,
        )
        outcome = data["value"].get("status") if isinstance(data["value"], dict) else None
        self._hold_once(
            target,
            f"Late result for '{kind}' ({outcome or data['error'] or 'returned'}) arrived after the "
            "control plane stopped waiting. It is recorded as evidence; verify and reconcile.",
        )

    def _settle(self, target, command, data, identity):
        device = target.startswith("device:")
        fault = ""
        if command["kind"] == "inspect" and not data["error"]:
            fault = self.inspect_check(target, data["value"])
        elif data["error"] and command["kind"] not in {"inspect", "stop"} and device:
            fault = (
                "Device command failed; verify the physical outcome and reconcile before a new run."
            )
        elif (
            device
            and command["kind"] == "execute"
            and not (isinstance(data["value"], dict) and data["value"].get("status") == "succeeded")
        ):
            status = data["value"].get("status") if isinstance(data["value"], dict) else "malformed"
            fault = f"Physical step {status}; verify the instrument and reconcile before a new run."
        if fault:
            # Hold before the result becomes visible: a crash in between leaves the
            # command delivered (the reaper then marks it unknown), never an unheld failure.
            self.hold(target, fault)
        for _ in range(5):
            changed = revised(
                command,
                state="returned",
                result={"value": data["value"], "error": data["error"]},
                result_fingerprint=identity,
                settled_at=self.clock(),
            )
            writes = [
                Write(COMMANDS, command["command_id"], changed, command["version"]),
                Write(
                    PENDING,
                    self._pending_key(target, command["order"], command["command_id"]),
                    None,
                    1,
                ),
            ]
            if command["kind"] == "inspect":
                record = self.target(target)
                verified = not data["error"] and not fault
                writes.append(
                    self._put_target(
                        record,
                        {
                            **record,
                            "inspected": verified,
                            "inspected_at": self.clock() if verified else 0,
                        },
                    )
                )
            try:
                self.store.transact(writes)
                return changed
            except Conflict:
                current = self.command(command["command_id"])
                if current is None or current["state"] not in {"delivered", "acked"}:
                    return None
                command = current
        raise Conflict

    def exchange(self, target, session, *, seq, acks=(), results=(), wait=0.0, credential=None):
        """One poll: absorb acknowledgements/results, then return at most one command."""
        if type(seq) is not int or seq < 1:
            raise BrokerError("Invalid poll sequence")
        if isinstance(wait, bool) or not isinstance(wait, (int, float)) or not 0 <= wait <= 20:
            raise BrokerError("Invalid wait")
        record = self._session(target, session, credential)
        confirmed, settled = self._absorb(target, acks, results)
        self._notify(settled)
        stale = False
        for _ in range(5):
            record = self._session(target, session, credential)
            if seq <= record["poll_seq"]:
                stale = True
                break
            try:
                self.store.transact(
                    [self._put_target(record, {**record, "poll_seq": seq, "seen_at": self.clock()})]
                )
                break
            except Conflict:
                continue
        if stale:
            return {"command": None, "confirmed": confirmed, "stale": True}
        deadline = self.clock() + wait
        while True:
            command = self._next(target, seq)
            if command is not None:
                return {"command": command, "confirmed": confirmed}
            if self.clock() >= deadline:
                return {"command": None, "confirmed": confirmed}
            self.sleep(min(0.5, max(0.0, deadline - self.clock())))
            record = self._session(target, session, credential)
            if record["poll_seq"] != seq:
                # Superseded by a newer poll: never deliver into a dead request.
                return {"command": None, "confirmed": confirmed}

    def _next(self, target, seq):
        """Stop first, then lost deliveries (same ID), then FIFO; never past its TTL."""
        now = self.clock()
        expired = []
        candidates = sorted(self.pending(target), key=lambda c: (c["kind"] != "stop", c["order"]))
        chosen = None
        for command in candidates:
            remaining = command["deadline"] - now
            if command["state"] == "delivered":
                if (command["delivered_seq"] or 0) >= seq or remaining <= MIN_DELIVERY_TTL_S:
                    continue
                redelivery = True
            elif command["state"] == "queued":
                if remaining <= MIN_DELIVERY_TTL_S:
                    expired.append(self._terminal(command, "not-dispatched", only_from={"queued"}))
                    continue
                redelivery = False
            else:
                continue
            try:
                # Durable before the command leaves the control plane.
                self.store.put(
                    COMMANDS,
                    command["command_id"],
                    revised(command, state="delivered", delivered_seq=seq),
                    command["version"],
                )
            except Conflict:
                continue
            if redelivery:
                record = self.target(target)
                try:
                    self.store.transact(
                        [
                            self._put_target(
                                record, {**record, "redeliveries": record["redeliveries"] + 1}
                            )
                        ]
                    )
                except Conflict:
                    pass
            chosen = {
                "id": command["command_id"],
                "kind": command["kind"],
                "payload": command["payload"],
                "ttl_s": round(min(remaining, MAX_TTL_S), 3),
            }
            break
        self._notify(expired)
        return chosen

    def result(self, target, session, data, credential=None):
        self._session(target, session, credential)
        settled = self._accept(target, data)
        if settled is not None:
            self._notify([settled])
