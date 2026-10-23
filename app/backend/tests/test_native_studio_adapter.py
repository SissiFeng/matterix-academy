"""CPU adapter/IPC contract tests; these do not establish GPU or browser evidence."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from academy.gateway import GatewayUnavailable
from academy.models import Action, Experiment
from academy.native_files import write_json
from academy.native_runner import NativeConfig, NativeFlexRunner
from academy.native_studio_isaac import probe_report
from academy.native_studio_runtime import (
    ASSET_COMMIT,
    ASSET_FILES,
    ENGINE_COMMIT,
    RIGHT_HOME,
    SLOTS,
    NativeLedger,
    compile_plan,
    flex_capability,
    joint_target,
    slot_origin,
    validate_assets,
)
from academy.native_supervisor import runtime_module
from academy.recipes import MixingPlan
from academy.remote_run import workflow_digest


def experiment(volume=100, **changes):
    return Experiment(
        course_id="workflow-sandbox",
        diluent_volume=0,
        actions=[
            Action(kind="pickup"),
            Action(kind="aspirate", volume=volume),
            Action(kind="dispense", well="A1", volume=volume),
            Action(kind="drop"),
        ],
        **changes,
    )


def request(plan):
    return dict(
        run_id=str(uuid4()),
        expected_revision=1,
        experiment=plan.model_dump(mode="json"),
        plan_hash=workflow_digest(plan),
    )


def test_saved_amount_and_moved_slot_change_the_compiled_native_plan():
    first = experiment(100)
    second = experiment(50, layout={**first.layout, "plate": "C2"})
    p1, origins1, steps1 = compile_plan(first)
    p2, origins2, steps2 = compile_plan(second)
    assert p1.model_dump() == first.model_dump()
    assert p2.model_dump() == second.model_dump()
    assert steps1[1].volume == 100 and steps2[1].volume == 50
    assert steps1[2].volume == 100 and steps2[2].volume == 50
    assert steps2[2].target[1] - steps1[2].target[1] == pytest.approx(0.107)
    assert origins2["plate"][1] - origins1["plate"][1] == pytest.approx(0.107)
    assert workflow_digest(p1) != workflow_digest(p2)


@pytest.mark.parametrize("slot", SLOTS)
def test_declared_native_slots_are_reachable_for_every_liquid_target(slot):
    others = [value for value in SLOTS if value != slot]
    plan = experiment(layout={"stock": others[0], "plate": slot, "tips": others[1], "waste": "D3"})
    for well in ("A1", "A2", "A3"):
        changed = plan.model_copy(deep=True)
        changed.actions[2].well = well
        _, _, steps = compile_plan(changed)
        for step in steps:
            joint_target(step.target)
            joint_target((step.target[0], step.target[1], RIGHT_HOME[2]))


def test_native_capability_excludes_occupied_cad_region_and_does_not_enable_ot2():
    cap = flex_capability()
    assert cap["instrument"] == "flex" and cap["pipette_capacity_ul"] == 300
    assert "A3" not in cap["slots"]["plate"] and cap["slots"]["waste"] == ["D3"]
    with pytest.raises(ValueError, match="A3"):
        compile_plan(experiment(layout={"stock": "D1", "plate": "A3", "tips": "B1", "waste": "D3"}))
    with pytest.raises(ValueError, match="unavailable"):
        slot_origin("1")
    ot2 = experiment(
        instrument="ot2", layout={"stock": "1", "plate": "2", "tips": "4", "waste": "12"}
    )
    with pytest.raises(ValueError, match="Flex Studio"):
        compile_plan(ot2)


@pytest.mark.parametrize(
    "actions,expected",
    [
        ([], "Add a workflow"),
        ([Action(kind="aspirate")], "attached tip"),
        ([Action(kind="pickup"), Action(kind="pickup")], "empty mount"),
        ([Action(kind="pickup"), Action(kind="dispense")], "pipette liquid"),
        ([Action(kind="pickup"), Action(kind="aspirate", volume=301)], "between 1 and 300"),
        ([Action(kind="pickup"), Action(kind="aspirate", well="A1")], "source liquid"),
    ],
)
def test_invalid_saved_plans_fail_before_native_allocation(actions, expected):
    plan = experiment().model_copy(update={"actions": actions})
    with pytest.raises(ValueError, match=expected):
        compile_plan(plan)


def test_ledger_does_not_credit_requested_volume_before_native_observations():
    ledger = NativeLedger(experiment())
    ledger.preview("pickup", "stock", 100)
    ledger.check("aspirate", "stock", 100)
    assert ledger.wells["stock"] == 1000 and ledger.pipette == 0
    ledger.observe_volume(25, "aspirate", "stock")
    assert ledger.wells["stock"] == 975 and ledger.pipette == 25
    ledger.observe_volume(100, "aspirate", "stock")
    ledger.observe_volume(50, "dispense", "A1")
    assert ledger.wells == {"stock": 900, "A1": 50, "A2": 0, "A3": 0}
    ledger.preview("drop", "stock", 100)
    assert ledger.waste == 50 and ledger.pipette == 0 and not ledger.attached
    ledger.assert_conserved()
    ledger.reset()
    assert ledger.wells == ledger.initial and ledger.used == ledger.waste == ledger.pipette == 0


def test_wrong_native_flow_direction_or_uncommanded_change_stops_the_run():
    ledger = NativeLedger(experiment())
    with pytest.raises(RuntimeError, match="outside a liquid action"):
        ledger.observe_volume(5, "pickup", "stock")
    ledger.preview("pickup", "stock", 100)
    ledger.observe_volume(30, "aspirate", "stock")
    with pytest.raises(RuntimeError, match="opposite"):
        ledger.observe_volume(20, "aspirate", "stock")
    with pytest.raises(RuntimeError, match="invalid volume"):
        ledger.observe_volume(float("nan"), "aspirate", "stock")


def test_valid_nonempty_final_tip_is_not_rewritten_into_a_discard():
    plan = experiment().model_copy(
        update={"actions": [Action(kind="pickup"), Action(kind="aspirate", volume=75)]}
    )
    _, _, steps = compile_plan(plan)
    assert [step.kind for step in steps] == ["pickup", "aspirate"]
    pickup_only = plan.model_copy(update={"actions": [Action(kind="pickup")]})
    assert len(compile_plan(pickup_only)[2]) == 1


def test_discarded_tips_are_not_reused_in_an_exact_saved_plan():
    plan = experiment()
    plan.actions += deepcopy(plan.actions)
    _, _, steps = compile_plan(plan)
    assert steps[0].tip_id == steps[3].tip_id == "Tips__A1"
    assert steps[4].tip_id == steps[7].tip_id == "Tips__B1"


def test_native_module_catalog_is_bound_to_the_saved_plan_hash():
    assert runtime_module(request(experiment())) == "native_studio_isaac"
    assert runtime_module(request(MixingPlan())) == "native_isaac"
    changed = request(experiment())
    changed["experiment"]["actions"][1]["volume"] = 50
    with pytest.raises(ValueError, match="saved plan hash"):
        runtime_module(changed)
    with pytest.raises(ValueError, match="no adapter"):
        runtime_module(request(Experiment()))


def test_studio_assets_require_exact_pins_materialized_payloads_and_internal_paths(tmp_path):
    config = SimpleNamespace(
        engine_version=ENGINE_COMMIT, asset_version=ASSET_COMMIT, assets_data_dir=str(tmp_path)
    )
    for name in ASSET_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"unit-only-payload")
    validate_assets(experiment(), config)
    (tmp_path / ASSET_FILES[0]).write_bytes(b"version https://git-lfs.github.com/spec/v1\n")
    with pytest.raises(ValueError, match="LFS pointer"):
        validate_assets(experiment(), config)
    config.engine_version = "a" * 40
    with pytest.raises(ValueError, match="exact reviewed"):
        validate_assets(experiment(), config)
    ot2 = experiment(
        instrument="ot2", layout={"stock": "1", "plate": "2", "tips": "4", "waste": "12"}
    )
    with pytest.raises(ValueError, match="OT-2 Studio"):
        validate_assets(ot2, config)


def test_runner_refuses_missing_studio_asset_before_creating_allocation(tmp_path, monkeypatch):
    config = NativeConfig(
        python="/fixture/python",
        matterix_root="/fixture/code",
        assets_root=str(tmp_path),
        assets_data_dir=str(tmp_path),
        engine_version=ENGINE_COMMIT,
        asset_version=ASSET_COMMIT,
        run_root=str(tmp_path / "runs"),
        frame_root=str(tmp_path / "frames"),
    )
    path = tmp_path / "config.json"
    write_json(path, config.model_dump())
    monkeypatch.setattr(NativeConfig, "verify", lambda _: None)
    runner = NativeFlexRunner(path, None)
    plan = experiment()
    local = dict(
        allocation_id=str(uuid4()),
        run=dict(run_id=str(uuid4()), plan=plan.model_dump(), plan_hash=workflow_digest(plan)),
    )
    with pytest.raises(GatewayUnavailable, match="native asset is unavailable"):
        runner.prepare(local)
    assert not runner.folder(local).exists()
    local["run"]["plan_hash"] = "f" * 64
    with pytest.raises(GatewayUnavailable, match="workflow hash"):
        runner.prepare(local)
    assert not runner.folder(local).exists()


def probe_fixture(folder):
    """Structured unit fixture only; no renderer or native engine runs here."""
    from academy.remote_run import RemoteRunRequest
    from test_remote_run import report

    plan, native_session = experiment(), uuid4()
    data = request(plan)
    body = report(native_session, RemoteRunRequest.model_validate(data), completed=4, sequence=2)
    body.update(engine_version=ENGINE_COMMIT, asset_version=ASSET_COMMIT)
    body["native_state"].update(
        pipette_volume_ul=0,
        tip_attached=False,
        well_volumes_ul={"stock": 900, "A1": 100, "A2": 0, "A3": 0},
        studio=dict(
            scene="workflow-studio-flex",
            instrument="flex",
            observation_model="native-semantic",
            labware_slots=plan.layout,
            native_action_index=21,
            native_action_count=21,
            native_action="Saved workflow completed",
            waste_volume_ul=0,
        ),
    )
    write_json(
        folder / "manifest.json",
        dict(
            request=data,
            binding=dict(
                native_session_id=str(native_session),
                engine_version=ENGINE_COMMIT,
                asset_version=ASSET_COMMIT,
            ),
        ),
    )
    write_json(folder / "snapshot.json", body)
    write_json(
        folder / "frame-proof.json",
        dict(
            source="native-renderer",
            scene="workflow-studio-flex",
            run_id=data["run_id"],
            native_session_id=str(native_session),
            plan_hash=data["plan_hash"],
            nonblack_frames=3,
        ),
    )
    return body, dict(objects=True, liquids=True, tips=True, controllers=True, stopped=False)


def test_probe_never_qualifies_a_failed_terminal_snapshot_despite_all_steps_completed(tmp_path):
    body, checks = probe_fixture(tmp_path)
    assert probe_report(tmp_path, 3, checks)["passed"]
    body.update(status="failed", error="A postcondition failed after the final step")
    write_json(tmp_path / "snapshot.json", body)
    result = probe_report(tmp_path, 3, checks)
    assert not result["passed"] and not result["workflow_verified"]
    assert not result["browser_qualified"]


def test_probe_validates_exact_terminal_volumes_bound_frames_and_every_reset_check(tmp_path):
    body, checks = probe_fixture(tmp_path)
    body["native_state"]["well_volumes_ul"].update(stock=950, A1=50)
    write_json(tmp_path / "snapshot.json", body)
    assert not probe_report(tmp_path, 3, checks)["passed"]
    _, checks = probe_fixture(tmp_path)
    assert not probe_report(tmp_path, 2, checks)["passed"]
    assert not probe_report(tmp_path, 3, {**checks, "tips": False})["passed"]
    assert not probe_report(tmp_path, 3, {"objects": True})["passed"]


def test_probe_cli_cannot_bypass_viewer_on_an_existing_run_folder(tmp_path, monkeypatch):
    import sys

    from academy import native_studio_isaac

    calls = []
    monkeypatch.setattr(
        native_studio_isaac, "run", lambda *args, **kwargs: calls.append((args, kwargs))
    )
    monkeypatch.setattr(sys, "argv", ["native_studio_isaac", "--folder", str(tmp_path), "--probe"])
    with pytest.raises(SystemExit) as error:
        native_studio_isaac.main()
    assert error.value.code == 2 and calls == []
    monkeypatch.setattr(sys, "argv", ["native_studio_isaac", "--folder", str(tmp_path)])
    native_studio_isaac.main()
    assert calls == [((tmp_path,), {})]


def test_probe_cli_uses_an_isolated_folder_and_exits_failure_for_failed_native_evidence(
    tmp_path, monkeypatch
):
    import sys

    from academy import native_studio_isaac

    config, output = tmp_path / "config.json", tmp_path / "report.json"
    write_json(config, dict(engine_version=ENGINE_COMMIT, asset_version=ASSET_COMMIT))
    folders = []

    def mock_native_run(folder, *, probe):
        assert probe is True and folder != tmp_path
        folders.append(folder)
        write_json(
            folder / "studio-probe.json",
            dict(passed=False, workflow_verified=False, browser_qualified=False),
        )

    monkeypatch.setattr(native_studio_isaac, "run", mock_native_run)
    monkeypatch.setattr(
        sys,
        "argv",
        ["native_studio_isaac", "--probe", "--config", str(config), "--output", str(output)],
    )
    with pytest.raises(SystemExit):
        native_studio_isaac.main()
    assert len(folders) == 1 and output.exists()
