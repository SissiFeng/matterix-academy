import { expect, test } from "@playwright/test";

// The onboarding case: an orchestrator's workflow file with two plates on each of two
// liquid handlers, an arm that must reach two slots on both, and the handlers apart.
const FILE = {
  draft: {
    roles: [
      {
        key: "ot2",
        name: "Liquid handler A",
        operations: ["load", "mix"],
        vessel: "plate",
        query: "OT-2",
        reach_slots: 2,
      },
      {
        key: "flex",
        name: "Liquid handler B",
        operations: ["load", "mix"],
        vessel: "plate",
        query: "Opentrons Flex",
        reach_slots: 2,
      },
      {
        key: "arm",
        name: "Robot arm",
        operations: ["transfer"],
        vessel: "none",
        query: "robot arm",
        reach_slots: 0,
      },
    ],
    steps: [
      ...[
        ["ot2", "plate-a"],
        ["ot2", "plate-b"],
        ["flex", "plate-c"],
        ["flex", "plate-d"],
      ].map(([role, sample]) => ({
        role,
        operation: "load",
        source_role: "",
        target_role: "",
        value: 200,
        sample,
      })),
      {
        role: "arm",
        operation: "transfer",
        source_role: "ot2",
        target_role: "flex",
        value: 1,
        sample: "plate-a",
      },
    ],
    assumptions: [],
    preferences: [
      {
        kind: "apart",
        role: "ot2",
        other_role: "flex",
        side: "",
        metres: 0.5,
      },
    ],
  },
};

test("an imported workflow file plans a layout that reaches deck slots", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "This is my first time" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page
    .getByRole("button", { name: "Plan a layout", exact: true })
    .click();
  await page.getByRole("tab", { name: "1 · Describe" }).click();

  await page.getByLabel("Workflow file").setInputFiles({
    name: "synthesis-cell.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(FILE)),
  });
  await expect(page.getByText("From synthesis-cell")).toBeVisible();
  const roles = page.getByRole("region", { name: "Instrument roles" });
  await expect(roles.getByText("arm reaches 2 slots")).toHaveCount(2);
  await expect(
    page
      .getByRole("region", { name: "Drafted steps" })
      .getByText("Liquid handler A · Load sample 200 µL · plate-b"),
  ).toBeVisible();
  await expect(
    page
      .getByRole("region", { name: "Layout preferences" })
      .getByText("Liquid handler A at least 0.5 m from Liquid handler B"),
  ).toBeVisible();

  await page.getByRole("button", { name: /Choose instruments/ }).click();
  const bindings = page.getByRole("region", {
    name: "Instruments for your workflow",
  });
  await bindings.getByRole("button", { name: "Find" }).nth(0).click();
  await page.getByRole("button", { name: "Add Opentrons OT-2" }).click();
  await bindings.getByRole("button", { name: "Find" }).nth(1).click();
  await page
    .getByRole("button", { name: "Add Liquid handler (Opentrons Flex)" })
    .click();
  await page
    .getByRole("button", { name: "Transfer robot", exact: true })
    .click();
  await bindings
    .getByLabel("Robot arm instrument")
    .selectOption({ label: "Sample transfer robot (unconfirmed)" });
  const confirm = page.getByRole("button", { name: "Confirm twin" });
  for (let i = 3; i > 0; i--) {
    await confirm.first().click();
    await expect(confirm).toHaveCount(i - 1);
  }
  // The deck's slots replace a free slot count.
  await expect(page.getByText(/11 on the deck \(1, 2, 3/)).toBeVisible();

  await page.getByRole("tab", { name: "3 · Workflow" }).click();
  await page.getByRole("button", { name: "Use drafted steps" }).click();
  await expect(page.getByLabel("Step 3 sample")).toHaveValue("plate-c");
  await expect(page.getByLabel("Step 1 slot")).toHaveValue("");

  await page.getByRole("tab", { name: "4 · Layout" }).click();
  const preferences = page.getByText("Preferences · 3");
  await expect(preferences).toBeVisible();
  await expect(
    page.getByText("Arm reaches 2 slots on Opentrons OT-2"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Search layouts" }).click();
  const first = page.getByRole("button", { name: /^Layout \d+/ }).first();
  await expect(first).toContainText("slots on Opentrons OT-2", {
    timeout: 120_000,
  });
  await expect(first).toContainText("° elbow");
  await page.getByRole("button", { name: "Stop" }).click();
  await first.click();
  await expect(
    page.getByRole("button", {
      name: /Step 5 · Opentrons OT-2 → Liquid handler \(Opentrons Flex\)/,
    }),
  ).toContainText("cm min clearance", { timeout: 30_000 });
  await page.getByRole("button", { name: "Save layout" }).click();
  await expect(
    page.getByRole("button", { name: "Save layout" }),
  ).toBeDisabled();
  await page.screenshot({
    path: "/tmp/academy-layout-preferences.png",
    fullPage: true,
  });

  // Fewer instruments: either liquid handler can take the other's plates.
  await page.getByText("Fewer instruments").click();
  await expect(
    page.getByText(/can also run the .* steps/).first(),
  ).toBeVisible();

  // A preference nothing can satisfy is explained.
  await page.getByLabel("Preference").selectOption("near");
  await page.getByLabel("Distance in metres").fill("0.05");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByText("Preferences · 4")).toBeVisible();
  await page.getByRole("button", { name: "Search layouts" }).click();
  await expect(page.getByText("No feasible layout")).toBeVisible({
    timeout: 120_000,
  });
  await expect(page.getByText(/Relax one of them/)).toBeVisible();
  expect(errors).toEqual([]);
});

test("finding an instrument opens its lesson or its twin", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "This is my first time" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page
    .getByRole("button", { name: "Meet the instruments", exact: true })
    .click();
  const find = page.getByLabel("Find an instrument to learn");
  await find.fill("OT-2");
  const found = page.getByRole("list", { name: "Instruments found" });
  await found.getByRole("button", { name: "Lesson" }).first().click();
  await expect(
    page.getByRole("button", { name: "Opentrons OT-2", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");

  await find.fill("xpr204e");
  await found.getByRole("button", { name: "Build its twin" }).click();
  await expect(page).toHaveURL(/#\/plan\/instruments$/);
  await expect(page.getByLabel("Search the asset library")).toHaveValue(
    "xpr204e",
  );
  await expect(
    page.getByRole("button", { name: "Add Analytical balance (XPR204E)" }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
