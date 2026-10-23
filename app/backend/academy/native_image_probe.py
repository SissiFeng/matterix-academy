"""Explicit GPU image scene/render probe; never submits or qualifies a workflow."""

import argparse
import csv
import json
import os
import re
import time
from pathlib import Path


def capacity_report(evidence, status, elapsed_seconds, *, cpu_count=None, mem_total_kib=None):
    """Summarize externally measured resource evidence, including a crashed/timed-out probe."""
    if cpu_count is None:
        cpu_count = os.cpu_count() or 0
    if mem_total_kib is None:
        mem_total_kib = int(
            re.search(r"^MemTotal:\s+(\d+)", Path("/proc/meminfo").read_text(), re.M)[1]
        )
    timing = (evidence / "probe-time.txt").read_text()
    peak = re.search(r"Maximum resident set size \(kbytes\):\s*(\d+)", timing)
    rss = int(peak[1]) if peak else None
    samples = []
    for row in csv.reader((evidence / "gpu-memory.csv").read_text().splitlines()):
        if len(row) != 4:
            continue
        try:
            samples.append({"total_mib": int(row[2].strip()), "used_mib": int(row[3].strip())})
        except ValueError:
            continue
    oom = [
        line
        for line in (evidence / "probe-kernel.log").read_text().splitlines()
        if re.search(r"out of memory|oom-kill|killed process|oom_reaper", line, re.I)
    ]
    journal_status = int((evidence / "kernel-read-status.txt").read_text())
    sampler_complete = (evidence / "gpu-sampler-complete.txt").read_text().strip() == "1"
    result = {
        "schema": "academy.gpu-capacity/1",
        "started_at": (evidence / "probe-started-at.txt").read_text().strip(),
        "probe_exit_code": status,
        "elapsed_seconds": elapsed_seconds,
        "timeout_or_kill": status in {124, 137},
        "logical_cpus": cpu_count,
        "os_visible_mem_total_kib": mem_total_kib,
        "peak_process_rss_kib": rss,
        "gpu_samples": len(samples),
        "gpu_sampler_completed_probe": sampler_complete,
        "peak_gpu_memory_used_mib": max((x["used_mib"] for x in samples), default=None),
        "gpu_memory_total_mib": min((x["total_mib"] for x in samples), default=None),
        "kernel_log_readable": journal_status == 0,
        "kernel_oom_events": oom[:20],
        # EC2 preflight separately enforces physical RAM >=32 GiB; Linux reserves some RAM.
        "capacity_probe_passed": bool(
            status == 0
            and cpu_count >= 8
            and mem_total_kib >= 31 * 1024 * 1024
            and rss
            and samples
            and sampler_complete
            and min(x["total_mib"] for x in samples) >= 22000
            and not oom
            and journal_status == 0
        ),
        "workflow_verified": False,
        "worker_qualified": False,
    }
    (evidence / "capacity.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-native-probe", action="store_true")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.confirm_native_probe:
        parser.error("Explicit native scene/render probe authorization is required")
    started = time.monotonic()
    cfg = json.loads(args.config.read_text())
    os.environ["MATTERIX_ASSETS_DATA_DIR"] = cfg["assets_data_dir"]
    from .native_isaac import activate

    activate(Path(cfg["matterix_root"]))
    from isaaclab.app import AppLauncher

    launch_parser = argparse.ArgumentParser()
    AppLauncher.add_app_launcher_args(launch_parser)
    app = AppLauncher(
        launch_parser.parse_args(
            [
                "--enable_cameras",
                "--device",
                "cuda:0",
                "--viz",
                "kit",
                "--livestream",
                "0",
                "--headless",
            ]
        )
    ).app
    env = None
    try:
        activate(Path(cfg["matterix_root"]))
        import gymnasium as gym
        import matterix_tasks  # noqa: F401
        import numpy as np
        from isaaclab_tasks.utils import parse_env_cfg

        task = "Matterix-Flex-Mixing-v1"
        scene = parse_env_cfg(task, device="cuda:0", num_envs=1)
        scene.configure_workflow(1, 42)
        scene.prepare_for_video_rec(
            fps=15,
            resolution=(960, 540),
            render="balanced",
            eye=(0.42, -1.10, 0.8),
            lookat=(0.0, 0.3, 0.4),
        )
        scene.recorders = None
        scene.viewer.origin_type = "env"
        scene.viewer.env_index = 0
        env = gym.make(task, cfg=scene, render_mode="rgb_array").unwrapped
        env.reset()
        scene_ready_at = time.monotonic()
        frames = 0
        for _ in range(30):
            env.sim.render()
            rgb = env.render()
            if rgb is not None and rgb.shape[:2] == (540, 960) and float(np.mean(rgb)) > 1:
                frames += 1
        if frames < 3:
            raise RuntimeError("Fixed scene did not produce three nonblack native RGB frames")
        rendered_at = time.monotonic()
        env.reset()
        reset_at = time.monotonic()
        result = {
            "scene": task,
            "seed": 42,
            "engine_version": cfg["engine_version"],
            "asset_version": cfg["asset_version"],
            "nonblack_frames": frames,
            "startup_scene_seconds": round(scene_ready_at - started, 3),
            "render_probe_seconds": round(rendered_at - scene_ready_at, 3),
            "reset_seconds": round(reset_at - rendered_at, 3),
            "scene_render_ready": True,
            "workflow_verified": False,
            "worker_qualified": False,
        }
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    finally:
        if env is not None:
            env.close()
        app.close()


if __name__ == "__main__":
    main()
