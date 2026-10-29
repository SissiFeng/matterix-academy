"""Declarative one-step validation gates, as JSON records a durable store can hold.

A receipt binds a simulated outcome and its explicit check verdicts to one exact
operation, one starting-state revision and one configuration revision. The
store that holds it must consume it at most once (a conditional write) in the
same transaction that queues the real dispatch. Passing is a prediction, never
a physical safety guarantee.
"""

from __future__ import annotations

import math

from .models import Evidence, Outcome, Status
from .wire import fingerprint, outcome_from_dict, plain

CHECK_STATUSES = ("passed", "failed", "unknown")


class ValidationRejected(RuntimeError):
    """Hold dispatch; reconcile or obtain a new prediction."""


def validate_specs(specs):
    """Validate explicit post-state checks. An empty list gates on execution success alone."""
    if not isinstance(specs, list):
        raise ValueError("Validation checks must be a list")
    names = []
    common = {"name", "field", "unit", "frame"}
    for spec in specs:
        if not isinstance(spec, dict) or set(spec) not in (common | {"min", "max"}, common | {"equals"}):
            raise ValueError("Check must define either min/max or equals with name/field/unit/frame")
        if any(not isinstance(spec[k], str) for k in common) or not spec["name"] or not spec["field"]:
            raise ValueError("Invalid validation check identity")
        if "min" in spec:
            if (
                any(
                    isinstance(spec[k], bool) or not isinstance(spec[k], (float, int)) or not math.isfinite(spec[k])
                    for k in ("min", "max")
                )
                or spec["min"] > spec["max"]
            ):
                raise ValueError("Invalid numeric check range")
        elif not isinstance(spec["equals"], (str, bool, int, float)) or (
            isinstance(spec["equals"], float) and not math.isfinite(spec["equals"])
        ):
            raise ValueError("Equality check requires a finite scalar")
        names.append(spec["name"])
    if len(set(names)) != len(names):
        raise ValueError("Duplicate check names")
    return tuple(names)


def _outcome(value):
    return value if isinstance(value, Outcome) else outcome_from_dict(value)


def evaluate(outcome, specs):
    """Check only supplied simulated facts; missing observations cannot certify a prediction."""
    outcome = _outcome(outcome)
    results = []
    for spec in specs:
        fact = outcome.observation.facts.get(spec["field"]) if outcome.observation else None
        status, reason = "unknown", "Missing simulated fact or incompatible units/frame"
        if (
            fact is not None
            and fact.value is not None
            and fact.evidence is Evidence.SIMULATED
            and (fact.unit, fact.frame) == (spec["unit"], spec["frame"])
        ):
            if "equals" in spec:
                passed = type(fact.value) is type(spec["equals"]) and fact.value == spec["equals"]
                status = "passed" if passed else "failed"
                reason = f"Predicted {spec['field']}={fact.value!r}; required {spec['equals']!r}"
            elif isinstance(fact.value, (int, float)) and not isinstance(fact.value, bool):
                status = "passed" if spec["min"] <= fact.value <= spec["max"] else "failed"
                reason = f"Predicted {spec['field']}={fact.value}; permitted [{spec['min']}, {spec['max']}]"
        results.append({"name": spec["name"], "status": status, "reason": reason})
    return results


def state_revision(observation):
    """Revision of a starting state: its source and facts, never its timestamp."""
    if observation is None:
        raise ValidationRejected("A known starting-state observation is required")
    data = plain(observation)
    facts = data.get("facts") or {}
    if not facts or any(f.get("value") is None or f.get("evidence") == "unknown" for f in facts.values()):
        raise ValidationRejected("Fresh known starting-state observation required")
    return fingerprint({"source": data["source"], "facts": facts})


def issue_receipt(*, operation, sim_outcome, state, configuration, specs, now, validity_s):
    """Produce immutable prediction evidence for one exact operation and context."""
    if isinstance(validity_s, bool) or not isinstance(validity_s, (int, float)) or not 0 < validity_s <= 3600:
        raise ValueError("Receipt validity must be within (0, 3600] seconds")
    validate_specs(specs)
    outcome = _outcome(sim_outcome)
    checks = evaluate(outcome, specs) if outcome.status is Status.SUCCEEDED else []
    passed = outcome.status is Status.SUCCEEDED and all(c["status"] == "passed" for c in checks)
    return {
        "schema": "labtwin.receipt/1",
        "operation_sha256": fingerprint(operation),
        "state_revision": state,
        "configuration_revision": configuration,
        "sim_status": outcome.status.value,
        "sim_error": outcome.error,
        "checks": checks,
        "required": [s["name"] for s in specs],
        "passed": passed,
        "issued_at": now,
        "expires_at": now + validity_s,
    }


def verify_receipt(receipt, *, operation, state, configuration, now):
    """Fail closed on a changed operation, starting state, configuration, expiry or failed check."""
    if not isinstance(receipt, dict) or receipt.get("schema") != "labtwin.receipt/1":
        raise ValidationRejected("Receipt is missing or foreign")
    if receipt["operation_sha256"] != fingerprint(operation):
        raise ValidationRejected("Operation changed after prediction")
    if receipt["state_revision"] != state or receipt["configuration_revision"] != configuration:
        raise ValidationRejected("Starting state or configuration changed after prediction")
    if now >= receipt["expires_at"]:
        raise ValidationRejected("Validation receipt expired")
    if not receipt["passed"]:
        raise ValidationRejected("DT failed, timed out, or required checks did not pass")
    return receipt
