"""Time the bench layout search on fixed teaching cells.

For each cell: seconds to the first feasible layout, layouts found within a budget,
and full workflow checks spent. Synthetic geometry only, as checked by the planner;
the numbers describe this search on this machine, not a physical workcell.

    uv run python scripts/bench-layout-search.py [--budget SECONDS]
"""

import argparse
import sys
import time
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app/backend"))

from academy import layout_search  # noqa: E402
from academy.chemlab import CHEMLAB  # noqa: E402
from academy.simple_twins import TEMPLATES  # noqa: E402
from academy.workcell_models import catalog  # noqa: E402


def twin(twin_id, spec):
    return {"id": twin_id, "spec": deepcopy(spec), "confirmed": True, "mode": "mock"}


def transfer(arm, source, target, sample="sample"):
    return {
        "device_id": arm,
        "operation": "transfer",
        "source_id": source,
        "target_id": target,
        "value": 1,
        "sample": sample,
    }


def load(device, sample="sample"):
    return {"device_id": device, "operation": "load", "value": 100, "sample": sample}


def cells():
    heater, reader, arm = TEMPLATES["heater"], TEMPLATES["reader"], TEMPLATES["transfer-arm"]
    ot2 = catalog()["opentrons-ot2"]["spec"]
    flex = CHEMLAB["opentrons_flex_single_5_1000ul"]["spec"]
    yield (
        "heater → reader",
        {"h": twin("h", heater), "r": twin("r", reader), "a": twin("a", arm)},
        [load("h"), transfer("a", "h", "r")],
        [],
    )
    yield (
        "heater → reader → heater, plus a spare",
        {
            "h": twin("h", heater),
            "r": twin("r", reader),
            "a": twin("a", arm),
            "s": twin("s", TEMPLATES["liquid-handler"]),
        },
        [load("h"), transfer("a", "h", "r"), transfer("a", "r", "h")],
        [],
    )
    plates = [
        load("o", "plate-a"),
        load("o", "plate-b"),
        load("f", "plate-c"),
        load("f", "plate-d"),
    ]
    deck = {"o": twin("o", ot2), "f": twin("f", flex), "a": twin("a", arm)}
    yield ("OT-2 ↔ Flex, 4 plates", deck, [*plates, transfer("a", "o", "f", "plate-a")], [])
    yield (
        "OT-2 ↔ Flex, arm reaches 2 slots on each",
        deck,
        [*plates, transfer("a", "o", "f", "plate-a")],
        [
            {"kind": "reach_slots", "twin_id": "o", "count": 2},
            {"kind": "reach_slots", "twin_id": "f", "count": 2},
        ],
    )


def bench(twins, steps, constraints, budget):
    found, checked, start, first = [], 0, 0, None
    began = time.perf_counter()
    while start is not None and time.perf_counter() - began < budget:
        chunk = layout_search.search_layouts(
            twins,
            {"width": 2.4, "depth": 1.6},
            steps,
            start=start,
            avoid=[c["layout"]["placements"] for c in found],
            constraints=constraints,
        )
        if chunk["candidates"] and first is None:
            first = time.perf_counter() - began
        found += chunk["candidates"]
        checked += chunk["checked"]
        start = chunk["next"]
    return first, len(found), checked, time.perf_counter() - began, start is None


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=float, default=30.0, help="seconds per cell")
    args = parser.parse_args(argv)
    print(f"{'cell':44} {'first':>7} {'layouts':>8} {'checked':>8} {'seconds':>8}")
    for name, twins, steps, constraints in cells():
        first, count, checked, spent, done = bench(twins, steps, constraints, args.budget)
        print(
            f"{name:44} {'—' if first is None else f'{first:.1f}':>7} {count:8d} {checked:8d} "
            f"{spent:8.1f}{'  (all arrangements)' if done else ''}"
        )


if __name__ == "__main__":
    main(sys.argv[1:])
