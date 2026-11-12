"""Deck slots of liquid handlers whose layout is published, as twin sites.

Slot pitches come from the Opentrons deck definitions (ot2_standard, ot3_standard), the
same data the workcell case draws. Positions are slot centres on the twin's top face,
centred on its footprint: x to the right, z toward the front (row 1 or D). The deck is
inside the enclosure, at LEVELS above the bench, and an arm reaches it through the open
front. Teaching geometry, not calibrated deck coordinates.
"""

# Deck surface above the bench (metres), as in the workcell case.
LEVELS = {"ot2": 0.1, "flex": 0.153}

SLOT = (0.128, 0.086)  # ANSI/SLAS footprint, metres

# (column pitch, row pitch, slot names front row first, left to right)
DECKS = {
    "ot2": (0.1325, 0.0905, (("1", "2", "3"), ("4", "5", "6"), ("7", "8", "9"), ("10", "11"))),
    # A3 holds the movable trash in the Flex workcell case.
    "flex": (
        0.164,
        0.107,
        (("D1", "D2", "D3"), ("C1", "C2", "C3"), ("B1", "B2", "B3"), ("A1", "A2")),
    ),
}


def deck_sites(kind, at=(0.0, 0.0)):
    """Slot centres; `at` is where the deck's centre sits on the footprint (x, z)."""
    pitch_x, pitch_z, rows = DECKS[kind]
    cols = max(len(r) for r in rows)
    sites = []
    for r, row in enumerate(rows):
        for c, key in enumerate(row):
            x = at[0] + (c - (cols - 1) / 2) * pitch_x
            z = at[1] + ((len(rows) - 1) / 2 - r) * pitch_z
            sites.append({"key": key, "x": round(x, 4) + 0.0, "z": round(z, 4) + 0.0})
    return sites
