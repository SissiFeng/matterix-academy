"""Sim-to-real evidence rows. Read-only; nothing here changes a model automatically."""

from __future__ import annotations

import math

from .wire import plain

ROW_SCHEMA = "sim2real.pair/1"
SUMMARY_SCHEMA = "sim2real.summary/1"
REAL_EVIDENCE = ("hardware_reported", "software_tracked")


def side(outcome, started=None, finished=None):
    """Normalize one recorded side: status, error, observation and optional duration."""
    if outcome is None:
        return None
    outcome = plain(outcome)
    result = {
        "status": outcome.get("status"),
        "error": outcome.get("error", ""),
        "observation": outcome.get("observation"),
    }
    if isinstance(started, (int, float)) and isinstance(finished, (int, float)):
        result["duration_s"] = finished - started
    return result


def residuals(real, sim):
    """Numeric (real - sim) deltas for comparable facts; everything else is omitted.

    Comparable means: same unit and frame, real evidence is hardware/tracked, sim
    evidence is simulated, and both values are finite numbers. Firmware millimetres
    and native joint metres are never subtracted from each other.
    """
    facts_real = ((real or {}).get("observation") or {}).get("facts") or {}
    facts_sim = ((sim or {}).get("observation") or {}).get("facts") or {}
    rows = []
    for name in sorted(set(facts_real) & set(facts_sim)):
        a, b = facts_real[name], facts_sim[name]
        if (
            a.get("evidence") in REAL_EVIDENCE
            and b.get("evidence") == "simulated"
            and (a.get("unit"), a.get("frame")) == (b.get("unit"), b.get("frame"))
            and all(
                isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                for v in (a.get("value"), b.get("value"))
            )
        ):
            rows.append(
                {
                    "field": name,
                    "unit": a.get("unit", ""),
                    "frame": a.get("frame", ""),
                    "real": a["value"],
                    "sim": b["value"],
                    "delta": a["value"] - b["value"],
                }
            )
    return rows


def pair_row(*, base, operation, real, sim, sim_source, gate):
    """One operation's real and simulated evidence plus workflow/profile identity."""
    op = plain(operation)
    return {
        "schema": ROW_SCHEMA,
        **base,
        "operation_id": op["operation_id"],
        "action": op["action"],
        "parameters": op["parameters"],
        "real": real,
        "sim": sim,
        "sim_source": sim_source if sim else None,
        "gate": gate,
        "residuals": residuals(real, sim),
    }


def summarize(rows):
    """Aggregate residuals per (action, field, unit, frame) and outcome agreement counts."""
    groups, counts = {}, {"rows": 0, "paired": 0, "status_agree": 0, "gate_held": 0}
    for row in rows:
        counts["rows"] += 1
        if row["real"] and row["sim"]:
            counts["paired"] += 1
            counts["status_agree"] += row["real"].get("status") == row["sim"].get("status")
        counts["gate_held"] += row["gate"] == "held"
        for r in row["residuals"]:
            groups.setdefault((row["action"], r["field"], r["unit"], r["frame"]), []).append(r["delta"])
    fields = []
    for (action, field, unit, frame), deltas in sorted(groups.items()):
        fields.append(
            {
                "action": action,
                "field": field,
                "unit": unit,
                "frame": frame,
                "n": len(deltas),
                "mean_delta": sum(deltas) / len(deltas),
                "max_abs_delta": max(abs(d) for d in deltas),
                "rms_delta": math.sqrt(sum(d * d for d in deltas) / len(deltas)),
            }
        )
    return {"schema": SUMMARY_SCHEMA, **counts, "residuals": fields}


def propose_offsets(summary, *, min_samples=3):
    """Candidate per-field sim corrections (mean real - sim) for operator review.

    Only fields with at least ``min_samples`` comparable residuals are proposed; the
    caller stores a proposal, a person approves it, and only then does a new
    model/calibration revision exist. Nothing is applied by this function.
    """
    if type(min_samples) is not int or min_samples < 1:
        raise ValueError("min_samples must be a positive integer")
    merged = {}
    for item in summary.get("residuals", []):
        key = (item["field"], item["unit"], item["frame"])
        n, total = merged.get(key, (0, 0.0))
        merged[key] = (n + item["n"], total + item["mean_delta"] * item["n"])
    return [
        {"field": field, "unit": unit, "frame": frame, "n": n, "offset": total / n}
        for (field, unit, frame), (n, total) in sorted(merged.items())
        if n >= min_samples
    ]
