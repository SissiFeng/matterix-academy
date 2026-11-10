import { expect, test } from "@playwright/test";

test("meet the instruments explains parts, modules and unit operations", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page
    .getByRole("button", { name: "Meet the instruments", exact: true })
    .click();

  await expect(
    page.getByRole("heading", { name: "What the robot is made of" }),
  ).toBeVisible();
  // The comparison answers the common confusion: only the Heater-Shaker shakes.
  const table = page.getByRole("table");
  const shaking = table.getByRole("row", { name: /Heater-Shaker/ });
  await expect(shaking.getByRole("cell").nth(2)).toHaveText("Yes");
  await expect(shaking.getByRole("cell").nth(1)).toContainText("No");
  // The table scrolls inside its region; the page itself never scrolls sideways.
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);

  // Unsupported operations say so instead of offering a practice button.
  await expect(
    page.getByText("Not in the teaching model yet").first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "Practise distribute" }).click();
  await expect(page).toHaveURL(/#\/lab\//);
});
