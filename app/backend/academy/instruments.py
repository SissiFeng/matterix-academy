"""Physical instrument authority: qualified profiles, gateway credentials and leases.

This is the real-device execution service PRODUCT-SCOPE.md reserves: it owns
physical run authorization, instrument exclusivity, recovery holds and records
of actual observations. Simulation qualification never grants anything here.

Records are system-scoped (``system#instruments``), never learner-owned. A
learner's onboarding device declaration may be *linked* to an instrument by an
operator; the link is server-owned and only exposes evidence, not control.
"""

from __future__ import annotations

import copy
import hashlib
import re
import secrets
import time

from fastapi import HTTPException
from labtwin import workflows
from labtwin.checks import validate_specs
from labtwin.wire import fingerprint

from .broker import CommandBroker
from .store import Conflict, Write

INSTRUMENTS = "system#instruments"
GATEWAYS = "system#gateways"
RECONCILIATIONS = "system#instrument-reconciliations"
GATEWAY_PREFIX = "gw."
INSTRUMENT_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
LEASE_MAX_S = 3600


def revised(record, **changes):
    return {**copy.deepcopy(record), **changes, "version": record["version"] + 1}


def device_target(instrument_id):
    return f"device:{instrument_id}"


def qualified_sha(profile):
    return fingerprint(workflows.qualified_profile(profile))


def gateway_credential(store, authorization: str, now=None):
    """Verify ``Bearer gw.<gateway_id>.<secret>`` against the gateway registry only."""
    if not authorization.startswith("Bearer " + GATEWAY_PREFIX):
        return None
    token = authorization[7:]
    gateway_id, separator, secret = token[len(GATEWAY_PREFIX) :].partition(".")
    if not separator or len(secret) < 32 or not INSTRUMENT_ID.fullmatch(gateway_id):
        return None
    record = store.get(GATEWAYS, gateway_id)
    if (
        not record
        or record.get("revoked", True)
        or record.get("credential_expires", 0) <= (now if now is not None else time.time())
        or not secrets.compare_digest(
            record.get("token_digest", ""), hashlib.sha256(token.encode()).hexdigest()
        )
    ):
        return None
    return record


