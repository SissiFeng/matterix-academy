"""Offline artifact checks only; never EC2, Isaac or native acceptance."""

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest
from academy.native_runner import NativeConfig
from academy.worker_admin import qualification_changes

ROOT = Path(__file__).resolve().parents[3]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = load_script("ec2-gpu-prepare")
costs = load_script("ec2-gpu-costs")


def pinned_fixture():
    manifest = json.loads((ROOT / "ops/ec2-gpu/image-manifest.example.json").read_text())
    manifest["academy_commit"] = "a" * 40
    manifest["sources_manifest_sha256"] = "b" * 64
    manifest["driver_version"] = prepare.PROFILE["driver_version"]
    return manifest


def test_unresolved_image_template_cannot_generate_runnable_config():
    template = json.loads((ROOT / "ops/ec2-gpu/image-manifest.example.json").read_text())
    with pytest.raises(ValueError, match="exact reviewed"):
        prepare.native_config(template)


def test_renderer_matches_existing_native_runner_contract_without_importing_isaac():
    config = NativeConfig.model_validate(prepare.native_config(pinned_fixture()))
    assert config.headless and config.display == ""
    assert config.engine_version == prepare.PROFILE["engine_commit"]
    assert config.run_root == "/var/lib/academy-native/runs"
    assert config.frame_root == "/run/academy-native/frames"


@pytest.mark.parametrize(
    "patch",
    [
        {"schema_version": True},
        {"status": "qualified"},
        {"simulation_only": False},
        {"controls": ["cancel"]},
        {"engine_commit": "latest"},
        {"asset_commit": "HEAD"},
        {"driver_version": "latest"},
        {"worker_id": "../other"},
        {"isaacsim_version": "5.0.0"},
        {"python_version": "3.11"},
        {"ubuntu_version": "20.04"},
        {"ubuntu_version": "22.04"},
        {"sources_manifest_sha256": ""},
        {"command": "arbitrary execution"},
    ],
)
def test_unqualified_manifest_enforces_reviewed_pins_and_fixed_scope(patch):
    fixture = {**pinned_fixture(), **patch}
    with pytest.raises(ValueError):
        prepare.native_config(fixture)


def test_cost_model_includes_stopped_storage_and_running_ipv4():
    result = costs.estimate("1.4692", "0.088", 40)
    assert result == {
        "running_hours": 40,
        "compute_usd": "58.77",
        "ipv4_usd": "0.20",
        "retained_ebs_month_usd": "26.40",
        "subtotal_usd": "85.37",
    }
    assert costs.estimate("1.4692", "0.088", 0)["subtotal_usd"] == "26.40"


def test_public_price_capture_handles_absent_candidates_and_never_needs_account(monkeypatch):
    def fake_fetch(url):
        if url.endswith("/ebs.json"):
            return {
                "manifest": {"source": "fixture"},
                "regions": {
                    location: {"Storage General Purpose gp3 GB Mo": {"price": "0.088"}}
                    for location in costs.LOCATIONS.values()
                },
            }, "fixture-hash"
        location = "Canada (Central)" if "Canada" in url else "US East (N. Virginia)"
        return {
            "manifest": {"source": "fixture"},
            "regions": {
                location: [
                    {
                        "Instance Type": "g6.4xlarge",
                        "Location": location,
                        "Operating System": "Linux",
                        "Pre Installed S/W": "NA",
                        "price": "1.4692",
                    }
                ]
            },
        }, "fixture-hash"

    monkeypatch.setattr(costs, "fetch", fake_fetch)
    result = costs.capture()
    assert len(result["candidates"]) == 6
    missing = [row for row in result["candidates"] if not row["listed"]]
    assert len(missing) == 4
    assert all(row["price_record"] is None and row["estimates"] == [] for row in missing)
    assert "no account" in result["scope"].lower()


def test_captured_price_evidence_is_reproducible_and_not_capacity_evidence():
    path = ROOT / "docs/evidence/ec2-gpu/prices-2026-10-19.json"
    captured = json.loads(path.read_text())
    for candidate in captured["candidates"]:
        if candidate["listed"]:
            expected = [
                costs.estimate(
                    candidate["price_record"]["price"], candidate["gp3_record"]["price"], hours
                )
                for hours in (8, 40, 730)
            ]
            assert candidate["estimates"] == expected
    assert all(
        source["url"].startswith("https://b0.p.awsstatic.com/") for source in captured["sources"]
    )
    assert "capacity" in captured["scope"]


def test_manifest_validation_does_not_mutate_its_source():
    fixture = pinned_fixture()
    before = deepcopy(fixture)
    prepare.native_config(fixture)
    assert fixture == before


def test_pending_acceptance_template_cannot_qualify_a_worker():
    pending = json.loads((ROOT / "ops/ec2-gpu/acceptance-record.example.json").read_text())
    with pytest.raises(ValueError, match="native acceptance checks"):
        qualification_changes({}, pending)
