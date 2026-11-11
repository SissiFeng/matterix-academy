import importlib.util
from pathlib import Path

import pytest
from academy.chemlab import CHEMLAB, MODELS
from academy.library import browse, search

SCRIPT = Path(__file__).parents[3] / "scripts/library-models/chemlab_models.py"


def top(query, n=1):
    return [r["id"] for r in search(query)["results"][:n]]


@pytest.mark.parametrize(
    ("query", "first"),
    [
        # Two letters are a word of their own, not a fragment of spectrophotometer.
        ("pH", "metrohm_914"),
        ("ph meter", "metrohm_914"),
        # Lab shorthand stands for the catalogue's wording.
        ("rotavap", "ika_rv10_digital_v"),
        ("lyophilizer", "buchi_lyovapor_l250_pro"),
        ("FTIR", "jasco_ftir4700"),
        ("ft-ir", "jasco_ftir4700"),
        ("SEM", "jeol_jsmit200"),
        ("glove box", "inert_purelab_he_2gb"),
        ("hot plate", "ika_plate_rctdigital"),
        # Model numbers, typed apart, together or in part.
        ("XPR 204", "mt_xpr204e"),
        ("rv10", "ika_rv10_digital_v"),
        ("5910", "eppendorf_5910ri"),
        # Maker and kind together.
        ("anton paar rheometer", "antonpaar_mcr503"),
        ("mettler toledo balance", "mt_xpr204e"),
    ],
)
def test_a_query_finds_the_instrument_it_names(query, first):
    assert first in CHEMLAB, f"{first} is not a catalogue slug"
    assert top(query) == [first]


def test_plurals_and_fragments_still_find_the_kind():
    assert search("balances")["total"] == search("balance")["total"] >= 4
    assert search("centrifuges")["results"][0]["id"] == "eppendorf_5910ri"
    assert {r["id"] for r in search("xrd")["results"]} == {
        "rigaku_miniflex600_external_cooling",
        "rigaku_xtalabsynergy",
    }
    assert search("spectro")["total"] > 20  # the start of a word still narrows a list


def test_a_whole_word_outranks_a_fragment_of_another():
    # "scale" means a balance; "full scale" in a flow controller's model comes after.
    found = [r["name"] for r in search("scale")["results"]]
    assert "balance" in found[0].lower() and any("mass-flow" in name for name in found[1:])


def test_pipetting_finds_both_liquid_handlers():
    assert set(top("pipette", 2)) == {"opentrons_flex_single_5_1000ul", "opentrons-ot2"}


def test_the_models_page_ranks_a_query_and_lists_all_without_one():
    everything = browse()
    assert everything["total"] == everything["size"] >= 200
    assert [r["id"] for r in browse("rotavap")["results"]] == ["ika_rv10_digital_v"]
    assert browse("no such instrument")["total"] == 0


def test_models_that_stand_on_y_say_so():
    turned = {slug for slug, model in MODELS["models"].items() if model.get("up") == "y"}
    assert len(turned) == 14 and "eppendorf_5910ri" in turned
    assert CHEMLAB["eppendorf_5910ri"]["mesh"]["up"] == "y"
    assert CHEMLAB["mt_xpr204e"]["mesh"]["up"] == "z"


def test_the_manifest_script_reads_which_way_up_a_model_stands():
    spec = importlib.util.spec_from_file_location("chemlab_models", SCRIPT)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    # A 0.2 × 0.3 × 0.5 box under a node that doubles it and a root that moves it.
    doc = {
        "scenes": [{"nodes": [0]}],
        "nodes": [
            {"translation": [1, 2, 3], "children": [1]},
            {"scale": [2, 2, 2], "mesh": 0},
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "accessors": [{"min": [-0.05, 0, -0.075], "max": [0.05, 0.25, 0.075]}],
    }
    assert script.extent(doc) == pytest.approx([0.2, 0.5, 0.3])
    assert script.up_axis(doc, [0.2, 0.3, 0.5]) == "y"  # catalogue sizes are Z-up
    assert script.up_axis(doc, [0.2, 0.5, 0.3]) == "z"
