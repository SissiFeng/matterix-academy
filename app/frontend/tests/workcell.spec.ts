import { expect, test, type Page } from "@playwright/test";

async function enter(page: Page) {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await expect(
    page.getByRole("heading", {
      name: "Your first workcell starts with one device.",
    }),
  ).toBeVisible();
}

async function identify(page: Page) {
  await page.getByRole("button", { name: "Onboard", exact: true }).click();
  await page.getByLabel("Device name", { exact: true }).fill("Flex 01");
  await page.getByLabel("Workcell name").fill("Liquid handling");
  await page.getByRole("button", { name: "Save and continue" }).click();
  await expect(
    page.getByRole("heading", { name: "Choose a connection plan" }),
  ).toBeVisible();
}

async function describe(page: Page) {
  await page.getByRole("radio", { name: /Native API/ }).check();
  await page.getByRole("button", { name: "Save and continue" }).click();
  for (const name of ["Pick up tip", "Aspirate", "Dispense", "Discard tip"]) {
    await page.getByRole("checkbox", { name: new RegExp(`^${name}`) }).check();
  }
  await page.getByRole("button", { name: "Save and continue" }).click();
  await expect(
    page.getByRole("heading", { name: "Pair a teaching twin" }),
  ).toBeVisible();
}

async function pair(page: Page) {
  await identify(page);
  await describe(page);
  await page
    .getByRole("button", { name: "Create teaching twin", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Review the evidence" }),
  ).toBeVisible();
}

test("device onboarding persists, pairs a trial, and closes the teaching evidence loop", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await enter(page);
  await identify(page);
  const deviceUrl = page.url();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Choose a connection plan" }),
  ).toBeVisible();
  await describe(page);
  await page
    .getByRole("button", { name: "Create teaching twin", exact: true })
    .click();
  await page.getByRole("button", { name: "Open twin", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "State difference" }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Physical state has not been observed. Differences cannot be calculated.",
    ),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Check readiness", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Physical readiness is unverified." }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Execute on real lab" }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Open teaching trial", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Run experiment", exact: true })
    .click();
  await expect(
    page.getByText("You reached the learning goal.", { exact: true }),
  ).toBeVisible({ timeout: 25000 });
  await page.getByRole("button", { name: "Runs", exact: true }).click();
  await expect(page.getByRole("table")).toContainText(
    "Teaching ↔ physical run comparison",
  );
  await expect(
    page.getByRole("table").getByText("Completed", { exact: true }),
  ).toHaveCount(12);
  await expect(page.getByText("Not comparable", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Return to the twin" }).click();
  await expect(
    page.getByRole("heading", { name: "Teaching timeline" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Check readiness", exact: true })
    .click();
  await expect(
    page.getByText("Saved teaching goal passed. Synthetic evidence only."),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Execute on real lab" }),
  ).toBeDisabled();
  await page.goto(deviceUrl);
  await expect(
    page.getByRole("heading", { name: "Review the evidence" }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("a lost twin receipt is reconciled without creating a second session", async ({
  page,
}) => {
  await enter(page);
  await identify(page);
  await describe(page);
  let sent = 0;
  await page.route(
    "**/api/devices/*/twin",
    async (route) => {
      sent += 1;
      await route.fetch();
      await route.abort("failed");
    },
    { times: 1 },
  );
  await page
    .getByRole("button", { name: "Create teaching twin", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Review the evidence" }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Reloaded the saved device. Review its current state before continuing.",
    ),
  ).toBeVisible();
  expect(sent).toBe(1);
  expect(await (await page.request.get("/api/sessions")).json()).toHaveLength(
    1,
  );
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Review the evidence" }),
  ).toBeVisible();
});

test("conflicting device edits reload the winning revision and unsaved edits are guarded", async ({
  page,
  context,
}) => {
  await enter(page);
  await identify(page);
  const other = await context.newPage();
  await other.goto(page.url());
  await other.getByRole("radio", { name: /SiLA 2 connector/ }).check();
  await page.getByRole("radio", { name: /Native API/ }).check();
  await page.getByRole("button", { name: "Save and continue" }).click();
  await expect(
    page.getByRole("heading", { name: "Describe its intended capabilities" }),
  ).toBeVisible();
  await other.getByRole("button", { name: "Save and continue" }).click();
  await expect(other.getByRole("alert")).toContainText("This record changed");
  await expect(
    other.getByText(
      "Reloaded the saved device. Review its current state before continuing.",
    ),
  ).toBeVisible();
  const records = await (await page.request.get("/api/devices")).json();
  expect(records[0].connection).toBe("native_api");
  expect(records[0].version).toBe(2);
  await page.getByRole("checkbox", { name: /^Aspirate/ }).check();
  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByRole("button", { name: "Overview", exact: true }).click();
  await expect(page.getByRole("checkbox", { name: /^Aspirate/ })).toBeChecked();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Overview", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Liquid handling", exact: true }),
  ).toBeVisible();
  await other.close();
});

test("workspace pages fit a phone and preserve device selection on reload", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await enter(page);
  await pair(page);
  await page.getByRole("button", { name: "Open twin", exact: true }).click();
  const twinUrl = page.url();
  for (const name of ["Twin", "Sim → Real", "Runs", "Overview"]) {
    await page
      .getByRole("navigation", { name: "Workcell navigation" })
      .getByRole("button", { name, exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Refresh workspace" }),
    ).toBeEnabled();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  }
  await page.goto(twinUrl);
  await expect(
    page.getByRole("heading", { name: "State difference" }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("twin-mobile.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({
    path: testInfo.outputPath("twin-desktop.png"),
    fullPage: true,
  });
});

test("edited declarations cannot skip saving and paired trials survive the recent list window", async ({
  page,
}) => {
  await enter(page);
  await pair(page);
  const steps = page.getByRole("list", { name: "Device onboarding steps" });
  await steps.getByRole("button", { name: /Capabilities/ }).click();
  await page.getByRole("checkbox", { name: /^Dispense/ }).uncheck();
  await expect(
    steps.getByRole("button", { name: /Create twin/ }),
  ).toBeDisabled();
  await expect(steps.getByRole("button", { name: /Validate/ })).toBeDisabled();
  await page.getByRole("button", { name: "Save and continue" }).click();
  await page.getByRole("button", { name: "Review validation" }).click();
  await expect(page.getByText("Not declared: dispense.")).toBeVisible();
  await page.route("**/api/sessions", (route) => route.fulfill({ json: [] }));
  await page.getByRole("button", { name: "Runs", exact: true }).click();
  await expect(
    page.getByRole("heading", {
      name: "Flex 01 · teaching trial",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("table").getByText("Not executed", { exact: true }),
  ).toHaveCount(12);
});
