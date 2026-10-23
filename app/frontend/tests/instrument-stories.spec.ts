import { expect, test } from "@playwright/test";

test("public instrument stories play, pause, seek and switch without creating learner data", async ({
  page,
}) => {
  const mutations: string[] = [];
  const errors: string[] = [];
  page.on("request", (request) => {
    if (
      request.url().includes("/api/") &&
      !["GET", "HEAD"].includes(request.method())
    )
      mutations.push(request.url());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  const stories = page.getByTestId("instrument-stories");
  const progress = stories.getByRole("slider", {
    name: "Introduction progress",
  });
  await expect(progress).toHaveValue("0");
  await stories
    .getByRole("button", { name: "Play Flex introduction", exact: true })
    .click();
  await expect
    .poll(async () => Number(await progress.inputValue()))
    .toBeGreaterThan(0.2);
  await stories
    .getByRole("button", { name: "Pause Flex introduction", exact: true })
    .click();
  const paused = await progress.inputValue();
  await page.waitForTimeout(250);
  expect(await progress.inputValue()).toBe(paused);
  await stories.getByRole("button", { name: /02 Read the deck/ }).click();
  await expect(
    stories.getByRole("heading", { name: "Every item has an address." }),
  ).toBeVisible();
  await expect(progress).toHaveValue("5");
  await stories
    .getByRole("button", { name: "Opentrons OT-2", exact: true })
    .click();
  await expect(progress).toHaveValue("0");
  await expect(
    stories.getByRole("heading", { name: "Meet OT-2." }),
  ).toBeVisible();
  await stories
    .getByRole("button", { name: "Distribute", exact: true })
    .click();
  await expect(
    stories.getByRole("heading", { name: "One source. Several samples." }),
  ).toBeVisible();
  await stories
    .getByRole("button", { name: "Replay OT-2 introduction", exact: true })
    .click();
  await expect(
    stories.getByRole("button", {
      name: "Pause OT-2 introduction",
      exact: true,
    }),
  ).toBeVisible();
  expect(mutations).toEqual([]);
  expect(errors).toEqual([]);
});

test("a selected OT-2 starter survives a refresh and opens once after onboarding", async ({
  page,
}) => {
  let creations = 0;
  page.on("request", (request) => {
    if (
      new URL(request.url()).pathname === "/api/sessions" &&
      request.method() === "POST"
    )
      creations++;
  });
  await page.goto("/");
  const stories = page.getByTestId("instrument-stories");
  await stories
    .getByRole("button", { name: "Opentrons OT-2", exact: true })
    .click();
  await stories
    .getByRole("button", { name: "Distribute", exact: true })
    .click();
  await stories
    .getByRole("button", { name: "Use this workflow", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText(
    "Your OT-2 distribute starter is selected",
  );
  expect(creations).toBe(0);
  await page.reload();
  await expect(page.getByRole("status")).toContainText(
    "Your OT-2 distribute starter is selected",
  );
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page
    .getByRole("button", { name: "Enter the learning lab", exact: true })
    .click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "This is my first time" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page
    .getByRole("button", { name: "Open my workspace", exact: true })
    .click();
  await expect(page.getByTestId("workflow-studio")).toHaveAttribute(
    "data-instrument",
    "ot2",
  );
  await expect(page.getByLabel("Workflow name")).toHaveValue(
    "Opentrons OT-2 · Distribute",
  );
  await expect(page.getByLabel("Step 2 volume", { exact: true })).toHaveValue(
    "240",
  );
  expect(creations).toBe(1);
  const savedUrl = page.url();
  await page.reload();
  await expect(page.getByLabel("Workflow name")).toHaveValue(
    "Opentrons OT-2 · Distribute",
  );
  expect(page.url()).toBe(savedUrl);
  expect(creations).toBe(1);
  await page
    .getByRole("button", { name: "Instrument introductions", exact: true })
    .click();
  await page.reload();
  await expect(page.getByTestId("instrument-stories")).toBeVisible();
  expect(page.url()).toContain("#/instruments");
});

test("reduced-motion introductions remain explorable on a small screen in both themes", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce", colorScheme: "dark" });
  await page.goto("/");
  const stories = page.getByTestId("instrument-stories");
  await expect(
    stories.getByRole("button", {
      name: "Play Flex introduction",
      exact: true,
    }),
  ).toBeDisabled();
  await stories.getByRole("button", { name: /04 Take up liquid/ }).click();
  await expect(
    stories.getByRole("heading", { name: "Take up a measured volume." }),
  ).toBeVisible();
  await expect(
    stories.getByRole("slider", { name: "Introduction progress" }),
  ).toHaveValue("14");
  await page.waitForTimeout(250);
  await expect(
    stories.getByRole("slider", { name: "Introduction progress" }),
  ).toHaveValue("14");
  for (const colorScheme of ["dark", "light"] as const) {
    await page.emulateMedia({ colorScheme });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  }
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByPlaceholder("Your first name")).toBeFocused();
});
