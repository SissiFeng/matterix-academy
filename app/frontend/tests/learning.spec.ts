import { test, expect, type Page } from "@playwright/test";

async function startLesson(page: Page) {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Lin");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page
    .getByRole("button", { name: "Start learning Flex", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /Move 100 µL/ }),
  ).toBeVisible();
}

async function tour(page: Page) {
  for (const name of [
    "Pipette",
    "Tip rack",
    "Source container",
    "Target plate",
    "Waste chute",
  ]) {
    await page.getByRole("button", { name, exact: true }).click();
    await expect(
      page.getByText(
        `Explored ${["Pipette", "Tip rack", "Source container", "Target plate", "Waste chute"].indexOf(name) + 1} / 5 objects.`,
        { exact: false },
      ),
    ).toBeVisible();
  }
  await page.getByLabel("A well in the plate", { exact: true }).click();
  await page
    .getByRole("button", { name: "Prepare the experiment", exact: true })
    .click();
}

async function prepare(page: Page) {
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
}

async function predict(page: Page, volume: number) {
  await page.getByLabel("Source volume remaining").fill(String(1000 - volume));
  await page.getByLabel("Volume in the tip").fill(String(volume));
  await page.getByLabel("Volume in target well A1").fill("0");
  await page
    .getByRole("button", { name: "Check my prediction", exact: true })
    .click();
  await expect(
    page.getByText(
      "Correct. Aspiration draws liquid into the tip; the target well is still empty.",
    ),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Start practicing", exact: true })
    .click();
}

test("novice learns equipment, predicts, executes each step, reflects and retries 50 uL", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await startLesson(page);
  await expect(
    page.getByRole("button", { name: "Prepare the experiment", exact: true }),
  ).toBeDisabled();
  await tour(page);
  await expect(
    page.getByLabel("Target plate slot").locator("option[value='D3']"),
  ).toHaveCount(0);
  await prepare(page);
  await page.getByLabel("Source volume remaining").fill("900");
  await page.getByLabel("Volume in the tip").fill("0");
  await page.getByLabel("Volume in target well A1").fill("100");
  await page
    .getByRole("button", { name: "Check my prediction", exact: true })
    .click();
  await expect(page.getByText(/Think again: aspiration/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Start practicing", exact: true }),
  ).toBeDisabled();
  await predict(page, 100);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Pick up a fresh tip", exact: true }),
  ).toBeVisible();
  for (const next of [
    "Aspirate 100 µL",
    "Dispense 100 µL",
    "Discard the used tip",
    "Transfer complete. Now explain it.",
  ]) {
    await page
      .getByRole("button", { name: "Run next step", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: next, exact: true }),
    ).toBeVisible();
  }
  await page
    .getByRole("button", {
      name: "Explain the result and try again",
      exact: true,
    })
    .click();
  await page
    .getByLabel("Directly from the source into the target well", {
      exact: true,
    })
    .click();
  await expect(
    page.getByText(/The target is still empty after aspiration/),
  ).toBeVisible();
  await page
    .getByLabel("From the source into the tip; the target is still empty", {
      exact: true,
    })
    .click();
  await expect(
    page.getByText("Practice and understanding complete", { exact: true }),
  ).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page
    .getByRole("button", { name: "Try a 50 µL transfer", exact: true })
    .click();
  await expect(page.getByRole("heading", { name: /Move 50 µL/ })).toBeVisible();
  await prepare(page);
  await predict(page, 50);
  await page
    .getByRole("button", { name: "Run continuously", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Transfer complete. Now explain it.",
      exact: true,
    }),
  ).toBeVisible({ timeout: 15000 });
  expect(errors).toEqual([]);
});

test("remote remains honest and lesson fits a phone", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await startLesson(page);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: /Remote 3D/ }).click();
  await expect(
    page.getByText(
      "The Ubuntu simulation connection is not configured yet. Lessons and teaching exercises are still available.",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", {
      name: "Live 3D simulation is not connected yet",
    }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "Check connection again" }).click();
  await expect(
    page.getByText(
      "The Ubuntu simulation connection is not configured yet. Lessons and teaching exercises are still available.",
    ),
  ).toBeVisible();
});

test("unfinished prediction is protected and changing deck invalidates readiness", async ({
  page,
}) => {
  await startLesson(page);
  await tour(page);
  await prepare(page);
  await page.getByLabel("Source volume remaining").fill("900");
  page.once("dialog", (dialog) => dialog.dismiss());
  await page
    .getByRole("button", { name: "Back to courses", exact: true })
    .click();
  await expect(page.getByLabel("Source volume remaining")).toHaveValue("900");
  await predict(page, 100);
  await page.getByRole("button", { name: /Predict changes Think/ }).click();
  await page.getByLabel("Source volume remaining").fill("0");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: /Prepare the deck Check/ }).click();
  await page.getByRole("button", { name: /Predict changes Think/ }).click();
  await expect(page.getByLabel("Source volume remaining")).toHaveValue("900");
  await page.getByRole("button", { name: /Prepare the deck Check/ }).click();
  await page.getByLabel("Tip rack slot").selectOption("C1");
  await expect(
    page.getByRole("checkbox", { name: /Pipette and tips/ }),
  ).not.toBeChecked();
  await page.getByRole("button", { name: /Run step by step Observe/ }).click();
  await expect(
    page.getByRole("button", { name: "Run next step", exact: true }),
  ).toBeDisabled();
});

test("a correct prediction is recognized even before other prerequisites", async ({
  page,
}) => {
  await startLesson(page);
  await page.getByRole("button", { name: /Predict changes Think/ }).click();
  await page.getByLabel("Source volume remaining").fill("900");
  await page.getByLabel("Volume in the tip").fill("100");
  await page.getByLabel("Volume in target well A1").fill("0");
  await page
    .getByRole("button", { name: "Check my prediction", exact: true })
    .click();
  await expect(
    page.getByText(
      "Correct. Aspiration draws liquid into the tip; the target well is still empty.",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Start practicing", exact: true }),
  ).toBeDisabled();
});

test("a lost step response reloads its saved result without replaying it", async ({
  page,
}) => {
  await startLesson(page);
  await tour(page);
  await prepare(page);
  await predict(page, 100);
  let sent = 0;
  await page.route(
    "**/api/sessions/*/advance",
    async (route) => {
      sent += 1;
      // The server commits the step, but the browser loses its response.
      await route.fetch();
      await route.abort("failed");
    },
    { times: 1 },
  );
  await page
    .getByRole("button", { name: "Run next step", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Aspirate 100 µL", exact: true }),
  ).toBeVisible();
  expect(sent).toBe(1);
  await page
    .getByRole("button", { name: "Run next step", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Dispense 100 µL", exact: true }),
  ).toBeVisible();
});
