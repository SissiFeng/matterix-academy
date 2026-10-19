"""Correlate browser, cloud and native run artifacts. Does not qualify a worker."""

import argparse
import json
from pathlib import Path
from uuid import UUID

from .recipes import MixingPlan
from .remote_run import RemoteRunRequest, RemoteRunSnapshot, check_run_snapshot, workflow_digest
from .runtime_inventory import PROFILE, REQUIRED_CHECKS


def evaluate(runtime, browser, runs_root):
    checks = {
        "runtime_inventory": runtime.get("ready_for_commissioning") is True
        and runtime.get("profile") == PROFILE
        and REQUIRED_CHECKS <= runtime.get("checks", {}).keys()
        and all(runtime["checks"][key] is True for key in REQUIRED_CHECKS)
    }
    records = browser.get("server_report", {}).get("runs", [])
    checks["two_browser_runs"] = len(records) == 2 and browser.get("submission_posts") == 2
    checks["browser_refresh_without_resubmit"] = browser.get("refresh_verified") is True
    browser_runs = browser.get("browser_runs", [])
    checks["decoded_relay_video"] = (
        len(browser_runs) == 2
        and all(
            row.get("frames_decoded", 0) > 0 and row.get("relay_verified") is True
            for row in browser_runs
        )
        and {row.get("run_id") for row in browser_runs} == {row["run"]["run_id"] for row in records}
    )
    checks["live_harness_completed"] = browser.get("status") == "completed"
    results = []
    seen = set()
    for item in records:
        run = item["run"]
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
            check_run_snapshot(snapshot, snapshot.session_id, request)
            cloud = RemoteRunSnapshot.model_validate(run["snapshot"])
            frame = json.loads((folder / "frame-proof.json").read_text())
            released = json.loads((folder / "released.json").read_text())
            release_command = json.loads((folder / "release-command.json").read_text())
            proof = item.get("browser") or {}
            valid = (
                request.experiment == MixingPlan()
                and str(request.run_id) == run_id
                and request.plan_hash == workflow_digest(MixingPlan())
                and snapshot == cloud
                and snapshot.status == "completed"
                and snapshot.engine_version == PROFILE["engine_commit"]
                and snapshot.asset_version == PROFILE["asset_commit"]
                and run.get("commissioning") is True
                and all(step.status == "completed" for step in snapshot.steps)
                and len(snapshot.steps) == 5
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
        except (OSError, ValueError, KeyError, TypeError) as exc:
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
        "scope": "Artifact consistency only; operator must review provenance, isolation, interruption/recovery and image identity before qualification.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-report", type=Path, required=True)
    parser.add_argument("--browser-report", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(
        json.loads(args.runtime_report.read_text()),
        json.loads(args.browser_report.read_text()),
        args.runs_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print("Artifact checks complete; worker qualification was not changed.")
    raise SystemExit(0 if result["browser_native_path_passed"] else 2)


if __name__ == "__main__":
    main()
