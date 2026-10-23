"""Execute one exact saved Flex Studio plan in the independent Matterix runtime.

The imported Matterix robot, native motion controller, disposable-tip semantics
and pipette storage execute the plan. Academy adds finite source/well accounting
coupled to measured native storage changes and a plan-specific scene. This is a
native semantic simulation, not a fluid solver or a physical robot validation.
"""

import argparse
import hashlib
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .native_files import FrameBuffer, alive_lease, read_json, write_json
from .native_isaac import activate, tensor
from .native_studio_runtime import (
    RIGHT_HOME,
    SCENE_VERSION,
    NativeLedger,
    compile_plan,
    joint_target,
    point,
    validate_assets,
)


def probe_report(folder, frame_count, checks):
    """Validate persisted terminal evidence; a loop counter is not completion."""
    from uuid import UUID

    from .remote_run import RemoteRunRequest, RemoteRunSnapshot, check_run_snapshot

    result = dict(
        scope="Local native render, execution and reset only; not browser qualification",
        scene="workflow-studio-flex",
        nonblack_frames=frame_count,
        completed=False,
        workflow_verified=False,
        browser_qualified=False,
        reset_checks={k: v for k, v in checks.items() if k != "stopped"},
        passed=False,
    )
    try:
        manifest = read_json(folder / "manifest.json")
        request = RemoteRunRequest.model_validate(manifest["request"])
        snapshot = RemoteRunSnapshot.model_validate(read_json(folder / "snapshot.json"))
        binding = manifest["binding"]
        check_run_snapshot(snapshot, UUID(binding["native_session_id"]), request)
        if snapshot.status != "completed":
            raise ValueError("The persisted native snapshot did not complete")
        if (snapshot.engine_version, snapshot.asset_version) != (
            binding["engine_version"],
            binding["asset_version"],
        ):
            raise ValueError("The native snapshot source revisions changed")
        frame_proof = read_json(folder / "frame-proof.json")
        if (
            frame_proof.get("source") != "native-renderer"
            or frame_proof.get("scene") != "workflow-studio-flex"
            or frame_proof.get("run_id") != str(request.run_id)
            or frame_proof.get("native_session_id") != binding["native_session_id"]
            or frame_proof.get("plan_hash") != request.plan_hash
            or not 3 <= frame_proof.get("nonblack_frames", 0) <= frame_count
        ):
            raise ValueError("The probe lacks three rendered frames bound to this exact run")
        expected_checks = {"objects", "liquids", "tips", "controllers"}
        if set(result["reset_checks"]) != expected_checks or not all(
            value is True for value in result["reset_checks"].values()
        ):
            raise ValueError("The native probe reset checks did not all pass")
        result.update(
            completed=True, workflow_verified=True, passed=True, plan_hash=request.plan_hash
        )
    except (ValueError, OSError, KeyError, TypeError) as exc:
        result["error"] = str(exc)
    return result


