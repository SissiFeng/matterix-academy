import { expect, test } from "@playwright/test";

test("the start page maps a learning route and a using route to their pages", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Roadmap learner");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();

  const learning = page.getByRole("region", { name: "Learning route" });
  const using = page.getByRole("region", { name: "Using route" });
  await expect(learning.getByRole("listitem")).toHaveCount(5);
  await expect(using.getByRole("listitem")).toHaveCount(5);

  await learning.getByRole("button", { name: /Simulate/ }).click();
  await expect(page).toHaveURL(/#\/sim$/);
  await page.getByRole("button", { name: "Start here", exact: true }).click();
  await using.getByRole("button", { name: /Check readiness/ }).click();
  await expect(
    page.getByRole("heading", { name: "Real-device readiness", level: 1 }),
  ).toBeVisible();
});
