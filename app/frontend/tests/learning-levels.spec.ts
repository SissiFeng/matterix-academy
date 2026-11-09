import { test, expect, type Page } from "@playwright/test";

async function enter(page: Page) {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Level learner");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page.getByRole("button", { name: "Learning lab", exact: true }).click();
}

test("levels live inside Learning lab; deep links and old entries keep records intact", async ({
  page,
}) => {
  await enter(page);
  await page
    .getByRole("button", { name: "Start an experiment", exact: true })
    .click();
  await expect(page.getByLabel("Experiment title")).toBeVisible();
  const legacyUrl = page.url();
  const before = await (await page.request.get("/api/sessions")).json();
  expect(before).toHaveLength(1);
  await page.getByRole("button", { name: "Learning lab", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Your first workflow." }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Beginner", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  await page.getByRole("link", { name: "Intermediate", exact: true }).click();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Design a complete experiment." }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Advanced", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", { name: "Understand the connected lab." }),
  ).toBeVisible();
  await expect(page.getByText(/Orchestration/).first()).toBeVisible();
  expect(await (await page.request.get("/api/sessions")).json()).toEqual(
    before,
  );
  await page.goto("/#/workflow-course");
  await expect(
    page.getByRole("heading", { name: "Can this workflow run?", exact: true }),
  ).toBeVisible();
  await page.goto("/#/instruments");
  await expect(page.getByTestId("instrument-stories")).toBeVisible();
  await page.goto("/#/learn");
  await expect(
    page.getByRole("heading", { name: "Your first workflow." }),
  ).toBeVisible();
  await page.goto(legacyUrl);
  await page.reload();
  await expect(page.getByLabel("Experiment title")).toHaveValue(
    before[0].experiment.title,
  );
  expect(await (await page.request.get("/api/sessions")).json()).toEqual(
    before,
  );
});

test("beginner lesson resumes existing progress without creating another session", async ({
  page,
}) => {
  await enter(page);
  await page
    .getByRole("button", { name: "Start learning Flex", exact: true })
    .click();
  await page.getByRole("button", { name: "Pipette", exact: true }).click();
  await expect(
    page.getByText("Explored 1 / 5 objects.", { exact: false }),
  ).toBeVisible();
  const lessonUrl = page.url();
  const before = await (await page.request.get("/api/sessions")).json();
  await page.getByRole("button", { name: "Learning lab", exact: true }).click();
  await page.getByRole("link", { name: "Advanced", exact: true }).click();
  await page.getByRole("link", { name: "Beginner", exact: true }).click();
  await page.reload();
  await page
    .getByRole("button", { name: "Continue my Flex lesson", exact: true })
    .click();
  await expect(page).toHaveURL(lessonUrl);
  await expect(
    page.getByText("Explored 1 / 5 objects.", { exact: false }),
  ).toBeVisible();
  expect(await (await page.request.get("/api/sessions")).json()).toEqual(
    before,
  );
  await page.reload();
  await expect(
    page.getByText("Explored 1 / 5 objects.", { exact: false }),
  ).toBeVisible();
});

test("beginner alone can edit, complete and resume a simple workflow on mobile", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await enter(page);
  await expect(
    page.getByRole("link", { name: "Advanced", exact: true }),
  ).toBeVisible();
  await page
    .getByText("Read the code behind a 100 µL teaching transfer", {
      exact: true,
    })
    .click();
  await expect(
    page.getByText(/This is the Academy teaching runner/),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page
    .getByRole("button", { name: "Open transfer starter", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Workflow studio." }),
  ).toBeVisible();
  const workflowUrl = page.url();
  await page.getByLabel("Step 2 volume", { exact: true }).fill("50");
  await page.getByLabel("Step 3 volume", { exact: true }).fill("50");
  await page.getByLabel("Step 3 well", { exact: true }).selectOption("A3");
  await page
    .getByRole("button", { name: "Save workflow", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Save workflow", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Run teaching simulation", exact: true })
    .click();
  await expect(
    page.getByText("Every workflow step completed in the teaching model", {
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Back to learning lab", exact: true })
    .click();
  await expect(
    page.getByText("Practice and understanding complete", { exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Continue my workflow", exact: true })
    .click();
  await expect(page).toHaveURL(workflowUrl);
  await expect(page.getByLabel("Step 3 well", { exact: true })).toHaveValue(
    "A3",
  );
  expect(await (await page.request.get("/api/sessions")).json()).toHaveLength(
    1,
  );
});
