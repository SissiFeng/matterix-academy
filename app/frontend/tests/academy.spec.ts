import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";

async function onboard(page: Page) {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "This is my first time" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await expect(
    page.getByRole("heading", { name: "Welcome to the lab, Ada." }),
  ).toBeVisible();
}

test("onboarding, keyboard deck placement, save, dilution, refresh and reset", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await onboard(page);
  await page.getByRole("button", { name: "Start an experiment" }).click();
  await page.getByRole("button", { name: "Tip rack B1" }).click();
  await page.getByRole("button", { name: "C1: empty" }).click();
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "C1: Tip rack" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Run experiment", exact: true })
    .click();
  await expect(
    page.getByText("You reached the learning goal.", { exact: true }),
  ).toBeVisible({ timeout: 25000 });
  await expect(page.getByText("12.5%", { exact: true }).first()).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Reset & try again" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Reset & try again" }).click();
  await expect(
    page.getByRole("button", { name: "Run experiment", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "One step at a time" }).click();
  await expect(
    page.getByRole("button", { name: "Resume experiment" }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("a missing tip gives a useful failure and does not claim Matterix evidence", async ({
  page,
}) => {
  await onboard(page);
  await page.getByRole("button", { name: "Start an experiment" }).click();
  await page.getByRole("button", { name: "Matterix 3D" }).click();
  await expect(
    page.getByRole("heading", { name: "Your 3D lab is not connected yet." }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Back to my experiment" }).click();
  await page.getByRole("button", { name: "Your method" }).click();
  await page
    .getByRole("button", { name: "Delete step 1", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Run experiment", exact: true })
    .click();
  await expect(page.getByText("Step 1: The pipette has no tip.")).toBeVisible();
  await expect(
    page.getByText("Add a pick-up step before transferring liquid."),
  ).toBeVisible();
  await expect(
    page.getByText("Teaching model · simulation only"),
  ).toBeVisible();
});

test("mobile onboarding and workspace have no horizontal overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await onboard(page);
  await page.getByRole("button", { name: "Start an experiment" }).click();
  await expect(
    page.getByRole("button", { name: "Run experiment", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "Your method" }).click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
});

test("unsaved method is protected on sidebar navigation and dialogs support Escape", async ({
  page,
}) => {
  await onboard(page);
  await page.getByRole("button", { name: "Start an experiment" }).click();
  await page.getByLabel("Experiment title").fill("Unfinished idea");
  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByRole("button", { name: "Learning lab", exact: true }).click();
  await expect(page.getByLabel("Experiment title")).toHaveValue(
    "Unfinished idea",
  );
  await page.getByRole("button", { name: "Matterix 3D" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(page.getByRole("button", { name: "Matterix 3D" })).toBeFocused();
});

test("late response from another experiment cannot replace the active workspace", async ({
  page,
}) => {
  await onboard(page);
  await page.getByRole("button", { name: "Start an experiment" }).click();
  const firstUrl = page.url();
  await page.getByLabel("Experiment title").fill("Experiment A");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  // Save is disabled while the PUT is still pending. Wait until it has settled.
  await expect(
    page.getByRole("button", { name: "Run experiment", exact: true }),
  ).toBeEnabled();
  await expect(
    page.getByRole("button", { name: "Save changes", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "My workspace", exact: true }).click();
  await page.getByRole("button", { name: "Start an experiment" }).click();
  await page.getByLabel("Experiment title").fill("Experiment B");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Run experiment", exact: true }),
  ).toBeEnabled();
  await expect(
    page.getByRole("button", { name: "Save changes", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "My workspace", exact: true }).click();
  await page.getByRole("button", { name: /Experiment A/ }).click();
  let release: () => void = () => {};
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  let requested: () => void = () => {};
  const seen = new Promise<void>((resolve) => {
    requested = resolve;
  });
  await page.route("**/api/sessions/*/start", async (route) => {
    const response = await route.fetch();
    requested();
    await pending;
    await route.fulfill({ response });
  });
  await page
    .getByRole("button", { name: "Run experiment", exact: true })
    .click();
  await seen;
  await page.getByRole("button", { name: "My workspace", exact: true }).click();
  await page.getByRole("button", { name: /Experiment B/ }).click();
  release();
  await expect(page.getByLabel("Experiment title")).toHaveValue("Experiment B");
  expect(page.url()).not.toEqual(firstUrl);
  await page.getByRole("button", { name: "One step at a time" }).click();
  await expect(
    page.getByRole("heading", { name: "Experiment B", exact: true }),
  ).toBeVisible();
});
