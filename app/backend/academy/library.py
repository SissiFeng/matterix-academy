"""Search across the pinned starting-point collections (SimReady and ChemLab)."""

import re

from .chemlab import CHEMLAB
from .simready import SIMREADY
from .workcell_models import catalog as workcell_catalog

# Registered 3D models first: they are the instruments drawn in full in the 3D view.
COLLECTIONS = {"workcell": workcell_catalog(), "simready": SIMREADY, "chemlab": CHEMLAB}


def summary(collection, asset_id, asset):
    x, y, z = asset["spec"]["parts"][0]["size"]  # Y-up twin box
    return {
        "collection": collection,
        "id": asset_id,
        "name": asset["spec"]["name"],
        "label": asset["label"],
        "provider": asset["provider"],
        "domain": asset.get("domain", ""),
        "license": asset["license"],
        "attribution": asset["attribution"],
        "size_m": [x, z, y],  # width, depth, height
        "operations": asset["spec"]["operations"],
    }


def haystack(asset):
    fields = [asset["label"], asset["spec"]["name"], asset["provider"], asset.get("domain", "")]
    return " ".join(fields).lower()


def search(query, limit=16):
    """Every query word must appear; name matches, featured entries and models rank first."""
    words = re.findall(r"[\w.+-]+", query.lower())
    hits = []
    for collection, assets in COLLECTIONS.items():
        for asset_id, asset in assets.items():
            featured = asset.get("featured", collection == "simready")
            if words:
                text = haystack(asset)
                if not all(w in text for w in words):
                    continue
                in_name = all(w in asset["spec"]["name"].lower() for w in words)
            elif not featured:
                continue
            else:
                in_name = True
            # Instruments with a full 3D model come before footprint-only ones.
            rank = (not in_name, not featured, collection != "workcell", asset["spec"]["name"])
            hits.append((rank, collection, asset_id))
    hits.sort()
    return {
        "size": sum(map(len, COLLECTIONS.values())),
        "total": len(hits),
        "results": [summary(c, i, COLLECTIONS[c][i]) for _, c, i in hits[:limit]],
    }


# Photo matching: Astra picks from this closed list; the server only ever offers listed keys.
KEYS = [f"{c}:{i}" for c, assets in COLLECTIONS.items() for i in assets]
MATCHES = 3


def listing():
    """One line per library entry, given to Astra alongside the photo."""
    return "\n".join(
        f"{c}:{i} | {a['label']}" for c, assets in COLLECTIONS.items() for i, a in assets.items()
    )


def squash(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def candidates(identification):
    """Astra's pick and alternatives, then entries whose text matches the model it read.

    A candidate is `verified` when the model text Astra read off the instrument appears
    in that entry's label, so a label-confirmed match is distinguishable from a visual guess.
    """
    model = identification["model"].strip()
    picked = [identification["library_id"], *identification["alternatives"]]
    read = [f"{r['collection']}:{r['id']}" for r in search(model, limit=MATCHES)["results"]]
    keys = [k for k in dict.fromkeys(picked + (read if model else [])) if k in KEYS]
    found = []
    for key in keys[:MATCHES]:
        collection, asset_id = key.split(":", 1)
        asset = COLLECTIONS[collection][asset_id]
        found.append(
            {
                **summary(collection, asset_id, asset),
                "suggested_by": "astra" if key in picked else "label_text",
                "verified": len(squash(model)) >= 3 and squash(model) in squash(asset["label"]),
            }
        )
    return found
