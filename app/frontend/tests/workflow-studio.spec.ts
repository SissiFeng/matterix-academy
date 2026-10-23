import { expect, test } from "@playwright/test";
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

async function design(
  page: Page,
  instrument: "Flex" | "OT-2",
  starter = "Transfer",
) {
  await page
    .getByRole("button", { name: "Meet the instruments", exact: true })
    .click();
  const stories = page.getByTestId("instrument-stories");
  await stories
    .getByRole("button", { name: `Opentrons ${instrument}`, exact: true })
    .click();
  if (starter === "blank") {
    await stories
      .getByRole("button", { name: "Start with a blank deck", exact: true })
      .click();
  } else {
    await stories.getByRole("button", { name: starter, exact: true }).click();
    await stories
      .getByRole("button", { name: "Use this workflow", exact: true })
      .click();
  }
  await expect(page.getByTestId("workflow-studio")).toHaveAttribute(
    "data-instrument",
    instrument === "Flex" ? "flex" : "ot2",
  );
  await expect(
    page.getByRole("heading", { name: "Workflow studio." }),
  ).toBeVisible();
}

async function save(page: Page) {
  await page
    .getByRole("button", { name: "Save workflow", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Save workflow", exact: true }),
  ).toBeDisabled();
  await expect(page.getByLabel("Workflow name")).toBeEnabled();
}

async function finish(page: Page) {
  await page
    .getByRole("button", { name: "Run teaching simulation", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Teaching model checks" }),
  ).toBeVisible({ timeout: 25000 });
  await expect(
    page.getByText("Every workflow step completed in the teaching model", {
      exact: true,
    }),
  ).toBeVisible();
}

test("Flex story opens an editable workflow; edits, deck, refresh, reset and a second run persist", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await onboard(page);
  await design(page, "Flex");
  await page.getByLabel("Workflow name").fill("My first custom transfer");
  await page.getByLabel("Step 2 volume", { exact: true }).fill("75");
  await page.getByLabel("Step 3 volume", { exact: true }).fill("75");
  await page
    .getByRole("button", { name: "Duplicate step 4", exact: true })
    .click();
  await expect(page.getByLabel("Step 5 action", { exact: true })).toHaveValue(
    "drop",
  );
  await page
    .getByRole("button", { name: "Delete step 5", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Move step 3 up", exact: true })
    .click();
  await expect(page.getByLabel("Step 2 action", { exact: true })).toHaveValue(
    "dispense",
  );
  await page
    .getByRole("button", { name: "Move step 2 down", exact: true })
    .click();
  await page.getByLabel("Labware to move").selectOption("tips");
  await page
    .getByRole("button", { name: "Slot C1: empty", exact: true })
    .click();
  await save(page);
  await page.reload();
  await expect(page.getByLabel("Workflow name")).toHaveValue(
    "My first custom transfer",
  );
  await expect(
    page.getByRole("button", { name: "Slot C1: Tip rack", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Step 2 volume", { exact: true })).toHaveValue(
    "75",
  );
  await finish(page);
  await expect(page.getByTestId("liquid-A1")).toContainText("75 µL");
  await expect(page.getByTestId("liquid-stock")).toContainText("925 µL");
  await expect(
    page.getByText("Your design has no prescribed dilution target.", {
      exact: false,
    }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Reset & edit", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Reset & edit", exact: true }).click();
  await expect(
    page.getByText("Earlier attempts", { exact: false }),
  ).toBeVisible();
  await expect(page.getByTestId("liquid-A1")).toContainText("0 µL");
  await finish(page);
  await expect(page.getByTestId("liquid-A1")).toContainText("75 µL");
  expect(errors).toEqual([]);
});

test("OT-2 distribution uses its own deck and recovers a paused run after refresh", async ({
  page,
}) => {
  await onboard(page);
  await design(page, "OT-2", "Distribute");
  const deck = page.getByTestId("studio-deck");
  await expect(deck.getByRole("button")).toHaveCount(12);
  expect(
    await deck
      .getByRole("button")
      .evaluateAll((buttons) =>
        buttons.map(
          (button) => button.getAttribute("aria-label")?.split(":")[0],
        ),
      ),
  ).toEqual([
    "Slot 10",
    "Slot 11",
    "Slot 12",
    "Slot 7",
    "Slot 8",
    "Slot 9",
    "Slot 4",
    "Slot 5",
    "Slot 6",
    "Slot 1",
    "Slot 2",
    "Slot 3",
  ]);
  await expect(
    page.getByRole("button", { name: "Slot 12: Fixed waste", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Advance one step", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Resume simulation", exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByText("Tip attached", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Resume simulation", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Teaching model checks" }),
  ).toBeVisible({ timeout: 15000 });
  for (const well of ["A1", "A2", "A3"])
    await expect(page.getByTestId(`liquid-${well}`)).toContainText("80 µL");
  await expect(page.getByTestId("liquid-stock")).toContainText("760 µL");
  await expect(
    page.getByText("Synthetic teaching model", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("You reached the learning goal.", { exact: true }),
  ).toHaveCount(0);
});

test("a blank OT-2 draft saves without steps and grows into a student-designed workflow", async ({
  page,
}) => {
  await onboard(page);
  await design(page, "OT-2", "blank");
  await expect(
    page.getByRole("button", { name: "Run teaching simulation", exact: true }),
  ).toBeDisabled();
  await page.getByLabel("Workflow name").fill("My blank canvas");
  await save(page);
  await page.reload();
  await expect(page.getByLabel("Workflow name")).toHaveValue("My blank canvas");
  // A saved empty draft still has a learner's name and may have a custom deck.
  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByRole("button", { name: "Load starter", exact: true }).click();
  await expect(page.getByLabel("Workflow name")).toHaveValue("My blank canvas");
  // Protect unsaved edits too, even before the first block is added.
  await page.getByLabel("Workflow name").fill("My still-empty design");
  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByRole("button", { name: "Load starter", exact: true }).click();
  await expect(page.getByLabel("Workflow name")).toHaveValue(
    "My still-empty design",
  );
  await expect(
    page.getByRole("heading", { name: "Your idea starts here." }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Add your first block", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Add aspirate block", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Add dispense block", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Add discard tip block", exact: true })
    .click();
  await page.getByLabel("Step 3 well", { exact: true }).selectOption("A3");
  await page.getByText("Starting liquids", { exact: false }).click();
  await page.getByLabel("Starting stock volume", { exact: true }).fill("500");
  await page.getByLabel("Starting diluent volume", { exact: true }).fill("50");
  await finish(page);
  await expect(page.getByTestId("liquid-A3")).toContainText("150 µL");
  await expect(page.getByTestId("liquid-A3")).toContainText("66.67% stock");
  await expect(page.getByTestId("liquid-stock")).toContainText("400 µL");
});

test("an invalid freeform sequence gives a model hint and can be corrected", async ({
  page,
}) => {
  await onboard(page);
  await design(page, "Flex");
  await page
    .getByRole("button", { name: "Delete step 1", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Run teaching simulation", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Step 1: The pipette has no tip." }),
  ).toBeVisible();
  await expect(
    page.getByText("Add a pick-up step before transferring liquid.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByTestId("liquid-stock")).toContainText("1,000 µL");
  await page.getByRole("button", { name: "Reset & edit", exact: true }).click();
  await page
    .getByRole("button", { name: "Add pick up tip block", exact: true })
    .click();
  for (const step of [4, 3, 2])
    await page
      .getByRole("button", { name: `Move step ${step} up`, exact: true })
      .click();
  await finish(page);
  await expect(page.getByTestId("liquid-A1")).toContainText("100 µL");
  await page.getByText("Earlier attempts", { exact: false }).click();
  await expect(
    page.getByText("Attempt 1 · 0 steps · faulted — The pipette has no tip.", {
      exact: true,
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Runs", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Previous attempts" }),
  ).toBeVisible();
  await expect(
    page.getByText("Sequence incomplete", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Goal not reached", { exact: true })).toHaveCount(
    0,
  );
});

test("starter replacement, unsaved navigation and keyboard controls protect a draft", async ({
  page,
}) => {
  await onboard(page);
  await design(page, "Flex");
  await page.getByLabel("Workflow name").fill("An unfinished idea");
  page.once("dialog", (dialog) => dialog.dismiss());
  await page
    .getByRole("button", { name: "Meet the instruments", exact: true })
    .click();
  await expect(page.getByLabel("Workflow name")).toHaveValue(
    "An unfinished idea",
  );
  await page.getByLabel("Workflow starter").selectOption("dilution");
  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByRole("button", { name: "Load starter", exact: true }).click();
  await expect(page.getByLabel("Step 5 action", { exact: true })).toHaveCount(
    0,
  );
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Load starter", exact: true }).click();
  await expect(page.getByLabel("Step 12 action", { exact: true })).toHaveValue(
    "drop",
  );
  const move = page.getByRole("button", {
    name: "Move step 3 up",
    exact: true,
  });
  await move.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("Step 2 action", { exact: true })).toHaveValue(
    "dispense",
  );
  await page
    .getByRole("button", { name: "Move step 2 down", exact: true })
    .click();
  await save(page);
  await finish(page);
  await expect(page.getByTestId("liquid-A3")).toContainText("12.5% stock");
});

test("mobile stories and studio controls fit the viewport in both themes", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce", colorScheme: "dark" });
  await onboard(page);
  await design(page, "OT-2");
  await page
    .getByRole("button", { name: "Preview & run", exact: true })
    .click();
  await expect(
    page.getByRole("region", {
      name: "Teaching simulation controls",
      exact: true,
    }),
  ).toBeFocused();
  await page.getByRole("button", { name: "Edit blocks", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "Workflow blocks", exact: true }),
  ).toBeFocused();
  await expect(
    page.getByRole("button", { name: "Run teaching simulation", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page
    .getByRole("button", { name: "Add aspirate block", exact: true })
    .click();
  await expect(page.getByLabel("Step 5 volume", { exact: true })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.emulateMedia({ colorScheme: "light" });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("a stale editor reloads the saved version instead of overwriting a newer workflow", async ({
  page,
}) => {
  await onboard(page);
  await design(page, "Flex");
  const id = page.url().split("/lab/")[1];
  const loaded = await page.request.get(`/api/sessions/${id}`);
  expect(loaded.ok()).toBe(true);
  const original = await loaded.json();
  const updated = await page.request.put(`/api/sessions/${id}`, {
    data: {
      version: original.version,
      experiment: { ...original.experiment, title: "Saved in another window" },
    },
  });
  expect(updated.ok()).toBe(true);
  await page.getByLabel("Workflow name").fill("An older local draft");
  await page
    .getByRole("button", { name: "Save workflow", exact: true })
    .click();
  await expect(page.getByLabel("Workflow name")).toHaveValue(
    "Saved in another window",
  );
  await expect(
    page.getByRole("button", { name: "Run teaching simulation", exact: true }),
  ).toBeEnabled();
  const persisted = await page.request.get(`/api/sessions/${id}`);
  expect((await persisted.json()).experiment.title).toBe(
    "Saved in another window",
  );
});