def build_scene(plan, origins, steps, assets):
    """Construct a fresh scene from imported assets; never run mix_four_vials."""
    from isaaclab.assets import RigidObjectCfg, RigidObjectCollectionCfg
    from isaaclab.sim import UsdFileCfg
    from isaaclab_tasks.utils import parse_env_cfg
    from matterix.managers.semantics.primitive_semantics.flex import FlexExhaleCfg, FlexInhaleCfg
    from matterix_assets.matterix_static_object import MatterixStaticObjectCfg

    # Reuse only the instrument's native config/sensors, replacing its scene,
    # sequence and recipe semantics before creating the environment.
    cfg = parse_env_cfg("Matterix-Flex-Mixing-v1", device="cuda:0", num_envs=1)
    robot = cfg.articulated_assets["flex"]
    robot.semantics = [
        s
        for s in robot.semantics
        if s.type
        not in {
            "FlexMixingState",
            "FlexMixingCommand",
            "FlexMixingTransition",
            "FlexTipAttachment",
        }
    ]
    for semantic in robot.semantics:
        if semantic.type == "FlexStorage":
            semantic.max_volume = 300.0
        if semantic.type == "FlexRightIsTipAttached":
            semantic.default_tip_asset_name = "studio_tips"
    robot.semantics += [
        FlexInhaleCfg(particles_per_step=0),
        FlexExhaleCfg(particles_per_step=(0, 0, 0)),
    ]
    base = assets / "labware/flex_mixing"
    tips = {}
    for step in steps:
        if step.kind != "pickup":
            continue
        tips[step.tip_id] = RigidObjectCfg(
            prim_path=f"{{ENV_REGEX_NS}}/StudioTips/{step.tip_id}",
            spawn=UsdFileCfg(usd_path=str(base / "tip_1000.usda")),
            init_state=RigidObjectCfg.InitialStateCfg(
                pos=point(step.target, (0, 0, 0.0105)), rot=(0, 0, 0, 1)
            ),
        )
    # A valid Studio plan must begin with pickup. Keep the assertion local so a
    # changed compiler cannot silently construct a robot without its inventory.
    if not tips:
        raise ValueError("Native Studio requires at least one disposable tip")
    cfg.objects = {
        "studio_plate": MatterixStaticObjectCfg(
            usd_path=str(base / "mix_plate.usda"), pos=origins["plate"]
        ),
        "studio_stock": MatterixStaticObjectCfg(
            usd_path=str(base / "reservoir.usda"), pos=origins["stock"]
        ),
        "studio_rack": MatterixStaticObjectCfg(
            usd_path=str(base / "rack_1000.usda"), pos=origins["tips"]
        ),
        "studio_waste": MatterixStaticObjectCfg(
            usd_path=str(base / "trash_collision.usda"),
            pos=point(origins["waste"], (0.0638, 0.04265, 0.003)),
            scale=(0.5, 0.65, 0.4),
        ),
        "studio_tips": RigidObjectCollectionCfg(rigid_objects=tips),
    }
    cfg.workflows = {"saved_studio_plan": []}
    cfg.episode_length_s = 1800
    cfg.prepare_for_video_rec(
        fps=15,
        resolution=(960, 540),
        render="balanced",
        eye=(0.48, -0.90, 0.90),
        lookat=(0.0, 0.30, 0.35),
    )
    cfg.recorders = None
    cfg.viewer.origin_type, cfg.viewer.env_index = "env", 0
    return cfg


def phases(step):
    """Native motion/semantic phases; boundaries allow observed pose checks."""
    from matterix_sm import MoveToJointConfigCfg, WaitCfg
    from matterix_sm.robot_action_spaces import FLEX_JOINT_ACTION_SPACE
    from matterix_sm.semantic_actions.flex_action import (
        SetFLEXPipetteFlowCfg,
        SetFLEXTipAttachedCfg,
    )

    def move(target, label):
        return MoveToJointConfigCfg(
            agent_assets="flex",
            target_joint_positions=joint_target(target),
            joint_indices=FLEX_JOINT_ACTION_SPACE.joint_indices,
            action_space_info=FLEX_JOINT_ACTION_SPACE,
            move_duration=1.2,
            position_threshold=0.001,
            settling_time=0.05,
            timeout=8.0,
            description=label,
        )

    above = (step.target[0], step.target[1], RIGHT_HOME[2])
    approach = [move(above, "Move above saved target"), move(step.target, "Lower to saved target")]
    if step.kind in {"pickup", "drop"}:
        action = [
            SetFLEXTipAttachedCfg(
                asset_name="flex",
                pipette="right",
                tip_asset_name="studio_tips",
                tip_child_id=step.tip_id,
                attached=step.kind == "pickup",
            )
        ]
        if step.kind == "drop":
            action.append(WaitCfg(duration=1.0))
    else:
        action = [
            SetFLEXPipetteFlowCfg(
                asset_name="flex",
                mode="aspirating" if step.kind == "aspirate" else "dispensing",
                volume=step.volume,
                flow_rate=40.0,
            ),
            WaitCfg(duration=step.volume / 40.0 + 0.1),
            SetFLEXPipetteFlowCfg(asset_name="flex", mode="idle"),
        ]
    return [approach, action, [move(above, "Retract clear of labware")]]


