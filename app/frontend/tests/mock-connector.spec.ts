import { expect, test } from "@playwright/test";

test("offline mock SiLA2 connector steps, runs, survives refresh and resets a saved workflow", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Riley");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  const saved = await page.request.post("/api/sessions", {
    data: {
      course_id: "workflow-sandbox",
      title: "Offline transfer",
      instrument: "flex",
      layout: { tips: "B1", stock: "D1", plate: "D2", waste: "D3" },
      diluent_volume: 0,
      actions: [
        { kind: "pickup" },
        { kind: "aspirate" },
        { kind: "dispense", well: "A1" },
        { kind: "drop" },
      ],
    },
  });
  expect(saved.status()).toBe(201);
  const session = await saved.json();

  const open = async () => {
    await page.getByRole("button", { name: "Sim → Real", exact: true }).click();
    await page
      .getByRole("button", { name: "Connect an instrument", exact: true })
      .click();
    await page.getByLabel("Offline workflow").selectOption(session.id);
  };
  await page.reload();
  await open();
  const state = page.getByLabel("Offline connector state");
  await page.getByRole("button", { name: "Prepare offline run" }).click();
  await expect(state).toContainText("Synthetic · draft · Step 0/4");
  await expect(state).toContainText("No physical execution");
  await page.getByRole("button", { name: "Next mock step" }).click();
  await expect(state).toContainText("Step 1/4");
  await expect(state).toContainText("Tip: attached");
  await page.getByRole("button", { name: "Run all mock steps" }).click();
  await expect(state).toContainText("Synthetic · completed · Step 4/4");
  await expect(state).toContainText("A1: 100 µL");
  await expect(
    page.getByRole("button", { name: "Run all mock steps" }),
  ).toBeDisabled();

  await page.reload();
  await open();
  await expect(state).toContainText("Synthetic · completed · Step 4/4");
  await page.getByRole("button", { name: "Reset mock run" }).click();
  await expect(state).toContainText("Synthetic · draft · Step 0/4");

  // The saved workflow itself is untouched by offline runs.
  const after = await (
    await page.request.get(`/api/sessions/${session.id}`)
  ).json();
  expect(after.version).toBe(session.version);
  expect(errors).toEqual([]);
});
