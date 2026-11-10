import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

async function enter(page: Page) {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
}

async function openPlan(page: Page, actions?: object[]) {
  const created = await page.request.post("/api/sessions", {
    data: { course_id: "workflow-sandbox", ...(actions ? { actions } : {}) },
  });
  expect(created.ok()).toBe(true);
  await page.goto(`/#/lab/${(await created.json()).id}`);
  await page.reload();
  return page.getByRole("region", { name: "On a real Opentrons" });
}

test("a clean workflow passes the Opentrons pre-check and downloads as a protocol", async ({
  page,
}) => {
  await enter(page);
  const check = await openPlan(page);
  await check.getByRole("button", { name: "Check my workflow" }).click();
  await expect(
    check.getByRole("heading", { name: "Opentrons would run every step" }),
  ).toBeVisible();
  const download = page.waitForEvent("download");
  await check.getByRole("button", { name: "Download protocol (.py)" }).click();
  const source = readFileSync((await (await download).path())!, "utf8");
  expect(source).toContain('"robotType": "Flex"');
  expect(source).toContain('pipette.aspirate(100, stock["A1"])');
});

test("the pre-check separates what Opentrons stops from what it lets through", async ({
  page,
}) => {
  await enter(page);
  await page.setViewportSize({ width: 390, height: 844 });
  const check = await openPlan(page, [
    { kind: "pickup" },
    { kind: "aspirate", well: "stock", volume: 2 },
    { kind: "dispense", well: "A1", volume: 50 },
  ]);
  await check.getByRole("button", { name: "Check my workflow" }).click();
  await expect(
    check.getByRole("heading", { name: "Opentrons would stop at 1 step" }),
  ).toBeVisible();
  await expect(
    check.getByText("Step 3 · Dispenses 50 µL when the tip holds 2 µL"),
  ).toBeVisible();
  await expect(
    check.getByRole("heading", {
      name: "Opentrons runs these without a warning",
    }),
  ).toBeVisible();
  await expect(
    check.getByText(/Step 2 · 2 µL is below the 5 µL/),
  ).toBeVisible();
  await expect(
    check.getByRole("button", { name: "Download protocol (.py)" }),
  ).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
