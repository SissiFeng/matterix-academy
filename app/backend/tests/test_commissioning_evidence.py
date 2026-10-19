"""Deliberately synthetic artifact fixtures; cannot establish live GPU acceptance."""

import json
from copy import deepcopy
from uuid import uuid4

import pytest
from academy.commissioning_evidence import evaluate
from academy.runtime_inventory import PROFILE, REQUIRED_CHECKS
from test_mixing import mixing_report


def artifacts(tmp_path):
    runs = []
    for _ in range(2):
        native, request, snapshot = mixing_report()
        snapshot.update(
            engine_version=PROFILE["engine_commit"], asset_version=PROFILE["asset_commit"]
        )
        run_id = str(request.run_id)
        folder = tmp_path / run_id
        folder.mkdir()
        command = str(uuid4())
        payloads = {
            "manifest.json": {"request": request.model_dump(mode="json")},
            "snapshot.json": snapshot,
            "frame-proof.json": {
                "run_id": run_id,
                "native_session_id": str(native),
                "plan_hash": request.plan_hash,
                "source": "native-renderer",
                "nonblack_frames": 20,
                "simulation_tick": 100,
                "rgb_sha256": "f" * 64,
            },
            "released.json": {
                "native_session_id": str(native),
                "command_id": command,
                "reset_verified": True,
                "checks": {
                    k: True for k in ("objects", "liquids", "tips", "controllers", "stopped")
                },
            },
            "release-command.json": {"native_session_id": str(native)},
        }
        for name, value in payloads.items():
            (folder / name).write_text(json.dumps(value))
        runs.append(
            {
                "run": {
                    "run_id": run_id,
                    "snapshot": snapshot,
                    "commissioning": True,
                    "cleanup": {"command_id": command, "reset_verified": True},
                },
                "browser": {
                    "run_id": run_id,
                    "native_session_id": str(native),
                    "plan_hash": request.plan_hash,
                    "source": "browser-report",
                    "frames_decoded": 50,
                },
            }
        )
    return {
        "ready_for_commissioning": True,
        "profile": PROFILE,
        "checks": {key: True for key in REQUIRED_CHECKS},
    }, {
        "status": "completed",
        "browser_runs": [
            {"run_id": r["run"]["run_id"], "frames_decoded": 50, "relay_verified": True}
            for r in runs
        ],
        "submission_posts": 2,
        "refresh_verified": True,
        "server_report": {"runs": runs},
    }


def test_matching_synthetic_fixtures_only_produce_consistency_review_not_qualification(tmp_path):
    runtime, browser = artifacts(tmp_path)
    report = evaluate(runtime, browser, tmp_path)
    assert report["browser_native_path_passed"]
    assert report["worker_qualified"] is False


@pytest.mark.parametrize(
    "case",
    [
        "no_runtime",
        "no_video",
        "wrong_run",
        "missing_reset",
        "no_refresh",
        "replayed",
        "wrong_versions",
        "one_run",
        "duplicate",
    ],
)
def test_missing_or_conflicting_browser_native_evidence_fails_closed(tmp_path, case):
    runtime, browser = artifacts(tmp_path)
    first = browser["server_report"]["runs"][0]
    folder = tmp_path / first["run"]["run_id"]
    if case == "no_runtime":
        runtime["ready_for_commissioning"] = False
    elif case == "no_video":
        first["browser"]["frames_decoded"] = 0
    elif case == "wrong_run":
        first["browser"]["native_session_id"] = str(uuid4())
    elif case == "missing_reset":
        (folder / "released.json").unlink()
    elif case == "no_refresh":
        browser["refresh_verified"] = False
    elif case == "replayed":
        browser["submission_posts"] = 3
    elif case == "wrong_versions":
        first["run"]["snapshot"]["engine_version"] = "other"
    elif case == "one_run":
        browser["server_report"]["runs"].pop()
    else:
        browser["server_report"]["runs"][1] = deepcopy(first)
    assert not evaluate(runtime, browser, tmp_path)["browser_native_path_passed"]
