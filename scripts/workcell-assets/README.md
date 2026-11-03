# Workcell case assets

The files in `app/frontend/public/workcell-assets/` are registered in
`app/backend/academy/workcell_assets.json` with their SHA-256, size, licence and source commit.
`app/backend/tests/test_workcell_assets.py` fails if a served file is missing from the registry or
its bytes change. After regenerating a file, update its `sha256` and `size_bytes` in the registry.

| File | Built from | Script |
| --- | --- | --- |
| `ur5e_2f140.glb` | `UniversalRobots/Universal_Robots_ROS2_Description` (UR5e visual meshes and offsets) and `PickNikRobotics/ros2_robotiq_gripper` (2F-140) | `build_ur5e_glb.py <ur_description> <ros2_robotiq_gripper> <out.glb>` |
| `flex.glb`, `flex_meta.json` | MuJoCo model written by `SmartisanNaive/MOSS-Lab` `flex3d` with a 1000 µL pipette, `opentrons_flex_96_tiprack_1000ul` in A1 and `nest_12_reservoir_15ml` in B1 | `mjcf_to_glb.py <flex.xml> <out.glb> <out_meta.json>` |
| `labware.json`, `decks.json` | `Opentrons/opentrons` `shared-data` labware and deck definitions | Wells, footprints, tip lengths, cutouts and addressable areas copied verbatim |

`mjcf_to_glb.py` reads the generated MJCF and its mesh folder with MuJoCo only; it does not import
MOSS-Lab code. Generate the MJCF in a separate checkout of that project. Static Flex bodies are baked
in the deck frame; the bridge, carriage, pipette and gripper stay body-local so the page can slide
them. Sample racks are omitted from the Flex file because the page draws them from the labware
definitions and moves them between instruments.

The OT-2 and the balance are drawn in code (`app/frontend/src/workcellCase/ot2Model.ts`,
`balanceModel.ts`) and registered as procedural assets. None of these files come from the Matterix
assets repository.

Requirements for the scripts: Python 3.12 with `numpy`, `trimesh`, `pycollada`, `fast-simplification`
and `mujoco`.
