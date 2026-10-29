import { expect, test, type Page, type Route } from "@playwright/test";

async function enter(page: Page) {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
}

async function onboard(page: Page) {
  await page.getByRole("button", { name: "Onboard", exact: true }).click();
  await page.getByLabel("Device name", { exact: true }).fill("Flex 01");
  await page.getByLabel("Workcell name").fill("Liquid handling");
  await page.getByRole("button", { name: "Save and continue" }).click();
  await page.getByRole("radio", { name: /SiLA 2 connector/ }).check();
  await page.getByRole("button", { name: "Save and continue" }).click();
  await page.getByRole("checkbox", { name: /^Pick up tip/ }).check();
  await page.getByRole("button", { name: "Save and continue" }).click();
  await expect(
    page.getByRole("heading", { name: "Pair a teaching twin" }),
  ).toBeVisible();
}

const step = (id: string, action: string) => ({
  operation: { operation_id: id, action },
  sim: null,
  real: null,
  gate: null,
  comparisons: [],
});

const awaiting = {
  run_id: "11111111-2222-3333-4444-555555555555",
  version: 1,
  mode: "sim_first",
  status: "awaiting_approval",
  reason: "",
  requested_as: "learner",
  requested_by: "someone",
  instrument_id: "flex-a",
  steps: [
    step("01-pickup", "pick_up_tip"),
    step("02-drop", "drop_tip"),
    step("03-park", "park"),
  ],
  completed_steps: 0,
  total_steps: 3,
  approval: null,
  created_at: 1793030000,
};

async function linked(page: Page, approvals: unknown[]) {
  // The learner's saved declaration, as an operator link would present it.
  const withInstrument = async (route: Route) => {
    const response = await route.fetch();
    const body = await response.json();
    const link = (device: Record<string, unknown>) => ({
      ...device,
      instrument_id: "flex-a",
    });
    await route.fulfill({
      response,
      json: Array.isArray(body) ? body.map(link) : link(body),
    });
  };
  await page.route("**/api/devices", withInstrument);
  await page.route(/\/api\/devices\/[0-9a-f-]+$/, withInstrument);
  await page.route("**/api/sim2real/status", (route) =>
    route.fulfill({
      json: { pairing_enabled: true, real_enabled: true, operator: true },
    }),
  );
  await page.route("**/api/instruments/flex-a", (route) =>
    route.fulfill({
      json: {
        gateway: { online: true, fault: "", inspected: true, pending: 0 },
      },
    }),
  );
  await page.route("**/api/pair-runs?instrument_id=flex-a", (route) =>
    route.fulfill({
      json: approvals.length
        ? [{ ...awaiting, status: "running", version: 2 }]
        : [awaiting],
    }),
  );
  await page.route(`**/api/pair-runs/${awaiting.run_id}/approve`, (route) => {
    approvals.push(route.request().postDataJSON());
    return route.fulfill({
      json: { ...awaiting, status: "running", version: 2 },
    });
  });
}

test("an operator approves a linked instrument's run only after confirming the site", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const approvals: unknown[] = [];
  await enter(page);
  await onboard(page);
  await linked(page, approvals);
  await page
    .getByRole("navigation", { name: "Workcell navigation" })
    .getByRole("button", { name: "Sim → Real", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "03 / Physical runs · flex-a" }),
  ).toBeVisible();
  await expect(page.getByText("Linked · flex-a")).toBeVisible();
  await expect(
    page.getByText("Gateway online · connector verified"),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Execute on real lab" }),
  ).toHaveCount(0);
  const approve = page.getByRole("button", { name: "Approve physical run" });
  await expect(approve).toBeDisabled();
  await page.getByRole("checkbox", { name: /deck matches this plan/ }).check();
  await page.getByRole("checkbox", { name: /workspace is clear/ }).check();
  await expect(approve).toBeDisabled();
  await page.getByRole("checkbox", { name: /emergency stop/ }).check();
  await page.getByLabel("Approval note").fill("Deck checked against plan");
  await approve.click();
  await expect.poll(() => approvals.length).toBe(1);
  expect(approvals[0]).toEqual({
    expected_version: 1,
    confirmation: {
      deck_matches_plan: true,
      workspace_clear: true,
      emergency_stop_reachable: true,
      note: "Deck checked against plan",
    },
  });
  await expect(page.getByText(/running · 0 \/ 3 steps/)).toBeVisible();
  expect(errors).toEqual([]);
});

test("an unlinked declaration keeps physical execution unavailable and fits a phone", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await enter(page);
  await onboard(page);
  await page
    .getByRole("navigation", { name: "Workcell navigation" })
    .getByRole("button", { name: "Sim → Real", exact: true })
    .click();
  await expect(
    page.getByText(/No physical instrument is linked to this declaration/),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Execute on real lab" }),
  ).toBeDisabled();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