class LiquidVisuals:
    """Bound scene geometry driven by native semantic amounts, without fluid claims."""

    def __init__(self, env, origins):
        from pxr import Gf, UsdGeom

        self.Gf, self.UsdGeom, self.entries = Gf, UsdGeom, {}
        stage, root = env.scene.stage, env.scene.env_prim_paths[0]
        for well in ("stock", "A1", "A2", "A3"):
            origin = origins["stock" if well == "stock" else "plate"]
            offset = (
                (0.0143, 0.04265, 0.006)
                if well == "stock"
                else (0.0143 + (int(well[1]) - 1) * 0.009, 0.07415, 0.003)
            )
            center = point(origin, offset)
            mesh = UsdGeom.Cube.Define(stage, f"{root}/StudioLiquid_{well}")
            mesh.CreateSizeAttr(1.0)
            mesh.CreateDisplayColorAttr(
                [Gf.Vec3f(0.08, 0.55, 0.74) if well == "stock" else Gf.Vec3f(0.35, 0.72, 0.82)]
            )
            translate, scale = mesh.AddTranslateOp(), mesh.AddScaleOp()
            self.entries[well] = (center, translate, scale)
        # The imported plate carries an example liquid prim. Hide it so the
        # exact saved initial volumes are the only liquid visualization.
        old = stage.GetPrimAtPath(f"{root}/StaticObjects_studio_plate/Liquid_A1")
        if old.IsValid():
            UsdGeom.Imageable(old).MakeInvisible()
        from pxr import Usd

        waste = stage.GetPrimAtPath(f"{root}/StaticObjects_studio_waste")
        if not waste.IsValid():
            raise RuntimeError("The saved D3 disposal receptacle was not spawned")
        for prim in Usd.PrimRange(waste):
            if prim.IsA(UsdGeom.Gprim):
                UsdGeom.Imageable(prim).MakeVisible()
                UsdGeom.Gprim(prim).CreateDisplayColorAttr([Gf.Vec3f(0.22, 0.26, 0.30)])

    def update(self, wells):
        for well, volume in wells.items():
            center, translate, scale = self.entries[well]
            width, depth = (0.006, 0.060) if well == "stock" else (0.0076, 0.0076)
            height = max(0.00001, volume * 1e-9 / (width * depth))
            translate.Set(self.Gf.Vec3d(center[0], center[1], center[2] + height / 2))
            scale.Set(self.Gf.Vec3f(width, depth, height))


