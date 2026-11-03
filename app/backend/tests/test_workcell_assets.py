import hashlib
import json
from pathlib import Path

import pytest
from academy.workcell_assets import ROOT, Registry, registry

PUBLIC = Path(__file__).resolve().parents[2] / "frontend" / "public" / "workcell-assets"


def test_registered_files_match_the_served_bytes():
    reg = registry()
    served = {p.name for p in PUBLIC.iterdir() if p.is_file()}
    files = {a.file for a in reg.assets if a.file}
    assert served == files, "Every served workcell asset must be registered, and only those"
    for asset in reg.assets:
        if asset.file is None:
            continue
        data = (PUBLIC / asset.file).read_bytes()
        assert len(data) == asset.size_bytes, asset.id
        assert hashlib.sha256(data).hexdigest() == asset.sha256, asset.id


def test_procedural_models_point_at_their_source():
    repo = Path(__file__).resolve().parents[3]
    for asset in registry().assets:
        if asset.file is None:
            for source in asset.sources:
                for path in source.paths:
                    assert (repo / path).is_file(), path


def test_cases_reference_registered_assets():
    raw = json.loads(ROOT.read_text())
    raw["cases"][0]["assets"].append("missing-asset")
    with pytest.raises(ValueError, match="unregistered"):
        Registry.model_validate(raw)
    raw = json.loads(ROOT.read_text())
    raw["assets"][0]["sha256"] = None
    with pytest.raises(ValueError, match="digest"):
        Registry.model_validate(raw)


def test_registry_endpoints_need_identity_and_resolve_cases(app, client):
    reg = client.get("/api/workcell/assets").json()
    assert reg["schema_version"] == "academy.workcell-assets/1"
    case = client.get("/api/workcell/cases/synthesis-cell").json()
    assert case["evidence"] == "synthetic"
    assert {a["id"] for a in case["assets"]} == set(registry().cases[0].assets)
    assert client.get("/api/workcell/cases/other").status_code == 404
    from fastapi.testclient import TestClient

    with TestClient(app) as anonymous:
        assert anonymous.get("/api/workcell/assets").status_code == 401
