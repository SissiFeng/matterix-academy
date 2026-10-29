import { test, expect } from "@playwright/test";
import {
  courseJourney,
  dilutionJourney,
  firstTransferJourney,
  type JourneyReport,
} from "../learner-acceptance-journeys.mjs";

test("live acceptance teaching journeys use the real app accessible controls", async ({
  page,
}) => {
  test.setTimeout(120000);
  // Local real backend/UI only. This is selector/journey coverage, never Cognito evidence.
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Acceptance regression");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  const actor = { page, mutations: 0, label: "local-regression" };
  page.on("request", (request) => {
    if (
      new URL(request.url()).pathname.startsWith("/api/") &&
      ["POST", "PUT"].includes(request.method())
    )
      actor.mutations++;
  });
  const report: JourneyReport = { checks: {}, sessions: [] };
  const read = async (_actor: typeof actor, endpoint: string) => {
    const response = await page.request.get(endpoint);
    expect(response.status()).toBe(200);
    return response.json();
  };
  const options = { read, report, runId: "local-selector-regression" };
  await courseJourney(actor, options);
  await dilutionJourney(actor, options);
  await firstTransferJourney(actor, options);
  expect(report.checks).toEqual({
    course_refresh_no_replay: true,
    course_completion: true,
    dilution_save_refresh: true,
    dilution_reset_second_run: true,
    first_transfer: true,
  });
  expect(report.sessions).toHaveLength(2);
});
