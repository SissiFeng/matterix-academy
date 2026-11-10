"""Deck slots of liquid handlers whose layout is published, as twin sites.

Slot pitches come from the Opentrons deck definitions (ot2_standard, ot3_standard), the
same data the workcell case draws. Positions are slot centres on the twin's top face,
centred on its footprint: x to the right, z toward the front (row 1 or D). The twin is
still one planning box, so a site is reached from above the box top, not down inside
the enclosure. Teaching geometry, not calibrated deck coordinates.
"""

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


def deck_sites(kind):
    pitch_x, pitch_z, rows = DECKS[kind]
    cols = max(len(r) for r in rows)
    sites = []
    for r, row in enumerate(rows):
        for c, key in enumerate(row):
            x = (c - (cols - 1) / 2) * pitch_x
            z = ((len(rows) - 1) / 2 - r) * pitch_z
            sites.append({"key": key, "x": round(x, 4) + 0.0, "z": round(z, 4) + 0.0})
    return sites
