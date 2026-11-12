import type { LayoutPreview, Motion, TimelineStep } from "./instrumentTypes";

/** Workflow time in seconds: the end of the last step. */
export function duration(timeline: TimelineStep[]) {
  return timeline.length ? timeline[timeline.length - 1].end_s : 0;
}

/** The step running at `clock`: the last one that has started. */
export function stepAt(timeline: TimelineStep[], clock: number) {
  let found = 0;
  timeline.forEach((step, i) => {
    if (step.start_s <= clock) found = i;
  });
  return found;
}

/** Sample and consumable state at `clock`: as the last finished step left it. */
export function stateAt(timeline: TimelineStep[], clock: number) {
  const done = timeline.filter((step) => step.end_s <= clock + 1e-9);
  return done.length ? done[done.length - 1] : null;
}

export type ArmMoment = {
  motion: Motion;
  /** Index into the motion's frames and joints. */
  frame: number;
  /** Whether the arm is moving now, rather than resting between transfers. */
  moving: boolean;
};

/** Where the arm is at `clock`: along a transfer, or resting where the last one left it. */
export function armAt(preview: LayoutPreview, clock: number): ArmMoment | null {
  const timeline = preview.timeline ?? [];
  const transfers = timeline.flatMap((step) => {
    const motion = preview.motions.find((m) => m.step === step.step);
    return motion?.frames.length ? [{ step, motion }] : [];
  });
  if (!transfers.length) return null;
  const active = transfers.find(
    ({ step }) => step.start_s <= clock && clock < step.end_s,
  );
  if (active) {
    const { step, motion } = active;
    const part = (clock - step.start_s) / (step.end_s - step.start_s || 1);
    const progress = motion.profile?.progress;
    const frame = progress
      ? Math.max(
          0,
          progress.findIndex((p) => p >= part),
        )
      : Math.round(part * (motion.frames.length - 1));
    return { motion, frame, moving: true };
  }
  const before = transfers.filter(({ step }) => step.end_s <= clock);
  if (before.length) {
    const { motion } = before[before.length - 1];
    return { motion, frame: motion.frames.length - 1, moving: false };
  }
  return { motion: transfers[0].motion, frame: 0, moving: false };
}