class InstrumentService:
    def __init__(self, store, clock=time.time):
        self.store, self.clock = store, clock

    # ------------------------------------------------------------------ registry

    def get(self, instrument_id):
        record = self.store.get(INSTRUMENTS, instrument_id)
        if record is None:
            raise HTTPException(404, "Instrument not found")
        return record

    def list(self):
        return self.store.partition(INSTRUMENTS, limit=100)

    def register(self, instrument_id, name, profile):
        """Register a reviewed hardware profile. Re-registration with the same profile is idempotent."""
        if not INSTRUMENT_ID.fullmatch(instrument_id or ""):
            raise ValueError("Invalid instrument ID")
        workflows.validate_profile(profile, hardware=True)
        if profile["device_id"] != instrument_id:
            raise ValueError("Profile device_id must equal the instrument ID")
        old = self.store.get(INSTRUMENTS, instrument_id)
        if old:
            if old["qualified_profile_sha256"] != qualified_sha(profile):
                raise ValueError(
                    "Instrument exists with a different qualified profile; approve a calibration revision instead"
                )
            return old
        record = {
            "version": 1,
            "instrument_id": instrument_id,
            "name": (name or instrument_id).strip()[:80] or instrument_id,
            "model": workflows.model(profile),
            "profile": copy.deepcopy(profile),
            "qualified_profile_sha256": qualified_sha(profile),
            "calibration_revision": None,
            "sim_corrections": [],
            "lease": None,
            "validation_checks": {},
            "tolerances": {},
            "created_at": self.clock(),
        }
        self.store.put(INSTRUMENTS, instrument_id, record, None)
        return record

    def configure_validation(self, instrument_id, *, expected_version, checks, tolerances):
        record = self.get(instrument_id)
        if record["version"] != expected_version:
            raise Conflict
        if not isinstance(checks, dict) or not isinstance(tolerances, dict):
            raise HTTPException(
                422, "Checks must map actions to specs; tolerances map fields to numbers"
            )
        actions = {
            op["action"] for op in workflows.make_plan(record["profile"], "probe")["operations"]
        }
        for action, specs in checks.items():
            if action not in actions:
                raise HTTPException(422, f"Unknown workflow action: {action}")
            try:
                validate_specs(specs)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
        for field, value in tolerances.items():
            if (
                not isinstance(field, str)
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0 <= value < 1e6
            ):
                raise HTTPException(422, "Tolerances must be finite non-negative numbers")
        changed = revised(record, validation_checks=checks, tolerances=tolerances)
        self.store.put(INSTRUMENTS, instrument_id, changed, record["version"])
        return changed

    # ------------------------------------------------------------------ gateway credentials

    def issue_gateway(self, instrument_id, gateway_id, *, replace=False):
        """Return a new secret once. Replacement revokes every other gateway of that instrument."""
        self.get(instrument_id)
        if not INSTRUMENT_ID.fullmatch(gateway_id or ""):
            raise ValueError("Invalid gateway ID")
        existing = [
            g
            for g in self.store.partition(GATEWAYS, limit=100)
            if g["instrument_id"] == instrument_id
        ]
        active = [g for g in existing if not g.get("revoked")]
        if active and not replace:
            raise ValueError(
                "This instrument already has an active gateway; use replace after stopping it"
            )
        if self.store.get(GATEWAYS, gateway_id):
            raise ValueError("Gateway ID was used before; choose a new installation ID")
        token = f"{GATEWAY_PREFIX}{gateway_id}.{secrets.token_urlsafe(48)}"
        record = {
            "version": 1,
            "gateway_id": gateway_id,
            "instrument_id": instrument_id,
            "credential_version": 1,
            "token_digest": hashlib.sha256(token.encode()).hexdigest(),
            "credential_expires": self.clock() + 90 * 86400,
            "revoked": False,
            "worker_class": "device",
        }
        writes = [Write(GATEWAYS, gateway_id, record, None)]
        writes += [
            Write(GATEWAYS, g["gateway_id"], revised(g, revoked=True), g["version"]) for g in active
        ]
        self.store.transact(writes)
        if active:
            CommandBroker(self.store, clock=self.clock).hold(
                device_target(instrument_id),
                "Gateway credential replaced. Stop the old gateway and reconcile before a new run.",
            )
        return token, record

    def gateway(self, gateway_id):
        record = self.store.get(GATEWAYS, gateway_id)
        if (
            not record
            or record.get("revoked")
            or record.get("credential_expires", 0) <= self.clock()
        ):
            raise HTTPException(403, "Gateway credential is inactive")
        return record

    # ------------------------------------------------------------------ identity checks

    def check_registration(self, instrument_id, profile):
        """A gateway must present exactly the qualified profile; silent substitution is refused."""
        record = self.get(instrument_id)
        try:
            workflows.validate_profile(profile, hardware=True)
        except ValueError as exc:
            return str(exc)
        if profile.get("device_id") != instrument_id:
            return "Credential belongs to another instrument"
        if qualified_sha(profile) != record["qualified_profile_sha256"]:
            return "Gateway device/model/calibration profile differs from the qualified profile"
        return ""

    def inspect_check(self, instrument_id, value):
        record = self.get(instrument_id)
        if (
            not isinstance(value, dict)
            or value.get("server_uuid") != record["profile"]["real"]["server_uuid"]
            or value.get("is_simulating") is not False
        ):
            return "Connector identity or physical mode differs; reconciliation rejected"
        return ""

    # ------------------------------------------------------------------ leases

    def acquire(self, instrument_id, holder, *, seconds, kind):
        """One control source per instrument: Lab Onboarding runs or one external orchestrator."""
        if kind not in {"run", "external"} or not isinstance(holder, str) or not holder:
            raise ValueError("Invalid lease holder")
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not 0 < seconds <= LEASE_MAX_S
        ):
            raise HTTPException(422, "Lease duration must be within (0, 3600] seconds")
        record = self.get(instrument_id)
        lease = record.get("lease")
        now = self.clock()
        if lease and lease["expires"] > now and lease["holder"] != holder:
            raise HTTPException(409, "Instrument is leased by another control source")
        changed = revised(record, lease={"holder": holder, "kind": kind, "expires": now + seconds})
        self.store.put(INSTRUMENTS, instrument_id, changed, record["version"])
        return changed["lease"]

    def release(self, instrument_id, holder):
        record = self.get(instrument_id)
        lease = record.get("lease")
        if not lease or lease["holder"] != holder:
            return False
        self.store.put(INSTRUMENTS, instrument_id, revised(record, lease=None), record["version"])
        return True

    def lease_holder(self, instrument_id):
        lease = self.get(instrument_id).get("lease")
        return lease["holder"] if lease and lease["expires"] > self.clock() else None

    # ------------------------------------------------------------------ calibration

    def apply_calibration(
        self, instrument_id, *, expected_version, revision_id, corrections, profile
    ):
        """Pin an approved calibration revision. A changed profile changes the qualified identity."""
        record = self.get(instrument_id)
        if record["version"] != expected_version:
            raise Conflict
        workflows.validate_profile(profile, hardware=True)
        if profile["device_id"] != instrument_id or workflows.model(profile) != record["model"]:
            raise HTTPException(
                422, "Calibrated profile must describe the same instrument and model"
            )
        changed = revised(
            record,
            profile=copy.deepcopy(profile),
            qualified_profile_sha256=qualified_sha(profile),
            calibration_revision=revision_id,
            sim_corrections=copy.deepcopy(corrections),
        )
        self.store.put(INSTRUMENTS, instrument_id, changed, record["version"])
        return changed
