import { expect, test, type Page } from "@playwright/test";

async function lesson(page: Page) {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Remote learner");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page
    .getByRole("button", { name: "Start learning Flex", exact: true })
    .click();
  await page.getByRole("button", { name: /Remote 3D/ }).click();
}

test("native execution stays disabled before qualification", async ({
  page,
}) => {
  await lesson(page);
  const panel = page.getByRole("region", { name: "Remote experiment run" });
  await expect(
    panel.getByText(/Remote execution is awaiting Ubuntu qualification/),
  ).toBeVisible();
  await expect(
    panel.getByRole("button", { name: "Run saved experiment in Matterix" }),
  ).toBeDisabled();
  await expect(
    panel.getByText("Awaiting native execution", { exact: true }),
  ).toBeVisible();
});

test("fixture-only snapshot survives disconnect and refresh without synthetic progress", async ({
  page,
}) => {
  let disconnected = false;
  let unknown = false;
  let mutations = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      /\/api\/runs(?:\/|$)/.test(new URL(request.url()).pathname)
    )
      mutations++;
  });
  await page.route("**/api/sessions/*/remote-run", async (route) => {
    if (disconnected) {
      await route.abort();
      return;
    }
    const sessionId = new URL(route.request().url()).pathname.split("/")[3];
    await route.fulfill({
      json: {
        run_id: "00000000-0000-4000-8000-000000000001",
        session_id: sessionId,
        version: unknown ? 3 : 2,
        status: unknown ? "outcome_unknown" : "running",
        evidence: "native",
        completed_steps: 1,
        total_steps: 4,
        stale_seconds: 12,
        supported_controls: [],
        control: null,
        cleanup: null,
        snapshot: {
          observed_at: "2026-10-01T14:00:00Z",
          engine_version: "fixture-only",
          asset_version: "fixture-only",
          steps: [],
          native_state: {
            pipette_volume_ul: null,
            tip_attached: null,
            well_volumes_ul: { stock: null, A1: null },
          },
        },
      },
    });
  });
  await lesson(page);
  const panel = page.getByRole("region", { name: "Remote experiment run" });
  await expect(panel.getByText("1 / 4 actions confirmed")).toBeVisible();
  for (const stage of await page
    .getByRole("navigation", { name: "Lesson stages" })
    .getByRole("button")
    .all()) {
    await expect(stage).toBeDisabled();
  }
  await expect(panel.getByText("Not observed", { exact: true })).toHaveCount(4);
  disconnected = true;
  await panel
    .getByRole("button", { name: "Check connection", exact: true })
    .click();
  await expect(
    panel.getByText("Reconnecting. Showing the last confirmed state."),
  ).toBeVisible();
  await expect(panel.getByText("1 / 4 actions confirmed")).toBeVisible();
  disconnected = false;
  unknown = true;
  await page.reload();
  await page.getByRole("button", { name: /Remote 3D/ }).click();
  await expect(
    panel.getByText("Outcome unknown", { exact: true }),
  ).toBeVisible();
  await expect(
    panel.getByRole("button", { name: "Run saved experiment in Matterix" }),
  ).toBeDisabled();
  expect(mutations).toBe(0);
});
