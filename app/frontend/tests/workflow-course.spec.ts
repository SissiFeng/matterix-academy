import { test, expect, type Page } from "@playwright/test";

async function enter(page: Page) {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Workflow learner");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page.getByRole("button", { name: "Learning lab", exact: true }).click();
  await page
    .getByRole("button", { name: "Open workflow judgment course" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Can this workflow run?", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Check the gaps" }),
  ).toBeEnabled();
}
async function diagnose(page: Page) {
  for (const text of [
    "The source cannot",
    "An explicit mixing",
    "A teaching pass",
  ])
    await page.getByRole("checkbox", { name: new RegExp(text) }).check();
  await page.getByRole("button", { name: "Check the gaps" }).click();
  await expect(page.getByLabel("Starting source volume (µL)")).toBeVisible();
}
async function repair(page: Page) {
  await page.getByLabel("Starting source volume (µL)").fill("100");
  await page.getByLabel("Mixing approach").selectOption("ideal");
  await page.getByRole("button", { name: "Save repaired plan" }).click();
  await expect(
    page.getByRole("button", { name: "Run synthetic trial" }),
  ).toBeEnabled();
}

test("complete course from learning entry, wrong answers, reload, evidence and restart", async ({
  page,
}) => {
  await enter(page);
  await page.getByRole("button", { name: "Check the gaps" }).click();
  await expect(page.getByText(/Compare the 50 µL source/)).toBeVisible();
  await diagnose(page);
  await page.getByRole("button", { name: "Save repaired plan" }).click();
  await expect(page.getByText(/Provide at least 100 µL/)).toBeVisible();
  await repair(page);
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Run synthetic trial" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Run synthetic trial" }).click();
  await expect(
    page.getByRole("heading", { name: "Synthetic trial · 12 actions" }),
  ).toBeVisible();
  await page.getByLabel("Immediately resend the dispense command").check();
  await page.getByRole("button", { name: "Check recovery decision" }).click();
  await expect(
    page.getByText(/A missing response leaves the outcome unknown/),
  ).toBeVisible();
  await page
    .getByLabel("Read the original command record without replaying it")
    .check();
  await page.getByRole("button", { name: "Check recovery decision" }).click();
  await expect(page.getByText(/Scripted record retrieved/)).toBeVisible();
  await page
    .getByLabel("The physical workflow is qualified and may run")
    .check();
  await page
    .getByLabel("Explain your evidence and its limits")
    .fill("The trial passed and I think that proves everything.");
  await page.getByRole("button", { name: "Submit conclusion" }).click();
  await expect(page.getByText(/Choose the conclusion supported/)).toBeVisible();
  await page
    .getByLabel(
      "The repaired plan passed synthetic checks; physical readiness is unverified",
    )
    .check();
  await page
    .getByLabel("Explain your evidence and its limits")
    .fill(
      "Synthetic bookkeeping passed; hardware calibration and physical execution are unverified. Read the original record before retrying.",
    );
  await page.getByRole("button", { name: "Submit conclusion" }).click();
  await expect(
    page.getByRole("heading", { name: "Workflow judgment complete" }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Workflow judgment complete" }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "No physical-device qualification or permission was issued.",
    ),
  ).toBeVisible();
  await page.getByText("Inspect synthetic action history").click();
  await expect(
    page
      .getByRole("region", { name: "Synthetic trial evidence" })
      .getByRole("listitem"),
  ).toHaveCount(12);
  const saved = await (await page.request.get("/api/workflow-course")).json();
  expect(saved.evidence).toBe("synthetic");
  expect(saved.completed).toBe(true);
  expect(await (await page.request.get("/api/sessions")).json()).toEqual([]);
  await page.screenshot({
    path: "test-results/workflow-course-complete.png",
    fullPage: true,
  });
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Restart course" }).click();
  await expect(
    page.getByRole("heading", { name: "Which claims prevent approval?" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Synthetic trial · 12 actions" }),
  ).toHaveCount(0);
});

test("lost save response reconciles original record without replaying", async ({
  page,
}) => {
  await enter(page);
  await diagnose(page);
  let posts = 0;
  await page.route("**/api/workflow-course", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    posts++;
    await route.fetch();
    await route.abort("failed");
  });
  await page.getByLabel("Starting source volume (µL)").fill("100");
  await page.getByLabel("Mixing approach").selectOption("ideal");
  await page.getByRole("button", { name: "Save repaired plan" }).click();
  await expect(
    page.getByRole("button", { name: "Run synthetic trial" }),
  ).toBeEnabled();
  expect(posts).toBe(1);
  expect(
    (await (await page.request.get("/api/workflow-course")).json()).phase,
  ).toBe("practice");
});

test("stale course answers reload the winner; unsaved navigation is guarded", async ({
  page,
}) => {
  await enter(page);
  await page.getByRole("checkbox", { name: /The source cannot/ }).check();
  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByRole("button", { name: "Back to learning lab" }).click();
  await expect(page).toHaveURL(/#\/workflow-course$/);
  await page.request.post("/api/workflow-course", {
    data: {
      expected_version: 0,
      action: "inspect",
      findings: ["source", "mixing", "physical"],
    },
  });
  await page.getByRole("button", { name: "Check the gaps" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "changed in another request",
  );
  await expect(page.getByLabel("Starting source volume (µL)")).toBeVisible();
});

test("unresolved save outcome blocks edits until read-only recovery succeeds", async ({
  page,
}) => {
  await enter(page);
  await diagnose(page);
  await page.route("**/api/workflow-course", async (route) => {
    if (route.request().method() === "POST") {
      await route.fetch();
      await route.abort("failed");
    } else await route.abort("failed");
  });
  await page.getByLabel("Starting source volume (µL)").fill("100");
  await page.getByLabel("Mixing approach").selectOption("ideal");
  await page.getByRole("button", { name: "Save repaired plan" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "saved outcome could not be checked",
  );
  await expect(page.getByLabel("Starting source volume (µL)")).toBeDisabled();
  await page.unroute("**/api/workflow-course");
  await page.getByRole("button", { name: "Reload saved progress" }).click();
  await expect(
    page.getByRole("button", { name: "Run synthetic trial" }),
  ).toBeEnabled();
});

test("mobile and dark theme keep the review usable without horizontal overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await enter(page);
  await page.evaluate(() =>
    document.documentElement.setAttribute("data-theme", "dark"),
  );
  await expect(page.getByText(/Synthetic teaching only/)).toBeVisible();
  const width = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }));
  expect(width.scroll).toBeLessThanOrEqual(width.client);
  await page.screenshot({
    path: "test-results/workflow-course-mobile-dark.png",
    fullPage: true,
  });
  await diagnose(page);
  await repair(page);
});
