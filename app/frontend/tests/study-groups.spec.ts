import { expect, test, type Browser, type Page } from "@playwright/test";

async function learner(browser: Browser, name: string) {
  const page = await (await browser.newContext()).newPage();
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill(name);
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  return page;
}

async function experiment(page: Page, title: string, volume: string) {
  const created = await page.request.post("/api/sessions", {
    data: { title, transfer_volume: Number(volume) },
  });
  expect(created.ok()).toBe(true);
  // Reload so the sidebar and share list include the new experiment.
  await page.reload();
}

async function openGroups(page: Page) {
  await page.getByRole("button", { name: "Study groups" }).click();
  await expect(
    page.getByRole("heading", { name: "Study groups", level: 1 }),
  ).toBeVisible();
}

test("two learners share, compare, discuss and copy workflows", async ({
  browser,
}) => {
  const ada = await learner(browser, "Ada");
  const grace = await learner(browser, "Grace");
  await experiment(ada, "Ada's dilution", "100");
  await experiment(grace, "Grace's dilution", "150");

  await openGroups(ada);
  await ada.getByLabel("Group name").fill("Dilution pair");
  await ada.getByRole("button", { name: "Create" }).click();
  await expect(
    ada.getByRole("heading", { name: "Dilution pair" }),
  ).toBeVisible();
  const code = (await ada
    .locator("strong")
    .filter({ hasText: /^[A-Z0-9]{8}$/ })
    .textContent())!;
  await ada.getByRole("button", { name: "Share", exact: true }).click();
  await expect(
    ada.getByRole("heading", { name: "Ada's dilution" }),
  ).toBeVisible();

  await openGroups(grace);
  await grace.getByLabel("Join code").fill(code);
  await grace.getByRole("button", { name: "Join" }).click();
  await expect(
    grace.getByRole("heading", { name: "Dilution pair" }),
  ).toBeVisible();
  // Members see each other but only the facilitator holds the code.
  await expect(grace.getByText(code)).toHaveCount(0);
  await grace.getByRole("button", { name: "Share", exact: true }).click();

  await grace
    .getByRole("checkbox", { name: "Compare Ada's dilution by Ada" })
    .check();
  await grace
    .getByRole("checkbox", { name: "Compare Grace's dilution by Grace" })
    .check();
  await expect(
    grace.getByRole("heading", { name: /differences? to discuss/ }),
  ).toBeVisible();

  const adaCard = grace
    .getByRole("listitem")
    .filter({ has: grace.getByRole("heading", { name: "Ada's dilution" }) });
  await adaCard.getByText("Discussion").click();
  await adaCard
    .getByRole("textbox", { name: "Comment on Ada's dilution by Ada" })
    .fill("Why 100 µL here?");
  await adaCard.getByRole("button", { name: "Post" }).click();
  await expect(adaCard.getByText("Why 100 µL here?")).toBeVisible();

  await adaCard.getByRole("button", { name: "Make my own copy" }).click();
  await expect(grace).toHaveURL(/#\/lab\//);
});

test("study groups fit a phone screen", async ({ browser }) => {
  const page = await learner(browser, "Lin");
  await page.setViewportSize({ width: 390, height: 844 });
  await openGroups(page);
  await page.getByLabel("Group name").fill("Phone group");
  await page.getByRole("button", { name: "Create" }).click();
  await expect(
    page.getByRole("heading", { name: "Phone group" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
