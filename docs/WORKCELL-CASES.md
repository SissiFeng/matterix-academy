# Multi-device workcell cases

**Onboard → Multi-device case: synthesis workcell** (`#/onboard/case-synthesis-cell`) opens a worked
example of onboarding several devices together: an Opentrons Flex, a UR5e with a Robotiq 2F-140, a
precision balance and an OT-2 on one bench. It complements the single-device wizard on the same page.

## What the case shows

1. **Arm path design.** The UR5e is edited joint by joint (sliders, exact angles or the ring in the
   3D view), positioned with nominal tool-down IK (*Move tool to*) or 1 cm jogs, and recorded as
   waypoints with hold and gripper actions. Every recorded waypoint leaves a dot for joints J2–J6
   and each joint keeps its own trail; the TCP path is coloured by phase.
2. **Workflow.** Flex dispenses solvent and substrate stocks into six 2 mL vials; the OT-2 prepares
   reagent and catalyst aliquots in parallel. The arm takes the vial rack from Flex D2 to the balance
   (weighed while the arm is clear), then to OT-2 slot 2, where the OT-2 adds the reagent mix and
   mixes. A lane chart, the workflow list and the run log follow the same clock.
3. **Play demo** scripts both: it records the default waypoints one by one, then runs the workflow
   with a moving camera and captions.

The chain exports as `ur5e.action-chain/2`, the input of the UR5e connector's
`PrepareActionChainAtSpeed`. Gripper actions stay in waypoint names because the connector has no
gripper command. Timing follows the connector's automatic rule (quintic rest-to-rest estimate,
shared knot tangents, 125 Hz check at the speed cap and twice that in acceleration, 8 ms grid).

## Geometry checks

Every 50 ms of the arm preview is checked for:

- arm link capsules against instrument walls, roofs, front headers, decks, the Flex touchscreen and
  the balance housing;
- finger pads and fingers against those keep-outs, the fixed labware on both decks and the placed
  sample rack;
- the carried rack against the same boxes, with 2 mm allowance so it can rest on a deck or pan.

A waypoint card reports joint-limit, clearance and gripper problems. The workflow blocks the OT-2
synthesis step when the rack never reaches OT-2 slot 2 or arrives rotated 180°.

Design decisions the checks led to:

- The gripper comes down onto the rack from above. The pads open along the line between the
  instruments, so sliding in or out at deck height would drag the rear finger through the rack.
- The pads open only 18 mm wider than the rack, and OT-2 slot 5 (behind slot 2) stays empty: at full
  opening the rear pad entered the neighbouring labware.
- Joint-space interpolation drifts about 13 mm sideways over a 120 mm vertical move, more than the
  9 mm beside the rack. Vertical moves next to an open gripper get a halfway waypoint.
- Inside the OT-2 the approach height is the minimum that clears the 85 mm vials (pads 8 mm above),
  because the wrist otherwise reaches the front header.

## Registered assets

`GET /api/workcell/assets` returns the registry and `GET /api/workcell/cases/{id}` a case with its
resolved assets; both need the usual identity. The page checks each downloaded file against its
registered SHA-256 before building the scene and lists the assets, licences and source commits under
**Registered assets**. See [`scripts/workcell-assets`](../scripts/workcell-assets/README.md) for how
the files were produced.

## Evidence boundary

Everything in the case is a synthetic teaching model: volumes, densities, masses, balance readings,
liquid colours and timings are illustrative. Instrument envelopes are approximate; the Flex model is
photo-informed project geometry and the OT-2 and balance are drawn in code. No connector is called,
no instrument moves and no result is physical evidence.
