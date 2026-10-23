# Instrument introductions and Workflow Studio

The learner entry starts with Opentrons Flex and OT-2 illustrations. Each has a
36-second introduction with chapters, a scrubber, play/pause and replay. Students
can explore without signing in. Reduced-motion preferences keep the illustrations
still and leave chapter navigation available; hidden tabs pause playback.

## Learner journey

1. Choose **Opentrons Flex** or **Opentrons OT-2**, then play the introduction.
2. Explore **Transfer**, **Distribute** or **Serial dilution**. Select **Use this
   workflow** or **Start with a blank deck**. A public-page choice survives refresh
   and the sign-in redirect; it is consumed once after account onboarding.
3. In **Workflow studio**, rename the design, arrange labware and combine blocks:
   pick up a tip, aspirate, dispense and discard. Reorder, duplicate or remove
   blocks; edit volumes, wells and initial liquid amounts. The blank starter can
   be saved with no steps, but needs a step before it can run.
4. **Save workflow**, or run directly to save and execute the draft. Watch the
   highlighted deck, step sequence and liquid amounts. Pause or advance one step
   at a time. Refresh restores saved state; a running session waits for the learner
   to resume automatic advancement in the reopened browser.
5. Inspect **Teaching model checks** and observations. Reset to edit and try again.
   Earlier attempt summaries remain available. **Runs** also opens saved designs.

The signed-in **Overview** repeats the introductions; **Meet the instruments** in
Learn & Explore opens them directly. Existing lessons, workcell setup and native
simulation entry points remain accessible.

## Model and evidence boundary

Both instruments use the same bounded bookkeeping model: one 300 µL pipette,
stock and three destination wells (A1–A3), 1500 µL container capacities, 0–64 steps,
instantaneous ideal mixing, fresh-tip tracking and explicit waste accounting.
This is a teaching abstraction, not a complete instrument configuration.

Flex starts with tips B1, stock D1, samples D2 and fixed waste D3. OT-2 starts with
tips 4, stock 1, samples 2 and fixed trash 12. OT-2 rows are shown back to front:
10–12, 7–9, 4–6, 1–3. Movable items can swap; waste cannot move.

Transfer moves 100 µL into A1. Distribution aspirates 240 µL and dispenses 80 µL
into each of A1–A3. Serial dilution begins with 100 µL buffer in each target and
passes 100 µL through the three wells using a fresh tip per transfer; the model
mixes instantly. A blank workflow starts with empty targets.

Free designs have no prescribed concentration target. Completion checks account
for every action, total volume/tracer including waste, container bounds, and an
empty pipette with its tip discarded. Passing these checks does not award a fixed
lesson goal or establish experimental success. The animations are authored SVG
illustrations; they are not camera footage or Isaac output. This feature cannot
submit sandbox plans to the native worker or operate a robot.

Instrument references: [Flex introduction](https://docs.opentrons.com/flex/introduction/),
[OT-2 robot description](https://docs.opentrons.com/ot-2/system-description/robot/),
[deck slot conventions](https://docs.opentrons.com/python-api/deck-slots/).

## Integration contract

`course_id: workflow-sandbox` and `instrument: flex | ot2` identify new designs.
The instrument and course cannot change after creation. All edits and controls
retain expected-version checks and existing subject-scoped storage. A stale
editor reloads the authoritative saved version with a visible conflict message.
Existing Flex course payloads omit the new instrument field, preserving native
adapter schema and recipe hashes. Sandbox assessment carries `scope: model-checks`.

No Matterix binaries, new runtime dependencies, GPU resources, identity settings
or native qualification gates are changed. Publishing follows the existing
application-only main deployment workflow.

## Acceptance

Run `bash scripts/build-lambda.sh`, `bash scripts/verify.sh` and
`npm --prefix app/frontend run test:e2e`. The backend studio tests cover both
storage implementations, invalid layouts, ownership, expected versions, reset,
conservation, faults, legacy hashes and native submission rejection. Browser
journeys cover public playback and reduced motion; selection through local
onboarding; both instruments; block editing; blank designs; save/refresh;
step/pause/reset/second run; faults; stale edits; and mobile light/dark layouts.

Browser automation uses explicit loopback guest access. It does not replace the
real-account Cognito acceptance deferred by the user, or GPU/hardware acceptance.
