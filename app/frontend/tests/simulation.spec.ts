import { expect, test, type Page } from "@playwright/test";

async function enter(page: Page) {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Sim learner");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page
    .getByRole("button", { name: "Simulation lab", exact: true })
    .click();
}

test("unqualified native lab displays no fabricated video, progress or amounts", async ({
  page,
}) => {
  await enter(page);
  await expect(
    page.getByRole("heading", { name: "Four sources. One mixture." }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Run mixing experiment" }),
  ).toBeDisabled();
  await expect(page.getByText("No native state received")).toBeVisible();
  await expect(page.locator("video")).toHaveJSProperty("srcObject", null);
  await expect(page.getByText("Vial 2 → well A1")).toBeVisible();
  await expect(page.getByText("Vial 6 → well A1")).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Four sources. One mixture." }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("saved native fixture displays matching quantities and survives refresh without another run", async ({
  page,
}) => {
  // This is explicitly a UI fixture, not Isaac or AWS streaming acceptance.
  await enter(page);
  const sessionResponse = await page.request.post("/api/simulations", {
    data: { session_id: crypto.randomUUID(), seed: 42 },
  });
  const session = await sessionResponse.json();
  const runId = crypto.randomUUID();
  let submitted = 0;
  await page.route("**/api/runs", async (route) => {
    submitted++;
    await route.abort();
  });
  await page.route(`**/api/sessions/${session.id}/remote-run`, async (route) =>
    route.fulfill({
      json: {
        run_id: runId,
        session_id: session.id,
        version: 5,
        status: "completed",
        plan_hash: "a".repeat(64),
        completed_steps: 5,
        total_steps: 5,
        stale_seconds: 0,
        cleanup: { reset_verified: true },
        snapshot: {
          session_id: crypto.randomUUID(),
          run_id: runId,
          plan_hash: "a".repeat(64),
          sequence: 8,
          engine_version: "fixture-code",
          asset_version: "fixture-assets",
          observed_at: "2026-10-01T15:00:00Z",
          steps: Array.from({ length: 5 }, (_, index) => ({
            index,
            status: "completed",
          })),
          native_state: {
            revision: 9,
            simulation_tick: 2000,
            observed_at: "2026-10-01T15:00:00Z",
            pipette_volume_ul: 0,
            tip_attached: false,
            well_volumes_ul: { stock: null, A1: 40, A2: null, A3: null },
            mixing: {
              source_volumes_ul: [
                1490, 1490, 1490, 1500, 1500, 1490, 1500, 1500,
              ],
              mixture_components_ul: [10, 10, 10, 0, 0, 10, 0, 0],
              source_order: [1, 0, 5, 2],
              lid_parked: true,
              lid_attached: false,
              active_tip: null,
              tips_used: ["A1", "A2", "A3", "A4"],
              tips_discarded: ["A1", "A2", "A3", "A4"],
              joint_positions: [0, 0, 0, 0, 0, 0, 0],
              native_action_index: 86,
              native_action_count: 86,
              native_action: "Workflow finished",
            },
          },
        },
      },
    }),
  );
  await page.goto(`/#/sim/${session.id}`);
  await expect(page.getByText("40 µL", { exact: true })).toBeVisible();
  await expect(page.getByText("4 / 4", { exact: true })).toBeVisible();
  await expect(page.getByText("Reset verified · lab released")).toBeVisible();
  await page
    .getByRole("button", { name: "Simulation lab", exact: true })
    .click();
  await expect(page).toHaveURL(new RegExp(`/#/sim/${session.id}$`));
  await page.reload();
  await expect(page.getByText("40 µL", { exact: true })).toBeVisible();
  expect(submitted).toBe(0);
});

test("recovering a selected experiment cannot submit a new one while state is unresolved", async ({
  page,
}) => {
  await enter(page);
  const created = await page.request.post("/api/simulations", {
    data: { session_id: crypto.randomUUID(), seed: 42 },
  });
  const session = await created.json();
  await page.route("**/api/simulations", async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      response,
      json: { ...(await response.json()), enabled: true },
    });
  });
  let release!: () => void;
  const delayed = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(`**/api/sessions/${session.id}`, async (route) => {
    await delayed;
    await route.continue();
  });
  await page.goto(`/#/sim/${session.id}`);
  await expect(
    page.getByRole("button", { name: "Run mixing experiment" }),
  ).toBeDisabled();
  release();
  await expect(
    page.getByRole("button", { name: "Run mixing experiment" }),
  ).toBeEnabled();
});

test("first visit can request a GPU before mixing execution is qualified", async ({
  page,
}) => {
  let created = 0;
  let requested = 0;
  let runs = 0;
  let receipt: { request_id: string; expires_at: number } | null = null;
  await page.route("**/api/simulations", async (route) => {
    if (route.request().method() === "POST") created += 1;
    await route.continue();
  });
  await page.route("**/api/sessions/*/gpu-request", (route) => {
    if (route.request().method() === "POST") {
      requested += 1;
      const data = route.request().postDataJSON();
      expect(data.expected_version).toBe(1);
      receipt = {
        request_id: data.request_id,
        expires_at: Date.now() / 1000 + 3600,
      };
    }
    return route.fulfill({
      status: route.request().method() === "POST" ? 202 : 200,
      json: {
        configured: true,
        active: !!receipt,
        request: receipt,
        gpu: {
          state: "starting",
          message: "Starting the GPU for digital twin access.",
          idle_seconds: 3600,
          retry_at: null,
          updated_at: null,
        },
      },
    });
  });
  await page.route("**/api/runs", (route) => {
    runs += 1;
    return route.abort();
  });
  await enter(page);
  await expect(
    page.getByRole("button", { name: "Run mixing experiment", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Request GPU", exact: true }).click();
  await expect(page).toHaveURL(/#\/sim\/[a-f0-9-]+$/);
  await expect(
    page.getByRole("button", { name: "GPU requested", exact: true }),
  ).toBeDisabled();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "GPU requested", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Run mixing experiment", exact: true }),
  ).toBeDisabled();
  expect(created).toBe(1);
  expect(requested).toBe(1);
  expect(runs).toBe(0);
});
