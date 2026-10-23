"""Correlate browser, cloud and native run artifacts. Does not qualify a worker."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from uuid import UUID

from .commissioning import CommissioningRequest
from .native_studio_runtime import SCENE_VERSION, compile_plan
from .recipes import MixingPlan
from .remote_run import RemoteRunRequest, RemoteRunSnapshot, check_run_snapshot, workflow_digest
from .runtime_inventory import PROFILE, REQUIRED_CHECKS


def acceptance_pair(scope):
    """The acceptance target is a changed saved plan, not a fixed fallback recipe."""
    if scope is None or scope.instrument != "flex":
        return False
    first, second = [approved.experiment for approved in scope.plans]
    for plan, volume in ((first, 100), (second, 50)):
        if plan.diluent_volume != 0 or [(action.kind, action.well) for action in plan.actions] != [
            ("pickup", "stock"),
            ("aspirate", "stock"),
            ("dispense", "A1"),
            ("drop", "stock"),
        ]:
            return False
        if any(action.volume != volume for action in plan.actions[1:3]):
            return False
    return first.source_volume == second.source_volume and any(
        first.layout[name] != second.layout[name] for name in ("stock", "plate", "tips")
    )


def studio_artifact_matches(folder, request, snapshot):
    """Compare saved-plan geometry with the versioned native adapter contract."""
    artifact = json.loads((folder / "studio-plan.json").read_text())
    if not isinstance(artifact, dict):
        return False
    plan, origins, steps = compile_plan(request.experiment)
    native = snapshot.native_state
    # Normalize tuple coordinates to their persisted JSON representation.
    expected_geometry = json.loads(
        json.dumps({"native_origins_m": origins, "steps": [asdict(step) for step in steps]})
    )
    return (
        artifact.get("scene_version") == SCENE_VERSION
        and artifact.get("scene") == f"workflow-studio-{plan.instrument}"
        and artifact.get("instrument") == plan.instrument
        and artifact.get("run_id") == str(request.run_id)
        and artifact.get("native_session_id") == str(snapshot.session_id)
        and artifact.get("plan_hash") == request.plan_hash
        and artifact.get("engine_version") == PROFILE["engine_commit"]
        and artifact.get("asset_version") == PROFILE["asset_commit"]
        and artifact.get("labware_slots") == plan.layout
        and artifact.get("observation_model") == "native-semantic"
        and native is not None
        and native.studio is not None
        and artifact.get("native_action_count") == native.studio.native_action_count
        and artifact.get("native_origins_m") == expected_geometry["native_origins_m"]
        and artifact.get("steps") == expected_geometry["steps"]
    )


def evaluate(runtime, browser, runs_root, *, commissioning_request=None):
    checks = {
        "runtime_inventory": runtime.get("ready_for_commissioning") is True
        and runtime.get("profile") == PROFILE
        and REQUIRED_CHECKS <= runtime.get("checks", {}).keys()
        and all(runtime["checks"][key] is True for key in REQUIRED_CHECKS)
    }
    server = browser.get("server_report", {})
    records = server.get("runs", [])
    approval = None
    if commissioning_request is not None:
        try:
            approval = CommissioningRequest.model_validate(commissioning_request)
        except (ValueError, TypeError):
            pass
        checks["operator_studio_approval"] = bool(
            approval and approval.studio and server.get("grant_id") == str(approval.grant_id)
        )
        checks["changed_studio_acceptance_pair"] = bool(
            approval and acceptance_pair(approval.studio)
        )
    checks["two_browser_runs"] = len(records) == 2 and browser.get("submission_posts") == 2
    checks["browser_refresh_without_resubmit"] = browser.get("refresh_verified") is True
    browser_runs = browser.get("browser_runs", [])
    checks["decoded_relay_video"] = (
        len(browser_runs) == 2
        and all(
            row.get("frames_decoded", 0) > 0 and row.get("relay_verified") is True
            for row in browser_runs
        )
        and {row.get("run_id") for row in browser_runs}
        == {(row.get("run") or {}).get("run_id") for row in records}
    )
    checks["live_harness_completed"] = browser.get("status") == "completed"
    results = []
    seen = set()
    for index, item in enumerate(records):
        run = item.get("run") or {}
        try:
            run_id = str(UUID(run["run_id"]))
            if run_id in seen:
                raise ValueError("Duplicate acceptance run")
            seen.add(run_id)
            folder = runs_root / run_id
            manifest = json.loads((folder / "manifest.json").read_text())
            request = RemoteRunRequest.model_validate(manifest["request"])
            snapshot = RemoteRunSnapshot.model_validate(
                json.loads((folder / "snapshot.json").read_text())
            )
            check_run_snapshot(
                snapshot, UUID(str(manifest["binding"]["native_session_id"])), request
            )
            cloud = RemoteRunSnapshot.model_validate(run["snapshot"])
            frame = json.loads((folder / "frame-proof.json").read_text())
            released = json.loads((folder / "released.json").read_text())
            release_command = json.loads((folder / "release-command.json").read_text())
            proof = item.get("browser") or {}
            studio_scope = approval.studio if approval else None
            expected_plan = studio_scope.plans[index].experiment if studio_scope else MixingPlan()
            plan_matches = (
                request.experiment == expected_plan
                and request.plan_hash == workflow_digest(expected_plan)
            )
            if studio_scope:
                plan_matches = plan_matches and (
                    run.get("scene") == studio_scope.scene
                    and run.get("instrument") == studio_scope.instrument
                    and run.get("plan_hash") == request.plan_hash
                    and studio_artifact_matches(folder, request, snapshot)
                )
            valid = (
                plan_matches
                and str(request.run_id) == run_id
                and snapshot == cloud
                and snapshot.status == "completed"
                and snapshot.engine_version == PROFILE["engine_commit"]
                and snapshot.asset_version == PROFILE["asset_commit"]
                and run.get("commissioning") is True
                and all(step.status == "completed" for step in snapshot.steps)
                and len(snapshot.steps) == len(expected_plan.actions)
                and (run.get("cleanup") or {}).get("reset_verified") is True
                and released.get("reset_verified") is True
                and set(released.get("checks", {}))
                == {"objects", "liquids", "tips", "controllers", "stopped"}
                and all(v is True for v in released["checks"].values())
                and released["command_id"] == run["cleanup"]["command_id"]
                and released["native_session_id"] == str(snapshot.session_id)
                and release_command["native_session_id"] == str(snapshot.session_id)
                and frame.get("run_id") == proof.get("run_id") == run_id
                and frame.get("native_session_id")
                == proof.get("native_session_id")
                == str(snapshot.session_id)
                and frame.get("plan_hash") == proof.get("plan_hash") == request.plan_hash
                and frame.get("source") == "native-renderer"
                and proof.get("source") == "browser-report"
                and frame.get("nonblack_frames", 0) >= 3
                and frame.get("simulation_tick", 0) > 0
                and proof.get("frames_decoded", 0) > 0
            )
            results.append({"run_id": run_id, "artifacts_match": valid})
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            results.append(
                {"run_id": run.get("run_id"), "artifacts_match": False, "error": type(exc).__name__}
            )
    checks["bound_native_and_browser_artifacts"] = len(results) == 2 and all(
        r["artifacts_match"] for r in results
    )
    return {
        "browser_native_path_passed": all(checks.values()),
        "checks": checks,
        "runs": results,
        "worker_qualified": False,
        "scope": "Artifact consistency only. Studio volumes are native-semantic accounting, not fluid, chemical or hardware validation. Operator must review provenance, isolation, interruption/recovery and image identity before qualification.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-report", type=Path, required=True)
    parser.add_argument("--browser-report", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument(
        "--commissioning-request",
        type=Path,
        help="Operator-approved request JSON; required for Studio's exact two-plan acceptance",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(
        json.loads(args.runtime_report.read_text()),
        json.loads(args.browser_report.read_text()),
        args.runs_root,
        commissioning_request=json.loads(args.commissioning_request.read_text())
        if args.commissioning_request
        else None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print("Artifact checks complete; worker qualification was not changed.")
    raise SystemExit(0 if result["browser_native_path_passed"] else 2)


if __name__ == "__main__":
    main()
