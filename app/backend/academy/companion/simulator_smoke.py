"""Optional real Opentrons Python simulator smoke, never a physical qualification.

Run only in a separately reviewed environment with opentrons==9.0.0 installed.
It uses the vendor's explicit simulator, real schema-2 labware definitions, a
private temporary config directory, and no Academy or robot network clients.
"""

import io
import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from academy.models import Action, Experiment
from academy.remote_run import workflow_digest

from .compiler import compile_plan
from .config import RobotProfile, digest


def main():
    with tempfile.TemporaryDirectory(prefix="academy-protocol-simulator-") as directory:
        os.environ["OT_API_CONFIG_DIR"] = directory
        # Import only after the simulator's configuration is isolated.
        import opentrons
        from opentrons import simulate
        from opentrons_shared_data.labware import load_definition

        if opentrons.__version__ != "9.0.0":
            raise RuntimeError("This optional smoke is pinned to opentrons 9.0.0")
        results = []
        original_run = simulate.RunOrchestrator.run
        observed_commands = []

        async def observe_run(orchestrator, *args, **kwargs):
            result = await original_run(orchestrator, *args, **kwargs)
            observed_commands[:] = [
                {
                    "commandType": item.commandType,
                    "status": item.status.value,
                    "params": item.params.model_dump(mode="json"),
                }
                for item in result.commands
            ]
            return result

        for instrument in ("flex", "ot2"):
            slots = (
                {"tips": "B1", "stock": "D1", "plate": "D2", "waste": "D3"}
                if instrument == "flex"
                else {"tips": "1", "stock": "2", "plate": "3", "waste": "12"}
            )
            names = {
                "tips": "opentrons_flex_96_tiprack_1000ul"
                if instrument == "flex"
                else "opentrons_96_tiprack_300ul",
                "stock": "nest_12_reservoir_15ml",
                "plate": "corning_96_wellplate_360ul_flat",
            }
            labware = {}
            for name, load_name in names.items():
                definition = load_definition(load_name, 1)
                labware[name] = {
                    "load_name": load_name,
                    "namespace": definition["namespace"],
                    "version": 1,
                    "sha256": digest(definition),
                    "definition": definition,
                    "slot": slots[name],
                }
            profile = RobotProfile.model_validate(
                {
                    "qualification_id": "SIMULATOR-ONLY-NOT-HARDWARE",
                    "qualified_by": "software smoke",
                    "qualified_until": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
                    "instrument": instrument,
                    "serial": "SIMULATOR-ONLY",
                    "source_commit": "0" * 40,
                    "release_id": "simulator-only",
                    "artifact_sha256": "0" * 64,
                    "firmware": "simulator-only",
                    "api_version": "9.0.0",
                    "connector_version": "simulator-only",
                    "runtime_contract_id": "simulator-only",
                    "runtime_release_id": "simulator-only",
                    "runtime_bundle_sha256": "0" * 64,
                    "calibration_sha256": "0" * 64,
                    "sila_server_uuid": "00000000-0000-0000-0000-000000000000",
                    "sila_features_sha256": "0" * 64,
                    "pipette_serial": "SIMULATOR-ONLY",
                    "pipette_model": "flex_1channel_1000"
                    if instrument == "flex"
                    else "p300_single_gen2",
                    "pipette_mount": "left",
                    "min_volume_ul": 20,
                    "max_volume_ul": 300,
                    "labware": labware,
                    "tip_wells": ["A1"],
                    "stock_well": "A1",
                    "capacity_ul": {"stock": 1500, "A1": 300, "A2": 300, "A3": 300},
                    "calibration_confirmed": True,
                    "deck_confirmed": True,
                }
            )
            plan = Experiment(
                course_id="workflow-sandbox",
                instrument=instrument,
                layout=slots,
                source_volume=1000,
                diluent_volume=0,
                actions=[
                    Action(kind="pickup"),
                    Action(kind="aspirate", volume=100),
                    Action(kind="dispense", well="A1", volume=100),
                    Action(kind="drop"),
                ],
            )
            protocol = compile_plan(plan, workflow_digest(plan), profile)
            with patch.object(simulate.RunOrchestrator, "run", observe_run):
                logs, _bundle = simulate.simulate(
                    io.StringIO(protocol.source.decode()),
                    file_name="academy_protocol.py",
                    custom_labware_paths=[str(Path(directory))],
                    log_level="error",
                )
            results.append(
                {
                    "instrument": instrument,
                    "plan_hash": protocol.plan_hash,
                    "planned_actions": protocol.action_count,
                    "engine_commands": list(observed_commands),
                    "log": [str(item.get("payload", {}).get("text", "")) for item in logs],
                }
            )
        print(
            json.dumps(
                {
                    "evidence": "Opentrons Python simulator only; not Matterix, SiLA wire or physical hardware",
                    "opentrons_version": opentrons.__version__,
                    "results": results,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
