"""Explicit GPU image scene/render probe; never submits or qualifies a workflow."""

import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-native-probe", action="store_true")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.confirm_native_probe:
        parser.error("Explicit native scene/render probe authorization is required")
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
        frames = 0
        for _ in range(30):
            env.sim.render()
            rgb = env.render()
            if rgb is not None and rgb.shape[:2] == (540, 960) and float(np.mean(rgb)) > 1:
                frames += 1
        if frames < 3:
            raise RuntimeError("Fixed scene did not produce three nonblack native RGB frames")
        env.reset()
        result = {
            "scene": task,
            "seed": 42,
            "engine_version": cfg["engine_version"],
            "asset_version": cfg["asset_version"],
            "nonblack_frames": frames,
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
