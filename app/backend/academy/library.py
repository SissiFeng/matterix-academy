"""Search across the pinned starting-point collections: workcell models, SimReady, ChemLab."""

import difflib
import math
import re

from .chemlab import CHEMLAB
from .simready import SIMREADY
from .workcell_models import catalog as workcell_catalog

# Registered 3D models first: they are the instruments drawn in full in the 3D view.
COLLECTIONS = {"workcell": workcell_catalog(), "simready": SIMREADY, "chemlab": CHEMLAB}
# Library entries with an instrument lesson in Meet the instruments.
LESSONS = {
    ("workcell", "opentrons-ot2"): "ot2",
    ("chemlab", "opentrons_flex_single_5_1000ul"): "flex",
}


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
        "lesson": LESSONS.get((collection, asset_id)),
    }


# What people type for an instrument, and the catalogue words it stands for. A term may
# stand for several phrasings; an entry matches when it has every word of any one of them.
ALIASES = {
    "rotavap": ["rotary evaporator"],
    "rotovap": ["rotary evaporator"],
    "fridge": ["refrigerator", "refrigerated"],
    "pipette": ["liquid handling", "liquid handler"],
    "pipettor": ["liquid handling", "liquid handler"],
    "pipetting": ["liquid handling", "liquid handler"],
    "liquid handler": ["liquid handling", "liquid handler"],
    "scale": ["balance"],
    "ph meter": ["ph"],
    "plate reader": ["microplate reader", "plate reader"],
    "hot plate": ["hotplate"],
    "stir plate": ["hotplate stirrer"],
    "glove box": ["glovebox"],
    "mass spec": ["mass spectrometer"],
    "ms": ["mass spectrometer"],
    "gc ms": ["gas chromatograph"],
    "gcms": ["gas chromatograph"],
    "lc": ["hplc"],
    "lc ms": ["hplc"],
    "lcms": ["hplc"],
    "icp ms": ["icp mass"],
    "icp oes": ["icp optical"],
    "aas": ["atomic absorption"],
    "toc": ["total organic carbon"],
    "xrd": ["x ray diffractometer"],
    "xps": ["x ray photoelectron"],
    "xrf": ["xrf"],
    "saxs": ["small angle x ray"],
    "ct": ["computed tomography"],
    "sem": ["scanning electron microscope"],
    "tem": ["transmission electron microscope"],
    "afm": ["atomic force microscope"],
    "stm": ["scanning tunneling microscope"],
    "dsc": ["differential scanning calorimeter"],
    "tga": ["thermogravimetric"],
    "ir": ["ft ir"],
    "esr": ["epr"],
    "viscometer": ["rheometer"],
    "lyophilizer": ["freeze dryer"],
    "lyophiliser": ["freeze dryer"],
    "sonicator": ["ultrasonic"],
    "homogenizer": ["disperser", "ultrasonic processor"],
    "homogeniser": ["disperser", "ultrasonic processor"],
    "pcr": ["qpcr"],
    "thermocycler": ["qpcr"],
    "fluorometer": ["spectrofluorometer"],
    "fluorimeter": ["spectrofluorometer"],
    "bet": ["physisorption"],
    "cobot": ["collaborative arm"],
    "robot arm": ["arm"],
    "chiller": ["circulator"],
    "water bath": ["circulator", "bath"],
    "vacuum pump": ["vacuum pumping"],
    "mfc": ["mass flow controller"],
    "kiln": ["furnace"],
    "tensile tester": ["universal testing machine"],
    "bsc": ["biological safety cabinet"],
    "analyser": ["analyzer"],
    "vapor": ["vapour"],
    # What the instrument is for. `can…` words are added to every entry from the
    # operations its twin supports, so a purpose finds instruments whose names never say it.
    "mix": ["canmix"],
    "mixing": ["canmix", "mixer"],
    "stir": ["canmix", "stirrer"],
    "stirring": ["canmix", "stirrer"],
    "shake": ["canmix", "shaker"],
    "blend": ["canmix"],
    "heat": ["canheat"],
    "heating": ["canheat"],
    "warm": ["canheat"],
    "incubate": ["canheat", "incubator", "incubated"],
    "measure": ["canread"],
    "read": ["canread"],
    "analyze": ["canread"],
    "analyse": ["canread"],
    "detect": ["canread"],
    "transfer": ["cantransfer"],
    "move": ["cantransfer"],
    "weigh": ["balance"],
    "weighing": ["balance"],
    "dispense": ["liquid handling", "liquid handler", "dosing", "pump"],
    "dilute": ["liquid handling", "liquid handler"],
    "aliquot": ["liquid handling", "liquid handler"],
    "store": ["refrigerator", "freezer", "cabinet", "storage"],
    "storage": ["refrigerator", "freezer", "cabinet"],
    "cool": ["refrigerator", "refrigerated", "freezer", "circulator"],
    "dry": ["dryer", "drying"],
    "wash": ["washer", "cleaning"],
    "clean": ["washer", "cleaning"],
    "separate": ["centrifuge", "chromatograph", "extractor", "extraction"],
    "purify": ["purification", "chromatography", "extraction", "ultrafiltration"],
    "grind": ["mill"],
    "seal": ["sealer"],
    "coat": ["coater"],
}
# Purposes typed in Chinese, read as the English purpose words above.
PURPOSES_ZH = {
    "混液": "mix",
    "混合": "mix",
    "混匀": "mix",
    "搅拌": "stir",
    "振荡": "shake",
    "加热": "heat",
    "孵育": "incubate",
    "称量": "weigh",
    "称重": "weigh",
    "移液": "pipette",
    "分液": "dispense",
    "稀释": "dilute",
    "离心": "centrifuge",
    "检测": "measure",
    "测量": "measure",
    "读板": "plate reader",
    "转移": "transfer",
    "搬运": "transfer",
    "储存": "store",
    "冷藏": "fridge",
    "冷冻": "freezer",
    "干燥": "dry",
    "清洗": "wash",
    "研磨": "grind",
    "封板": "seal",
    "纯化": "purify",
    "分离": "separate",
}
LONGEST_ALIAS = max(len(key.split()) for key in ALIASES)


