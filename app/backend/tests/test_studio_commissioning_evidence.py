"""Fabricated artifacts exercise correlation only; never live native acceptance."""

import json
from copy import deepcopy
from dataclasses import asdict
from uuid import uuid4

import pytest
from academy.commissioning import CommissioningRequest
from academy.commissioning_evidence import acceptance_pair, evaluate
from academy.native_studio_runtime import SCENE_VERSION, compile_plan
from academy.remote_run import RemoteRunRequest, workflow_digest
from academy.runtime_inventory import PROFILE, REQUIRED_CHECKS
from test_studio_commissioning import approved_request, completed_snapshot


def artifacts(tmp_path):
    approval = approved_request()
    runs = []
    for approved in approval.studio.plans:
        native = uuid4()
        request = RemoteRunRequest(
            run_id=uuid4(),
            expected_revision=1,
            experiment=approved.experiment,
            plan_hash=approved.plan_hash,
        )
        snapshot = completed_snapshot(native, request)
        plan, origins, steps = compile_plan(approved.experiment)
        run_id = str(request.run_id)
        folder = tmp_path / run_id
        folder.mkdir()
        command = str(uuid4())
        payloads = {
            "manifest.json": {
                "request": request.model_dump(mode="json"),
                "binding": {"native_session_id": str(native)},
            },
            "snapshot.json": snapshot,
            "studio-plan.json": {
                "scene_version": SCENE_VERSION,
                "scene": approval.studio.scene,
                "instrument": "flex",
                "run_id": run_id,
                "native_session_id": str(native),
                "plan_hash": request.plan_hash,
                "engine_version": PROFILE["engine_commit"],
                "asset_version": PROFILE["asset_commit"],
                "labware_slots": plan.layout,
                "native_origins_m": origins,
                "steps": [asdict(step) for step in steps],
                "observation_model": "native-semantic",
                "native_action_count": 20,
            },
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
                "checks": dict.fromkeys(
                    ("objects", "liquids", "tips", "controllers", "stopped"), True
                ),
            },
            "release-command.json": {"native_session_id": str(native)},
        }
        for name, value in payloads.items():
            (folder / name).write_text(json.dumps(value))
        runs.append(
            {
                "run": {
                    "run_id": run_id,
                    "scene": approval.studio.scene,
                    "instrument": "flex",
                    "plan_hash": request.plan_hash,
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
    return (
        {
            "ready_for_commissioning": True,
            "profile": PROFILE,
            "checks": dict.fromkeys(REQUIRED_CHECKS, True),
        },
        {
            "status": "completed",
            "submission_posts": 2,
            "refresh_verified": True,
            "browser_runs": [
                {"run_id": row["run"]["run_id"], "frames_decoded": 50, "relay_verified": True}
                for row in runs
            ],
            "server_report": {"grant_id": str(approval.grant_id), "runs": runs},
        },
        approval.model_dump(mode="json"),
    )


def test_studio_artifacts_bind_approved_changed_plan_render_reset_and_browser(tmp_path):
    runtime, browser, approval = artifacts(tmp_path)
    result = evaluate(runtime, browser, tmp_path, commissioning_request=approval)
    assert result["browser_native_path_passed"]
    assert result["worker_qualified"] is False
    assert "native-semantic" in result["scope"]
    assert "not fluid, chemical or hardware validation" in result["scope"]
    # Studio artifacts alone cannot confer operator authority.
    assert not evaluate(runtime, browser, tmp_path)["browser_native_path_passed"]


@pytest.mark.parametrize("artifact", [None, [], ["unexpected"], "unexpected", 0, 1.5, True])
def test_non_object_studio_artifact_fails_without_aborting_other_run(tmp_path, artifact):
    runtime, browser, approval = artifacts(tmp_path)
    run_id = browser["server_report"]["runs"][0]["run"]["run_id"]
    (tmp_path / run_id / "studio-plan.json").write_text(json.dumps(artifact))

    result = evaluate(runtime, browser, tmp_path, commissioning_request=approval)

    assert result["browser_native_path_passed"] is False
    assert result["worker_qualified"] is False
    assert [run["artifacts_match"] for run in result["runs"]] == [False, True]


@pytest.mark.parametrize(
    "case",
    [
        "approval_grant",
        "approval_hash",
        "approval_missing",
        "wrong_order",
        "run_scene",
        "run_hash",
        "no_studio_plan",
        "geometry",
        "action_volume",
        "asset_pin",
        "scene_version",
        "native_layout",
        "native_semantics",
        "native_waste",
        "native_final_volume",
        "no_render",
        "no_relay",
        "no_refresh",
        "resubmit",
        "no_reset",
        "duplicate",
        "missing_run",
    ],
)
def test_studio_evidence_rejects_missing_conflicting_or_replayed_artifacts(tmp_path, case):
    runtime, browser, approval = artifacts(tmp_path)
    first = browser["server_report"]["runs"][0]
    folder = tmp_path / first["run"]["run_id"]
    if case == "approval_grant":
        approval["grant_id"] = str(uuid4())
    elif case == "approval_hash":
        approval["studio"]["plans"][0]["plan_hash"] = "f" * 64
    elif case == "approval_missing":
        approval = None
    elif case == "wrong_order":
        browser["server_report"]["runs"].reverse()
    elif case == "run_scene":
        first["run"]["scene"] = "workflow-studio-ot2"
    elif case == "run_hash":
        first["run"]["plan_hash"] = "f" * 64
    elif case == "no_studio_plan":
        (folder / "studio-plan.json").unlink()
    elif case in {"geometry", "action_volume", "asset_pin", "scene_version"}:
        artifact = json.loads((folder / "studio-plan.json").read_text())
        if case == "geometry":
            artifact["native_origins_m"]["stock"][0] += 0.1
        elif case == "action_volume":
            artifact["steps"][1]["volume"] = 10
        elif case == "asset_pin":
            artifact["asset_version"] = "a" * 40
        else:
            artifact["scene_version"] = "unreviewed"
        (folder / "studio-plan.json").write_text(json.dumps(artifact))
    elif case.startswith("native_"):
        snapshot = first["run"]["snapshot"]
        state = snapshot["native_state"]
        if case == "native_layout":
            state["studio"]["labware_slots"]["tips"] = "C1"
        elif case == "native_semantics":
            state["studio"]["observation_model"] = "fluid-validated"
        elif case == "native_waste":
            state["studio"]["waste_volume_ul"] = 10
        else:
            state["well_volumes_ul"]["A1"] = 10
            state["well_volumes_ul"]["stock"] += 90
        (folder / "snapshot.json").write_text(json.dumps(snapshot))
    elif case == "no_render":
        artifact = json.loads((folder / "frame-proof.json").read_text())
        artifact["nonblack_frames"] = 0
        (folder / "frame-proof.json").write_text(json.dumps(artifact))
    elif case == "no_relay":
        browser["browser_runs"][0]["relay_verified"] = False
    elif case == "no_refresh":
        browser["refresh_verified"] = False
    elif case == "resubmit":
        browser["submission_posts"] = 3
    elif case == "no_reset":
        first["run"]["cleanup"]["reset_verified"] = False
    elif case == "duplicate":
        browser["server_report"]["runs"][1] = deepcopy(first)
    else:
        del first["run"]
    assert not evaluate(runtime, browser, tmp_path, commissioning_request=approval)[
        "browser_native_path_passed"
    ]


@pytest.mark.parametrize(
    "case",
    ["same_layout", "same_volume", "different_source", "different_destination", "extra_action"],
)
def test_two_safe_approved_plans_do_not_automatically_satisfy_acceptance_target(case):
    approval = approved_request().model_dump(mode="json")
    first, second = [item["experiment"] for item in approval["studio"]["plans"]]
    if case == "same_layout":
        second["layout"] = first["layout"]
    elif case == "same_volume":
        second["actions"][1]["volume"] = second["actions"][2]["volume"] = 100
    elif case == "different_source":
        second["source_volume"] = 1100
    elif case == "different_destination":
        second["actions"][2]["well"] = "A2"
    else:
        second["actions"].append({"kind": "pickup", "well": "stock", "volume": 100})
    for entry in approval["studio"]["plans"]:
        from academy.models import Experiment

        entry["plan_hash"] = workflow_digest(Experiment.model_validate(entry["experiment"]))
    validated = CommissioningRequest.model_validate(approval)
    assert not acceptance_pair(validated.studio)
