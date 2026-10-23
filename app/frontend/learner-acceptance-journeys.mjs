// Shared by live Cognito acceptance and local real-app journey regression.
import assert from "node:assert/strict";
import { expect } from "@playwright/test";
import { completedTeaching } from "./learner-acceptance-helpers.mjs";

export async function courseJourney(actor, { read, report }) {
  const page = actor.page;
  await page.getByRole("button", { name: "Learning lab", exact: true }).click();
  await page
    .getByRole("button", { name: "Open workflow judgment course" })
    .click();
  for (const text of [
    "The source cannot",
    "An explicit mixing",
    "A teaching pass",
  ])
    await page.getByRole("checkbox", { name: new RegExp(text) }).check();
  await page.getByRole("button", { name: "Check the gaps" }).click();
  await page.getByLabel("Starting source volume (µL)").fill("100");
  await page.getByLabel("Mixing approach").selectOption("ideal");
  await page.getByRole("button", { name: "Save repaired plan" }).click();
  await expect(
    page.getByRole("button", { name: "Run synthetic trial" }),
  ).toBeEnabled();
  const saved = await read(actor, "/api/workflow-course");
  assert.equal(saved.phase, "practice");
  const mutations = actor.mutations;
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Run synthetic trial" }),
  ).toBeEnabled();
  assert.deepEqual(await read(actor, "/api/workflow-course"), saved);
  assert.equal(
    actor.mutations,
    mutations,
    "Refresh must not replay a course command.",
  );
  report.checks.course_refresh_no_replay = true;
  await page.getByRole("button", { name: "Run synthetic trial" }).click();
  await expect(
    page.getByRole("heading", { name: "Synthetic trial · 12 actions" }),
  ).toBeVisible();
  await page
    .getByLabel("Read the original command record without replaying it")
    .check();
  await page.getByRole("button", { name: "Check recovery decision" }).click();
  await page
    .getByLabel(
      "The repaired plan passed synthetic checks; physical readiness is unverified",
    )
    .check();
  await page
    .getByLabel("Explain your evidence and its limits")
    .fill(
      "Synthetic bookkeeping passed. Physical execution, calibration and chemical outcomes remain unverified; read the original record before retrying.",
    );
  await page.getByRole("button", { name: "Submit conclusion" }).click();
  await expect(
    page.getByRole("heading", { name: "Workflow judgment complete" }),
  ).toBeVisible();
  const completed = await read(actor, "/api/workflow-course");
  assert.equal(completed.completed, true);
  assert.equal(completed.evidence, "synthetic");
  assert.equal(completed.trial.steps, 12);
  assert.equal(completed.trial.assessment.passed, true);
  report.checks.course_completion = true;
  return completed;
}

export async function dilutionJourney(actor, { read, report, runId }) {
  const page = actor.page;
  await page.getByRole("button", { name: "Learning lab", exact: true }).click();
  await page
    .getByRole("button", { name: "Start an experiment", exact: true })
    .click();
  await page
    .getByLabel("Experiment title")
    .fill(`Acceptance ${runId.slice(0, 8)} ${actor.label}`);
  await page.getByRole("button", { name: "Tip rack B1" }).click();
  await page.getByRole("button", { name: "C1: empty" }).click();
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Save changes", exact: true }),
  ).toBeDisabled();
  const id = new URL(page.url()).hash.split("/").at(-1);
  const endpoint = `/api/sessions/${id}`;
  const saved = await read(actor, endpoint);
  assert.equal(saved.experiment.layout.tips, "C1");
  const mutations = actor.mutations;
  await page.reload();
  await expect(
    page.getByRole("button", { name: "C1: Tip rack" }),
  ).toBeVisible();
  assert.equal(actor.mutations, mutations);
  assert.deepEqual(await read(actor, endpoint), saved);
  report.checks.dilution_save_refresh = true;
  await page
    .getByRole("button", { name: "Run experiment", exact: true })
    .click();
  await expect(
    page.getByText("You reached the learning goal.", { exact: true }),
  ).toBeVisible({ timeout: 60000 });
  completedTeaching(await read(actor, endpoint), 12);
  await page
    .getByRole("button", { name: "Reset & try again", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Run experiment", exact: true }),
  ).toBeEnabled();
  const reset = await read(actor, endpoint);
  assert.equal(reset.status, "draft");
  assert.equal(reset.cursor, 0);
  await page
    .getByRole("button", { name: "Run experiment", exact: true })
    .click();
  await expect(
    page.getByText("You reached the learning goal.", { exact: true }),
  ).toBeVisible({ timeout: 60000 });
  const completed = await read(actor, endpoint);
  completedTeaching(completed, 12);
  assert.ok(completed.version > reset.version);
  report.checks.dilution_reset_second_run = true;
  report.sessions.push({
    learner: actor.label,
    id,
    evidence: "synthetic",
    steps: 12,
    runs: 2,
  });
  return completed;
}

export async function firstTransferJourney(actor, { read, report }) {
  const page = actor.page;
  await page.getByRole("button", { name: "Learning lab", exact: true }).click();
  await page
    .getByRole("button", { name: "Start learning Flex", exact: true })
    .click();
  for (const [index, name] of [
    "Pipette",
    "Tip rack",
    "Source container",
    "Target plate",
    "Waste chute",
  ].entries()) {
    await page.getByRole("button", { name, exact: true }).click();
    await expect(
      page.getByText(`Explored ${index + 1} / 5 objects.`, { exact: false }),
    ).toBeVisible();
  }
  await page.getByLabel("A well in the plate", { exact: true }).click();
  await page
    .getByRole("button", { name: "Prepare the experiment", exact: true })
    .click();
  for (const name of [
    "Pipette and tips",
    "Labware and positions",
    "Starting volumes",
    "Scope of this exercise",
  ]) {
    const checkbox = page.getByRole("checkbox", { name: new RegExp(name) });
    await checkbox.click();
    await expect(checkbox).toBeChecked();
  }
  await page
    .getByRole("button", { name: "Predict the volumes", exact: true })
    .click();
  await page.getByLabel("Source volume remaining").fill("900");
  await page.getByLabel("Volume in the tip").fill("100");
  await page.getByLabel("Volume in target well A1").fill("0");
  await page
    .getByRole("button", { name: "Check my prediction", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Start practicing", exact: true })
    .click();
  for (const heading of [
    "Aspirate 100 µL",
    "Dispense 100 µL",
    "Discard the used tip",
    "Transfer complete. Now explain it.",
  ]) {
    await page
      .getByRole("button", { name: "Run next step", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: heading, exact: true }),
    ).toBeVisible();
  }
  await page
    .getByRole("button", {
      name: "Explain the result and try again",
      exact: true,
    })
    .click();
  await page
    .getByLabel("From the source into the tip; the target is still empty", {
      exact: true,
    })
    .click();
  await expect(
    page.getByText("Practice and understanding complete", { exact: true }),
  ).toBeVisible();
  const id = new URL(page.url()).hash.split("/").at(-1);
  const saved = await read(actor, `/api/sessions/${id}`);
  completedTeaching(saved, 4);
  assert.equal(saved.lesson_outcome.understanding_demonstrated, true);
  report.checks.first_transfer = true;
  report.sessions.push({
    learner: actor.label,
    id,
    evidence: "synthetic",
    steps: 4,
  });
}
