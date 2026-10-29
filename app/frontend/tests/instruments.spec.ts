import { expect, test } from "@playwright/test";

test("instrument twins run a multi-device workflow on mock SiLA 2 connectors", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page.getByRole("button", { name: "Meet the instruments" }).click();
  await expect(
    page.getByRole("heading", {
      name: "Photograph an instrument. Run it as a twin.",
    }),
  ).toBeVisible();
  await expect(
    page.getByText("Astra is not configured on this server."),
  ).toBeVisible();

  for (const name of ["Heating station", "Plate reader", "Transfer robot"]) {
    await page.getByRole("button", { name }).click();
  }
  const confirm = page.getByRole("button", { name: "Confirm twin" });
  await expect(confirm).toHaveCount(3);
  for (let i = 3; i > 0; i--) {
    await confirm.first().click();
    await expect(confirm).toHaveCount(i - 1);
  }
  await page.reload();
  await expect(page.getByText("Confirmed")).toHaveCount(3);

  await page.getByRole("tab", { name: "2 · Workflow" }).click();
  const add = page.getByRole("button", { name: "Add step" });
  await add.click();
  await add.click();
  await page.getByLabel("Step 2 operation").selectOption("heat");
  await page.getByLabel("Step 2 temperature").fill("42");
  await add.click();
  await page
    .getByLabel("Step 3 instrument")
    .selectOption({ label: "Sample transfer robot" });
  await expect(page.getByLabel("Step 3 to")).toHaveValue(/.+/);
  await add.click();
  await page
    .getByLabel("Step 4 instrument")
    .selectOption({ label: "Plate reader" });
  await page.getByLabel("Step 4 operation").selectOption("read");
  // The heater's deep-well plate holds 500 µL; the reader's plate does not.
  await page.getByLabel("Step 1 volume").fill("500");
  await page.getByRole("button", { name: "Save workflow" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "500 µL exceeds Plate reader's 300 µL limit",
  );
  await page.getByLabel("Step 1 volume").fill("150");
  await page.getByRole("button", { name: "Save workflow" }).click();
  await page.getByRole("button", { name: "Run on mock connectors" }).click();
  await expect(
    page.getByText("4. Plate reader · Read → 150 µL, 42 °C, not mixed"),
  ).toBeVisible();
  await expect(
    page.getByText("Synthetic · mock SiLA 2 connectors"),
  ).toBeVisible();

  // Detail is added only against a recorded failure residual.
  await page.getByRole("tab", { name: "1 · Instruments" }).click();
  const reader = page.locator("article", { hasText: "Plate reader" });
  const addConsumable = reader.getByRole("button", { name: "Add consumable" });
  await expect(addConsumable).toBeDisabled();
  await reader
    .getByRole("button", { name: "Record a failure residual" })
    .click();
  await reader.getByLabel("Which layer was wrong?").selectOption("consumable");
  await reader.getByLabel("The twin predicted").fill("Read needs nothing");
  await reader
    .getByLabel("The real instrument did")
    .fill("Read used a sealing film");
  await reader.getByRole("button", { name: "Record residual" }).click();
  await expect(reader.getByText("Open against revision 1")).toBeVisible();
  await addConsumable.click();
  await reader.getByLabel("Consumable name").fill("Sealing film");
  await reader.getByLabel("Sealing film used by").selectOption("read");
  await reader.getByRole("button", { name: "Save revision" }).click();
  await expect(reader.getByText("Addressed in revision 2")).toBeVisible();
  await expect(
    reader.getByText("Academy USD template · revision 2"),
  ).toBeVisible();

  await page.getByRole("tab", { name: "3 · Connectors" }).click();
  await expect(
    page.getByRole("radio", { name: /Real device/ }).first(),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "View mock connector" })
    .first()
    .click();
  await expect(
    page.getByText("HeatingStationMock.sila.xml", { exact: true }),
  ).toBeVisible();
  await expect(page.locator("pre").first()).toContainText(
    "<Identifier>Heat</Identifier>",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("tab", { name: "2 · Workflow" }).click();
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
  expect(errors).toEqual([]);
});