def squash(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def tokens(text):
    """Lower-case words; a hyphenated or slashed run also counts joined (uv-vis as uvvis)."""
    text = text.lower()
    joined = re.findall(r"[a-z0-9]+(?:[-/][a-z0-9]+)+", text)
    return re.findall(r"[a-z0-9]+", text) + [re.sub(r"[-/]", "", run) for run in joined]


def index(asset):
    """An entry's name words, all its words, and its label run together for model numbers."""
    name = set(tokens(asset["spec"]["name"]))
    other = [asset["label"], asset["provider"], asset.get("domain", "")]
    can = {f"can{operation}" for operation in asset["spec"]["operations"]}
    words = name | can | {t for field in other for t in tokens(field)}
    return name, words, squash(asset["label"])


INDEX = {(c, i): index(a) for c, assets in COLLECTIONS.items() for i, a in assets.items()}


def parse(query):
    """The query as terms; each term is the alternative phrasings (word lists) it stands for."""
    for typed, purpose in PURPOSES_ZH.items():
        query = query.replace(typed, f" {purpose} ")
    words = re.findall(r"[a-z0-9]+", query.lower())
    if query.strip() and not words:
        return [[["\0"]]]  # typed, but nothing to look for: no entry has this word
    terms, at = [], 0
    while at < len(words):
        for n in range(min(LONGEST_ALIAS, len(words) - at), 0, -1):
            typed = " ".join(words[at : at + n])
            if typed in ALIASES or n == 1:
                phrasings = [typed, *ALIASES.get(typed, [])]
                terms.append([phrase.split() for phrase in dict.fromkeys(phrasings)])
                at += n
                break
    return terms


def word_score(word, have):
    """3 for a whole word, 2 for the start of one, 1 for a longer fragment inside one."""
    for stem in dict.fromkeys([word, word.removesuffix("es"), word.removesuffix("s")]):
        if len(stem) < len(word) and len(stem) < 3:
            continue
        if stem in have:
            return 3
        if len(stem) >= 3 and any(t.startswith(stem) for t in have):
            return 2
        # Two letters inside a longer word say nothing (ph in spectrophotometer); digits
        # inside a model number do (204 in xpr204e).
        if (len(stem) >= 4 or (len(stem) >= 3 and stem.isdigit())) and any(stem in t for t in have):
            return 1
    # A slip of the keyboard still finds the word it was meant to be.
    if len(word) >= 5 and difflib.get_close_matches(word, have, n=1, cutoff=0.8):
        return 0.5
    return 0


def relevance(query, terms, entry):
    """How well an entry answers the query: its word score, or a model number typed apart
    from or run into its neighbours (rv10 for RV 10)."""
    typed = squash(query)
    model = len(typed) >= 4 and any(c.isdigit() for c in typed) and typed in entry[2]
    return score(terms, entry[1]) or (2 if model else 0)


def score(terms, have):
    """How well an entry's words answer the query, or 0 when too few terms find anything.

    One or two terms must all be found. Of three or more, most must be: a search is for
    showing everything relevant to pick from, so one stray word does not hide the rest,
    and an entry that answers every term outranks any that answers only some.
    """
    total = found_terms = 0
    for phrasings in terms:
        best = 0
        for words in phrasings:
            found = [word_score(w, have) for w in words]
            if all(found):
                best = max(best, sum(found) / len(found))
        total += best
        found_terms += bool(best)
    needed = len(terms) if len(terms) < 3 else math.ceil(len(terms) * 0.6)
    if found_terms < needed:
        return 0
    return total + (10 if found_terms == len(terms) else 0)


def search(query, limit=16):
    """Everything relevant to the query, the closest name matches first.

    A term is found as a whole word, the start of a word, a longer fragment of one or a
    near miss, in the entry's name, maker, model or domain. Common lab shorthand (rotavap,
    XRD, fridge) stands for the catalogue's wording, and plurals are read as singular.
    A purpose (mix, heat, weigh, 混液) finds the instruments whose twins can do it.
    `limit` only cuts the list shown; `total` counts every match.
    """
    terms = parse(query)
    hits = []
    for collection, assets in COLLECTIONS.items():
        for asset_id, asset in assets.items():
            featured = asset.get("featured", collection == "simready")
            entry = INDEX[collection, asset_id]
            if terms:
                found = relevance(query, terms, entry)
                if not found:
                    continue
                in_name = score(terms, entry[0])
            elif not featured:
                continue
            else:
                found = in_name = 1
            # A search puts lessons first; then instruments with a full 3D model.
            rank = (
                not in_name,
                bool(terms) and (collection, asset_id) not in LESSONS,
                -max(found, in_name),
                not featured,
                collection != "workcell",
                asset["spec"]["name"],
            )
            hits.append((rank, collection, asset_id))
    hits.sort()
    return {
        "size": sum(map(len, COLLECTIONS.values())),
        "total": len(hits),
        "results": [summary(c, i, COLLECTIONS[c][i]) for _, c, i in hits[:limit]],
    }


def browse(query="", domain="", collection="", offset=0, limit=24):
    """Every entry that has a drawn 3D model, filtered for the asset library page.

    Without a query the entries are in name order; with one, the closest matches lead.
    """
    terms = parse(query)
    drawn = [
        (c, i, a) for c, assets in COLLECTIONS.items() for i, a in assets.items() if a.get("mesh")
    ]
    found = [
        (relevance(query, terms, INDEX[c, i]) if terms else 1, c, i, a)
        for c, i, a in drawn
        if not collection or c == collection
    ]
    found = [e for e in found if e[0]]
    domains = {}
    for _, _, _, a in found:
        domains[a["domain"]] = domains.get(a["domain"], 0) + 1
    shown = sorted(
        (e for e in found if not domain or e[3]["domain"] == domain),
        key=lambda e: (
            -(e[0] + score(terms, INDEX[e[1], e[2]][0])),
            e[1] != "workcell",
            e[3]["spec"]["name"].lower(),
        ),
    )
    return {
        "size": len(drawn),
        "total": len(shown),
        "domains": dict(sorted(domains.items())),
        "results": [
            {**summary(c, i, a), "mesh": a["mesh"], "url": a["url"]}
            for _, c, i, a in shown[offset : offset + limit]
        ],
    }


# Photo matching: Astra picks from this closed list; the server only ever offers listed keys.
KEYS = [f"{c}:{i}" for c, assets in COLLECTIONS.items() for i in assets]
MATCHES = 3


def listing():
    """One line per library entry, given to Astra alongside the photo."""
    return "\n".join(
        f"{c}:{i} | {a['label']}" for c, assets in COLLECTIONS.items() for i, a in assets.items()
    )


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