def run(folder, *, probe=False):
    """A probe renders/executes/resets locally; it never constitutes browser acceptance."""
    from .native_runner import NativeConfig
    from .remote_run import RemoteRunRequest

    manifest = read_json(folder / "manifest.json")
    config = NativeConfig.model_validate(manifest["config"])
    binding, request = manifest["binding"], manifest["request"]
    RemoteRunRequest.model_validate(request)  # Includes the complete saved-plan hash.
    plan, origins, steps = compile_plan(request["experiment"])
    config.verify()
    validate_assets(plan, config)
    activate(Path(config.matterix_root))
    from isaaclab.app import AppLauncher

    parser = argparse.ArgumentParser()
    AppLauncher.add_app_launcher_args(parser)
    flags = ["--enable_cameras", "--device", "cuda:0", "--viz", "kit", "--livestream", "0"]
    if config.headless:
        flags += ["--headless"]
    app = AppLauncher(parser.parse_args(flags)).app
    env, frame = None, None
    try:
        import builtins

        import gymnasium as gym
        import matterix_tasks  # noqa: F401
        import numpy as np
        import torch
        from matterix_sm import StateMachine
        from pxr import UsdGeom

        cfg = build_scene(plan, origins, steps, Path(config.assets_data_dir))
        env = gym.make("Matterix-Flex-Mixing-v1", cfg=cfg, render_mode="rgb_array").unwrapped
        if getattr(builtins, "ISAACLAB_CALLBACK_EXCEPTION", None):
            raise RuntimeError("Studio native assets failed to initialize")
        observations, _ = env.reset()
        robot = env.scene["flex"]
        tips = env.scene["studio_tips"]
        tip = env.semantic_manager.full_semantic_predicates["flex/FlexRightIsTipAttached"]
        storage = env.semantic_manager.full_semantic_states["flex/FlexStorage"]
        inhale = env.semantic_manager.full_semantic_predicates["flex/FlexIsInhaling"]
        exhale = env.semantic_manager.full_semantic_predicates["flex/FlexIsExhaling"]
        baseline_joints = tensor(robot.data.joint_pos).clone()
        baseline_tips = tensor(tips.data.body_link_pose_w).clone()

        def static_frames():
            cache = UsdGeom.XformCache()
            result = {}
            for name in ("plate", "stock", "rack", "waste"):
                prim = env.scene.stage.GetPrimAtPath(
                    f"{env.scene.env_prim_paths[0]}/StaticObjects_studio_{name}"
                )
                if not prim.IsValid():
                    raise RuntimeError("Saved labware geometry is missing from the native scene")
                result[name] = np.asarray(cache.GetLocalToWorldTransform(prim))
            return result

        baseline_objects = static_frames()
        for name, logical in (("plate", "plate"), ("stock", "stock"), ("rack", "tips")):
            if not np.allclose(baseline_objects[name][3, :3], origins[logical], atol=0.002):
                raise RuntimeError("Native labware placement differs from the saved slot mapping")
        ledger, visuals = NativeLedger(plan), LiquidVisuals(env, origins)
        all_phases = [phases(step) for step in steps]
        action_count = sum(len(phase) for sequence in all_phases for phase in sequence)
        action_index, tick, revision, completed, frame_count = 0, 0, 1, 0, 0
        last_render, last_report = 0.0, 0.0
        label, terminal = "Loading saved workflow", False
        confirmations = {}
        frame_path = Path(config.frame_root) / (binding["native_session_id"] + ".rgb")
        frame_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        frame = FrameBuffer(frame_path, create=True)
        write_json(
            folder / "studio-plan.json",
            dict(
                scene_version=SCENE_VERSION,
                scene="workflow-studio-flex",
                instrument="flex",
                run_id=request["run_id"],
                native_session_id=binding["native_session_id"],
                plan_hash=request["plan_hash"],
                engine_version=config.engine_version,
                asset_version=config.asset_version,
                labware_slots=plan.layout,
                native_origins_m=origins,
                steps=[asdict(step) for step in steps],
                observation_model="native-semantic",
                native_action_count=action_count,
            ),
        )

        def alive():
            if not app.is_running() or (not probe and not alive_lease(folder)):
                raise RuntimeError("Native lease or Isaac application ended")

        def capture():
            nonlocal last_render, frame_count
            if time.monotonic() - last_render < 1 / 15:
                return False
            visuals.update(ledger.wells)
            env.sim.render()
            rgb, last_render = env.render(), time.monotonic()
            if rgb is None or rgb.shape[:2] != (540, 960) or float(np.mean(rgb)) <= 1:
                return False
            pixels = np.asarray(rgb[..., :3], dtype=np.uint8).tobytes()
            frame.write(pixels, tick)
            frame_count += 1
            if frame_count == 3 or frame_count % 15 == 0:
                write_json(
                    folder / "frame-proof.json",
                    dict(
                        run_id=request["run_id"],
                        native_session_id=binding["native_session_id"],
                        plan_hash=request["plan_hash"],
                        scene="workflow-studio-flex",
                        source="native-renderer",
                        nonblack_frames=frame_count,
                        simulation_tick=tick,
                        rgb_sha256=hashlib.sha256(pixels).hexdigest(),
                    ),
                )
            return True

        def publish(status, error=None):
            nonlocal revision, last_report
            revision += 1
            now = datetime.now(UTC).isoformat()
            for index in range(completed):
                confirmations.setdefault(
                    index,
                    dict(
                        index=index,
                        status="completed",
                        completed_at=now,
                        observation_revision=revision,
                    ),
                )
            progress = [
                confirmations.get(
                    i,
                    dict(
                        index=i,
                        status=("failed" if status == "failed" else "running")
                        if i == completed and status in {"running", "failed"}
                        else "pending",
                    ),
                )
                for i in range(len(steps))
            ]
            native = dict(
                revision=revision,
                observed_at=now,
                simulation_tick=tick,
                pipette_volume_ul=float(storage.state[0]),
                tip_attached=bool(tip.is_attached[0]),
                well_volumes_ul=ledger.wells.copy(),
                studio=dict(
                    instrument="flex",
                    scene="workflow-studio-flex",
                    observation_model="native-semantic",
                    labware_slots=plan.layout,
                    native_action_index=action_index,
                    native_action_count=action_count,
                    native_action=label,
                    waste_volume_ul=ledger.waste,
                ),
            )
            snapshot = dict(
                session_id=binding["native_session_id"],
                run_id=request["run_id"],
                plan_hash=request["plan_hash"],
                sequence=revision,
                session_revision=revision,
                engine="matterix",
                evidence="native",
                simulation_only=True,
                engine_version=binding["engine_version"],
                asset_version=binding["asset_version"],
                status=status,
                observed_at=now,
                steps=progress,
                native_state=native,
                error=error,
            )
            write_json(folder / "snapshot.json", snapshot)
            last_report = time.monotonic()

        def reset(command_id):
            env.reset()
            ledger.reset()
            visuals.update(ledger.wells)
            env.sim.render()
            checks = {
                "objects": all(
                    np.allclose(pose, baseline_objects[name], atol=0.002)
                    for name, pose in static_frames().items()
                ),
                "liquids": abs(float(storage.state[0])) < 0.01
                and ledger.wells == ledger.initial
                and ledger.waste == 0,
                "tips": not bool(tip.is_attached.any())
                and not tip.used_tip_ids[0]
                and bool(
                    torch.allclose(tensor(tips.data.body_link_pose_w), baseline_tips, atol=0.002)
                ),
                "controllers": bool(
                    torch.allclose(tensor(robot.data.joint_pos), baseline_joints, atol=0.002)
                )
                and not bool(inhale.is_inhaling.any())
                and not bool(exhale.is_exhaling.any())
                and not bool(inhale.remaining_volume.any())
                and not bool(exhale.remaining_volume.any()),
                "stopped": False,
            }
            write_json(
                folder / "reset-proof.json",
                dict(
                    command_id=command_id,
                    native_session_id=binding["native_session_id"],
                    engine_version=binding["engine_version"],
                    asset_version=binding["asset_version"],
                    reset_verified=False,
                    checks=checks,
                ),
            )
            return checks

        try:
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                alive()
                capture()
                if time.monotonic() - last_report > 1:
                    publish("loading")
                ready = (
                    read_json(folder / "viewer-ready.json")
                    if (folder / "viewer-ready.json").exists()
                    else {}
                )
                if frame_count >= 3 and (
                    probe
                    or (
                        ready.get("connected")
                        and ready.get("native_session_id") == binding["native_session_id"]
                        and time.time() - ready.get("observed_at", 0) < 2
                    )
                ):
                    break
                time.sleep(0.02)
            else:
                raise RuntimeError("No authorized live viewer connected before the start deadline")
            begin = time.monotonic()
            for step, sequences in zip(steps, all_phases, strict=True):
                ledger.check(step.kind, step.well, step.volume)
                initial_volume = ledger.pipette
                label = f"{step.index + 1}. {step.kind} {step.well}"
                for phase_index, sequence in enumerate(sequences):
                    sm = StateMachine(num_envs=1, dt=env.step_dt, device=env.device)
                    sm.set_action_sequence(sequence)
                    sm.reset()
                    offset = action_index
                    for _ in range(5000):
                        alive()
                        if time.monotonic() - begin > 1500:
                            raise RuntimeError("Saved workflow exceeded its bounded runtime")
                        actions, semantics = sm.step(observations)
                        observations, _, terminated, truncated, _ = env.step(
                            actions.to(env.device), semantic_actions=semantics
                        )
                        tick += 1
                        if getattr(builtins, "ISAACLAB_CALLBACK_EXCEPTION", None):
                            raise RuntimeError("Native callback failed")
                        if (
                            step.kind == "pickup"
                            and bool(tip.is_attached[0])
                            and not ledger.attached
                        ):
                            if tip.tip_child_ids[0] != step.tip_id:
                                raise RuntimeError("Native pickup selected a different saved tip")
                            ledger.attached, ledger.used = True, ledger.used + 1
                        if step.kind == "drop" and not bool(tip.is_attached[0]) and ledger.attached:
                            # The adapter's disposal semantic empties the observed
                            # native tip into the bound waste container exactly once.
                            ledger.waste += float(storage.state[0])
                            storage.state.zero_()
                            ledger.pipette, ledger.attached = 0.0, False
                        ledger.observe_volume(float(storage.state[0]), step.kind, step.well)
                        action_index = offset + min(int(sm.current_action_idx[0]), len(sequence))
                        if time.monotonic() - last_report > 0.5:
                            publish("running")
                        capture()
                        if (
                            bool(sm.action_sequence_failure[0])
                            or bool(tensor(terminated).any())
                            or bool(tensor(truncated).any())
                        ):
                            raise RuntimeError("Native saved workflow action failed")
                        if bool(sm.action_sequence_success[0]):
                            action_index = offset + len(sequence)
                            break
                        time.sleep(
                            max(0, min(0.03, tick * env.step_dt - (time.monotonic() - begin)))
                        )
                    else:
                        raise RuntimeError("Native action exceeded its finite tick budget")
                    if phase_index == 0:
                        nozzle = (
                            tensor(env.scene["right_frame_flex"].data.target_pos_w)[0, 0]
                            - tensor(env.scene.env_origins)[0]
                        )
                        if (
                            float(
                                torch.linalg.vector_norm(
                                    nozzle - torch.tensor(step.target, device=env.device)
                                )
                            )
                            > 0.003
                        ):
                            raise RuntimeError(
                                "Native nozzle has not reached the saved layout target"
                            )
                    if phase_index == 1:
                        expected = (
                            initial_volume
                            + (step.volume if step.kind == "aspirate" else -step.volume)
                            if step.kind in {"aspirate", "dispense"}
                            else (0 if step.kind == "drop" else initial_volume)
                        )
                        if abs(float(storage.state[0]) - expected) > 0.02:
                            raise RuntimeError(
                                "Native observed transfer differs from the exact saved volume"
                            )
                        if step.kind in {"pickup", "drop"} and bool(tip.is_attached[0]) != (
                            step.kind == "pickup"
                        ):
                            raise RuntimeError(
                                "Native tip lifecycle did not confirm the saved step"
                            )
                        if step.kind == "drop":
                            body = tips.body_names.index(step.tip_id)
                            position = (
                                tensor(tips.data.body_link_pose_w)[0, body, :3]
                                - tensor(env.scene.env_origins)[0]
                            )
                            center = point(origins["waste"], (0.0638, 0.04265, 0.003))
                            if (
                                abs(float(position[0]) - center[0]) > 0.060
                                or abs(float(position[1]) - center[1]) > 0.026
                                or not center[2] - 0.01 < float(position[2]) < center[2] + 0.18
                            ):
                                raise RuntimeError(
                                    "Native discarded tip was not observed in the saved waste region"
                                )
                        if (
                            float(inhale.remaining_volume[0]) > 0.001
                            or float(exhale.remaining_volume[0]) > 0.001
                        ):
                            raise RuntimeError("Native flow has not finished")
                completed += 1
                publish("running")
            label = "Saved workflow completed"
            publish("completed")
            terminal = True
        except Exception:
            import traceback

            traceback.print_exc()
            publish(
                "failed", "Native saved workflow stopped; inspect its bound scene and operator log"
            )
            terminal = True
        finally:
            if terminal and probe:
                checks = reset("local-studio-probe")
                write_json(folder / "studio-probe.json", probe_report(folder, frame_count, checks))
            elif terminal:
                deadline = time.monotonic() + 40
                while alive_lease(folder) and time.monotonic() < deadline:
                    if (folder / "cleanup-request.json").exists():
                        reset(read_json(folder / "cleanup-request.json")["command_id"])
                        break
                    capture()
                    time.sleep(0.05)
    finally:
        if frame is not None:
            frame.close()
            if probe:
                frame_path.unlink(missing_ok=True)
        if env is not None:
            env.close()
        app.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder")
    parser.add_argument(
        "--probe", action="store_true", help="Local operator probe only; never a browser acceptance"
    )
    parser.add_argument("--config", help="NativeConfig for an isolated local probe")
    parser.add_argument("--output", help="JSON result for an isolated local probe")
    args = parser.parse_args()
    if args.folder:
        if args.probe or args.config or args.output:
            parser.error("Use either --folder or --probe --config --output")
        run(Path(args.folder))
        return
    if not (args.probe and args.config and args.output):
        parser.error("Use --folder, or --probe --config CONFIG --output RESULT.json")
    from uuid import uuid4

    from .models import Action, Experiment
    from .remote_run import workflow_digest

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    folder = output.parent / f"studio-probe-{uuid4()}"
    folder.mkdir(mode=0o700)
    config = read_json(args.config)
    plan = Experiment(
        course_id="workflow-sandbox",
        instrument="flex",
        diluent_volume=0,
        actions=[
            Action(kind="pickup"),
            Action(kind="aspirate", volume=100),
            Action(kind="dispense", well="A1", volume=100),
            Action(kind="drop"),
        ],
    )
    write_json(
        folder / "manifest.json",
        dict(
            config=config,
            binding=dict(
                native_session_id=str(uuid4()),
                expected_revision=1,
                engine_version=config["engine_version"],
                asset_version=config["asset_version"],
            ),
            request=dict(
                run_id=str(uuid4()),
                expected_revision=1,
                experiment=plan.model_dump(mode="json"),
                plan_hash=workflow_digest(plan),
            ),
        ),
    )
    try:
        run(folder, probe=True)
        report = read_json(folder / "studio-probe.json")
    except Exception as exc:
        report = dict(
            passed=False,
            workflow_verified=False,
            browser_qualified=False,
            error=str(exc),
            scope="Local native probe only",
        )
    report["artifacts"] = str(folder)
    write_json(output, report)
    if not report["passed"]:
        raise SystemExit("Studio native probe did not pass; inspect its bound artifacts")


if __name__ == "__main__":
    main()
