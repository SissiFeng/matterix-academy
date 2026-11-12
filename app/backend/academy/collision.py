"""The solid shape of a placed twin, as boxes the arm must stay clear of.

A twin started from a ChemLab-Assets model takes the boxes measured from that model's
surface (chemlab_collision.json, from scripts/library-models/chemlab_collision.py), so an
enclosure keeps its openings. A deck without a measured model is an open-fronted
enclosure around its deck. Anything else is the twin's own parts.
"""

import json
from functools import cache
from pathlib import Path

WALL = 0.03  # metres: walls and roof of an enclosure drawn around a deck
HEAD = 0.15  # metres from every side: nearer the middle than this, a part is the moving head


@cache
def _measured():
    return json.loads((Path(__file__).parent / "chemlab_collision.json").read_text())


def _extent(spec):
    parts = spec["parts"]
    low = [min(p["position"][i] - p["size"][i] / 2 for p in parts) for i in (0, 2)]
    high = [max(p["position"][i] + p["size"][i] / 2 for p in parts) for i in (0, 2)]
    return low, high, max(p["position"][1] + p["size"][1] / 2 for p in parts)


def shapes(twin):
    """(centre, half size) of every box, in the twin's frame (metres, y up from the bench)."""
    spec = twin["spec"]
    (x0, z0), (x1, z1), height = _extent(spec)
    width, depth = x1 - x0, z1 - z0
    cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
    asset = twin.get("asset") or {}
    measured = twin.get("source") == "chemlab_asset" and _measured().get(asset.get("id"))
    level = spec.get("level_m")
    # Only a deck served through its front is an enclosure; one loaded from above is open.
    deck = spec.get("sites") and level is not None and spec.get("access") == "front"
    if measured:
        boxes = [
            (
                (cx + bx * width, by * height, cz + bz * depth),
                (hx * width, hy * height, hz * depth),
            )
            for bx, by, bz, hx, hy, hz in measured
        ]
        if deck:
            # The head over a deck is drawn wherever the model parked it; it moves aside
            # for a handoff, so what hangs free over the middle of the deck is left out.
            boxes = [
                (c, h)
                for c, h in boxes
                if c[1] - h[1] < level
                or abs(c[0] - cx) + h[0] > width / 2 - HEAD
                or abs(c[2] - cz) + h[2] > depth / 2 - HEAD
            ]
        return boxes
    if deck and level + 2 * WALL < height:
        side = (WALL / 2, (height - level) / 2, depth / 2)
        enclosure = [
            ((cx, level / 2, cz), (width / 2, level / 2, depth / 2)),
            ((cx, height - WALL / 2, cz), (width / 2, WALL / 2, depth / 2)),
            (
                (cx, (height + level) / 2, z0 + WALL / 2),
                (width / 2, (height - level) / 2, WALL / 2),
            ),
            ((x0 + WALL / 2, (height + level) / 2, cz), side),
            ((x1 - WALL / 2, (height + level) / 2, cz), side),
        ]
        # A deck level with the bench has no slab under it.
        return [(c, h) for c, h in enclosure if min(h) > 0]
    return [(tuple(p["position"]), tuple(v / 2 for v in p["size"])) for p in spec["parts"]]
