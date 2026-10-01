"""One bounded Flex workflow in the independent, prepared Matterix environment.

All observations are read from native semantics/articulations. This adapter does
not implement a replacement liquid model or issue physical hardware commands.
"""

import argparse
import importlib
import importlib.util
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from .native_files import FrameBuffer, alive_lease, read_json, write_json


def activate(root):
    for name in ("matterix", "matterix_assets", "matterix_sm", "matterix_tasks"):
        expected = root / "source" / name
        sys.path.insert(0, str(expected))
    os.environ["MATTERIX_PATH"] = str(root)
    importlib.invalidate_caches()
    for name in ("matterix", "matterix_assets", "matterix_sm", "matterix_tasks"):
        spec = importlib.util.find_spec(name)
        if (
            not spec
            or not spec.origin
            or not Path(spec.origin).resolve().is_relative_to(root / "source" / name)
        ):
            raise RuntimeError("Native package resolution differs from the pinned checkout")


def tensor(value):
    return value.torch if hasattr(value, "torch") else value


def run(folder):
    manifest = read_json(folder / "manifest.json")
    config, binding, request = manifest["config"], manifest["binding"], manifest["request"]
    plan = request["experiment"]
    root = Path(config["matterix_root"]).resolve()
    activate(root)
    from isaaclab.app import AppLauncher

    parser = argparse.ArgumentParser()
    AppLauncher.add_app_launcher_args(parser)
    flags = ["--enable_cameras", "--device", "cuda:0", "--viz", "kit", "--livestream", "0"]
    if config["headless"]:
        flags += ["--headless"]
    app = AppLauncher(parser.parse_args(flags)).app
    activate(root)
    import builtins

    import gymnasium as gym
    import matterix_tasks  # noqa: F401
    import numpy as np
    import torch
    from isaaclab_tasks.utils import parse_env_cfg
    from matterix_sm import StateMachine

    cfg = parse_env_cfg(plan["task"], device="cuda:0", num_envs=1)
    cfg.configure_workflow(1, plan["seed"])
    expected_order = [item["source_index"] for item in plan["actions"][1:]]
    if cfg.source_order != [expected_order]:
        raise RuntimeError("Native recipe source selection does not match the saved plan")
    cfg.prepare_for_video_rec(
        fps=15,
        resolution=(960, 540),
        render="balanced",
        eye=(0.42, -1.10, 0.8),
        lookat=(0.0, 0.3, 0.4),
    )
    cfg.recorders = None
    cfg.viewer.origin_type = "env"
    cfg.viewer.env_index = 0
    # No implicit episode restart can be reached inside the bounded workflow.
    cfg.episode_length_s = 1800
    env = gym.make(plan["task"], cfg=cfg, render_mode="rgb_array").unwrapped
    if getattr(builtins, "ISAACLAB_CALLBACK_EXCEPTION", None):
        raise RuntimeError("Isaac asset initialization failed")
    observations, _ = env.reset()
    sm = StateMachine(num_envs=1, dt=env.step_dt, device=env.device)
    sequence = cfg.workflows[plan["workflow"]]
    sm.set_action_sequence(sequence)
    sm.reset()
    # Pin this adapter to the reviewed 10 + 4*19 native action structure.
    if len(sm.actions) != 86:
        raise RuntimeError("Native action layout changed; requalify the mixing adapter")
    deck = env.semantic_manager.full_semantic_states["flex/FlexMixingState"]
    tip = env.semantic_manager.full_semantic_predicates["flex/FlexIsTipAttached"]
    command = env.semantic_manager.full_semantic_predicates["flex/FlexMixingCommand"]
    robot = env.scene["flex"]
    baseline_joints = tensor(robot.data.joint_pos).clone()
    baseline_tips = {
        name: tensor(env.scene[name].data.body_link_pose_w).clone()
        for name in ("tips_50", "tips_1000")
    }
    baseline_lid = tensor(env.scene["vial_lid"].data.root_pos_w).clone()
    frame = FrameBuffer(
        Path(config["frame_root"]) / (binding["native_session_id"] + ".rgb"), create=True
    )
    tick = 0
    revision = 1
    last_render = 0.0
    last_report = 0.0
    last_action = -1
    pickups, drops = [], []
    active_tip = None
    confirmations = {}
    final_snapshot = None

    def capture():
        nonlocal last_render
        if time.monotonic() - last_render < 1 / 15:
            return False
        env.sim.render()
        rgb = env.render()
        last_render = time.monotonic()
        if rgb is None or rgb.shape[:2] != (540, 960) or float(np.mean(rgb)) <= 1:
            return False
        frame.write(np.asarray(rgb[..., :3], dtype=np.uint8).tobytes(), tick)
        return True

    def observe(status, error=None):
        nonlocal revision, active_tip, final_snapshot
        attached = bool(tip.is_attached[0])
        child = tip.tip_child_ids[0] if attached else None
        if child != active_tip:
            if active_tip is not None and child is not None:
                raise RuntimeError("A tip changed without observed disposal")
            if active_tip is not None:
                drops.append(active_tip)
            if child is not None:
                pickups.append(child)
            active_tip = child
        total = deck.sources + deck.tip + deck.well
        if not torch.allclose(total, torch.full_like(total, 1500), atol=0.01):
            raise RuntimeError("Native reagent mass balance failed")
        revision += 1
        now = datetime.now(UTC).isoformat()
        action_index = int(sm.current_action_idx[0])
        completed = sum(action_index >= boundary for boundary in (10, 29, 48, 67, 86))
        for index in range(completed):
            confirmations.setdefault(
                index,
                {
                    "index": index,
                    "status": "completed",
                    "completed_at": now,
                    "observation_revision": revision,
                },
            )
        steps = [
            confirmations.get(
                index,
                {
                    "index": index,
                    "status": ("failed" if status == "failed" else "running")
                    if index == completed and status in {"running", "failed"}
                    else "pending",
                },
            )
            for index in range(5)
        ]
        native = dict(
            revision=revision,
            observed_at=now,
            simulation_tick=tick,
            pipette_volume_ul=float(deck.tip[0].sum()),
            tip_attached=attached,
            well_volumes_ul={
                "stock": None,
                "A1": float(deck.well[0].sum()),
                "A2": None,
                "A3": None,
            },
            mixing=dict(
                source_volumes_ul=deck.sources[0].cpu().tolist(),
                mixture_components_ul=deck.well[0].cpu().tolist(),
                source_order=cfg.source_order[0],
                lid_parked=bool(deck.lid_parked[0]),
                lid_attached=bool(deck.lid_attached[0]),
                active_tip=active_tip,
                tips_used=pickups.copy(),
                tips_discarded=drops.copy(),
                joint_positions=tensor(robot.data.joint_pos)[0].cpu().tolist(),
                native_action_index=action_index,
                native_action_count=len(sm.actions),
                native_action=str(
                    getattr(sequence[action_index], "description", None)
                    or type(sequence[action_index]).__name__
                )
                if action_index < len(sequence)
                else "Workflow finished",
            ),
        )
        snapshot = dict(
            session_id=binding["native_session_id"],
            run_id=request["run_id"],
            plan_hash=request["plan_hash"],
            sequence=revision - 1,
            session_revision=revision,
            engine="matterix",
            evidence="native",
            simulation_only=True,
            engine_version=binding["engine_version"],
            asset_version=binding["asset_version"],
            status=status,
            observed_at=now,
            steps=steps,
            native_state=native,
            error=error,
        )
        write_json(folder / "snapshot.json", snapshot)
        if status in {"completed", "failed"}:
            final_snapshot = snapshot

    try:
        # Warm render and wait for an authorized peer, without stepping physics.
        deadline = time.monotonic() + 180
        visible = 0
        while time.monotonic() < deadline:
            if not alive_lease(folder):
                raise RuntimeError("Native lease expired before execution")
            visible = visible + 1 if capture() else visible
            if time.monotonic() - last_report > 1:
                observe("loading")
                last_report = time.monotonic()
            ready = (
                read_json(folder / "viewer-ready.json")
                if (folder / "viewer-ready.json").exists()
                else {}
            )
            if (
                visible >= 3
                and ready.get("connected")
                and ready.get("native_session_id") == binding["native_session_id"]
                and time.time() - ready["observed_at"] < 2
            ):
                break
            time.sleep(0.02)
        else:
            raise RuntimeError("No authorized live viewer connected before the start deadline")
        begin = time.monotonic()
        for _ in range(16000):
            if not alive_lease(folder) or not app.is_running():
                raise RuntimeError("Native lease or Isaac application ended")
            actions, semantics = sm.step(observations)
            observations, _, terminated, truncated, _ = env.step(
                actions.to(env.device), semantic_actions=semantics
            )
            tick += 1
            # Observe attachment transitions every native tick; publish at 2 Hz.
            child = tip.tip_child_ids[0] if bool(tip.is_attached[0]) else None
            action_changed = int(sm.current_action_idx[0]) != last_action
            if child != active_tip or action_changed or time.monotonic() - last_report >= 0.5:
                observe("running")
                last_report = time.monotonic()
                last_action = int(sm.current_action_idx[0])
            capture()
            if (
                bool(sm.action_sequence_failure[0])
                or bool(tensor(terminated).any())
                or bool(tensor(truncated).any())
            ):
                raise RuntimeError("Native workflow failed or its episode ended")
            if bool(sm.action_sequence_success[0]):
                break
            # Keep observation comprehensible at real simulation speed.
            time.sleep(max(0, min(0.05, tick * env.step_dt - (time.monotonic() - begin))))
        else:
            raise RuntimeError("Native workflow exceeded its finite step budget")
        # Native pose checks supplement the semantic quantities validated by AWS.
        from matterix_assets.labware.flex_consumables import FLEX_TRASH_POS
        from matterix_assets.labware.flex_mixing import LID_PARK

        origins = tensor(env.scene.env_origins)
        lid = tensor(env.scene["vial_lid"].data.root_pos_w) - origins
        expected_tips = [f"Tips__A{i}" for i in range(1, 5)]
        collection = env.scene["tips_50"]
        ids = [collection.body_names.index(name) for name in expected_tips]
        positions = tensor(collection.data.body_link_pose_w)[0, ids, :3] - origins[0]
        if (
            pickups != expected_tips
            or drops != expected_tips
            or set(tip.used_tip_ids[0]) != set(expected_tips)
        ):
            raise RuntimeError("Native fresh-tip evidence differs from the recipe")
        if not bool(
            (
                torch.linalg.vector_norm(lid - torch.tensor(LID_PARK, device=env.device), dim=-1)
                < 0.008
            ).all()
        ):
            raise RuntimeError("Lid was not observed on its parking support")
        if not bool(
            (
                (positions[:, :2] - torch.tensor(FLEX_TRASH_POS[:2], device=env.device)).abs()
                < torch.tensor([0.11, 0.04], device=env.device)
            ).all()
        ) or not bool(((positions[:, 2] > 0.008) & (positions[:, 2] < 0.18)).all()):
            raise RuntimeError("Used tips were not observed inside the waste region")
        observe("completed")
    except Exception:
        import traceback

        traceback.print_exc()
        if final_snapshot is None:
            observe("failed", "Native workflow stopped; inspect its operator log and observations")
    finally:
        if final_snapshot is not None:
            # Freeze the terminal snapshot; no later frame invents a new result.
            deadline = time.monotonic() + 40
            while alive_lease(folder) and time.monotonic() < deadline:
                if (folder / "cleanup-request.json").exists():
                    reset_request = read_json(folder / "cleanup-request.json")
                    env.reset()
                    sm.reset()
                    env.sim.render()
                    checks = {
                        "objects": bool(
                            torch.allclose(
                                tensor(env.scene["vial_lid"].data.root_pos_w),
                                baseline_lid,
                                atol=0.002,
                            )
                        )
                        and not bool(deck.lid_attached.any())
                        and not bool(deck.lid_parked.any()),
                        "liquids": bool(
                            torch.allclose(
                                deck.sources, torch.full_like(deck.sources, 1500), atol=0.01
                            )
                        )
                        and bool(torch.allclose(deck.tip, torch.zeros_like(deck.tip), atol=0.001))
                        and bool(
                            torch.allclose(deck.well, torch.zeros_like(deck.well), atol=0.001)
                        ),
                        "tips": not bool(tip.is_attached.any())
                        and not tip.used_tip_ids[0]
                        and all(
                            bool(
                                torch.allclose(
                                    tensor(env.scene[name].data.body_link_pose_w),
                                    initial,
                                    atol=0.002,
                                )
                            )
                            for name, initial in baseline_tips.items()
                        ),
                        "controllers": bool(
                            torch.allclose(
                                tensor(robot.data.joint_pos), baseline_joints, atol=0.002
                            )
                        )
                        and int(sm.current_action_idx[0]) == 0
                        and not bool(command.remaining.any())
                        and command.mode[0] is None,
                        "stopped": False,
                    }
                    write_json(
                        folder / "reset-proof.json",
                        dict(
                            command_id=reset_request["command_id"],
                            native_session_id=binding["native_session_id"],
                            engine_version=binding["engine_version"],
                            asset_version=binding["asset_version"],
                            reset_verified=False,
                            checks=checks,
                        ),
                    )
                    break
                capture()
                time.sleep(0.05)
        frame.close()
        env.close()
        app.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", required=True)
    args = parser.parse_args()
    run(Path(args.folder))


if __name__ == "__main__":
    main()
