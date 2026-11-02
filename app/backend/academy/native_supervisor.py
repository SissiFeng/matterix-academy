"""Own exactly two child processes; never discover or kill unrelated runtimes."""

import argparse
import fcntl
import os
import subprocess
import sys
import time
from pathlib import Path

from .gpu_health import gpu_issue
from .native_files import SCENE_STARTED, alive_lease, read_json, write_json


class LaunchBlocked(RuntimeError):
    """Raised before any simulator child exists."""


def runtime_module(request):
    """Select from a fixed module catalog; learner data never supplies code paths."""
    from .remote_run import RemoteRunRequest

    plan = RemoteRunRequest.model_validate(request).experiment
    if plan.course_id == "flex-mixing":
        return "native_isaac"
    if plan.course_id == "workflow-sandbox":
        from .native_studio_runtime import compile_plan

        compile_plan(plan)
        return "native_studio_isaac"
    raise ValueError("This installed native process has no adapter for the saved course")


def supervise(folder):
    manifest = read_json(folder / "manifest.json")
    cfg = manifest["config"]
    binding = manifest["binding"]
    native_module = runtime_module(manifest["request"])
    children = []
    logs = []
    frame_path = Path(cfg["frame_root"]) / (binding["native_session_id"] + ".rgb")
    launch_failure = None
    try:
        if not alive_lease(folder):
            raise RuntimeError("Native lease expired before process launch")
        issue = gpu_issue(cfg.get("driver_version"))
        if issue:
            raise LaunchBlocked(issue)
        Path(cfg["frame_root"]).mkdir(parents=True, exist_ok=True, mode=0o700)
        backend = str(Path(__file__).resolve().parents[1])
        env = {
            k: v
            for k, v in os.environ.items()
            if k
            not in {
                "PYTHONPATH",
                "PYTHONHOME",
                "ISAACLAB_PATH",
                "ISAACSIM_PATH",
                "ISAAC_PATH",
                "HEADLESS",
                "LIVESTREAM",
            }
        }
        env.update(
            PYTHONPATH=backend,
            PYTORCH_JIT="0",
            MATTERIX_ASSETS_DATA_DIR=cfg["assets_data_dir"],
            DISPLAY=cfg["display"],
        )
        for name, python in (("native_media", sys.executable), (native_module, cfg["python"])):
            log = open(folder / (name + ".log"), "ab", buffering=0)
            logs.append(log)
            children.append(
                subprocess.Popen(
                    [python, "-m", "academy." + name, "--folder", str(folder)],
                    cwd=cfg["matterix_root"],
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            )
        while children[1].poll() is None:
            if not alive_lease(folder) or children[0].poll() is not None:
                raise RuntimeError("Lease or live media process ended; simulator must stop")
            time.sleep(0.25)
        if children[1].returncode != 0 or not (folder / "reset-proof.json").exists():
            raise RuntimeError("Isaac exited without verified cleanup")
        # The media child observes this sentinel and closes every peer/socket.
        write_json(folder / "stop-media.json", {"native_session_id": binding["native_session_id"]})
        children[0].wait(timeout=10)
        if children[0].returncode != 0:
            raise RuntimeError("Media process did not close normally")
        proof = read_json(folder / "reset-proof.json")
        proof["checks"]["stopped"] = True
        proof["reset_verified"] = all(proof["checks"].values())
        write_json(folder / "released.json", proof)
    except Exception as exc:
        if (folder / SCENE_STARTED).exists():
            write_json(
                folder / "fault.json",
                {
                    "native_session_id": binding["native_session_id"],
                    "message": "Native execution or cleanup needs operator inspection",
                },
            )
        else:
            # Isaac writes the marker before building any scene. Without it the
            # simulator never held run state; report only once children are gone.
            launch_failure = {
                "native_session_id": binding["native_session_id"],
                "stage": "preflight" if isinstance(exc, LaunchBlocked) else "launch",
                "reason": str(exc)[:300] or type(exc).__name__,
                "simulator_exit": children[1].poll() if len(children) > 1 else None,
            }
        raise
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
        for log in logs:
            log.close()
        frame_path.unlink(missing_ok=True)
        if launch_failure is not None:
            if any(child.poll() is None for child in children) or (folder / SCENE_STARTED).exists():
                write_json(
                    folder / "fault.json",
                    {
                        "native_session_id": binding["native_session_id"],
                        "message": "Native launch did not stop cleanly; operator inspection needed",
                    },
                )
            else:
                write_json(folder / "launch-failed.json", launch_failure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", required=True)
    args = parser.parse_args()
    folder = Path(args.folder)
    with open(folder / "runtime.lock", "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # A second supervisor cannot launch after the first has ended either.
        fd = os.open(folder / "supervisor-started", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        supervise(folder)


if __name__ == "__main__":
    main()
