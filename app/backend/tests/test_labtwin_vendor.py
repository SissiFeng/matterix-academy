import hashlib
from pathlib import Path

import labtwin
from labtwin import workflows

VENDORED = Path(__file__).resolve().parents[1] / "labtwin"


def test_vendored_contracts_match_their_pinned_digest():
    h = hashlib.sha256()
    for file in sorted(VENDORED.glob("*.py")):
        h.update(file.name.encode() + b"\0" + file.read_bytes() + b"\0")
    assert (VENDORED / "CONTRACT.sha256").read_text().strip() == h.hexdigest(), (
        "Vendored labtwin was edited; change the canonical package and run scripts/sync-labtwin.py"
    )


def test_contract_version_and_registered_models():
    assert labtwin.CONTRACT_VERSION == "1.0.0"
    assert set(workflows.MODELS) == {"opentrons_flex", "opentrons_ot2"}
