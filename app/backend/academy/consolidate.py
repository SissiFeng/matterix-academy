"""Instruments a workflow could do without, checked by rerunning the mock contract.

For each pair of stations, the steps of one are moved onto the other and transfers
between the two disappear. A suggestion is offered only when the rewritten workflow
still passes `execute_mock`: same vessel, volume, limits, consumables and enough free
slots. It says nothing about throughput or whether a lab would want to share the deck.
"""

from .mock_contract import PlanError, execute_mock, site_keys


def _rewrite(steps, drop, into):
    out = []
    for step in steps:
        ends = {step.get("source_id"), step.get("target_id")}
        if step["operation"] == "transfer" and ends == {drop, into}:
            continue  # the sample no longer moves between them
        moved = {
            **step,
            **{k: into for k in ("device_id", "source_id", "target_id") if step.get(k) == drop},
        }
        # Slots named on the dropped instrument mean nothing on the other one.
        if step["device_id"] == drop and step["operation"] == "load":
            moved["site"] = ""
        if step.get("source_id") == drop:
            moved["source_site"] = ""
        if step.get("target_id") == drop:
            moved["target_site"] = ""
        out.append(moved)
    return out


def _peak(trace, device):
    return max(
        (sum(1 for s in entry["samples"].values() if s["location"] == device) for entry in trace),
        default=0,
    )


def consolidation(twins, steps):
    """Pairs (drop, into) where `into` can take every step `drop` performs."""
    if not steps:
        return []
    stations = [
        t
        for t in dict.fromkeys(
            s[k] for s in steps for k in ("device_id", "source_id", "target_id") if s.get(k)
        )
        if "transfer" not in twins[t]["spec"]["operations"]
    ]
    before = execute_mock(twins, steps)
    out = []
    for drop in stations:
        for into in stations:
            if into == drop:
                continue
            rewritten = _rewrite(steps, drop, into)
            try:
                trace = execute_mock(twins, rewritten)
            except PlanError:
                continue
            peak = _peak(trace, into)
            out.append(
                {
                    "drop_id": drop,
                    "into_id": into,
                    "extra_slots": max(0, peak - _peak(before, into)),
                    "free_slots": len(site_keys(twins[into]["spec"])) - peak,
                    "transfers_saved": sum(s["operation"] == "transfer" for s in steps)
                    - sum(s["operation"] == "transfer" for s in rewritten),
                    "message": f"{twins[into]['spec']['name']} can also run the "
                    f"{twins[drop]['spec']['name']} steps"
                    + (
                        f" with {peak - _peak(before, into)} more slots"
                        if peak > _peak(before, into)
                        else ""
                    ),
                }
            )
    out.sort(key=lambda c: (-c["transfers_saved"], c["extra_slots"], c["message"]))
    return out[:4]
