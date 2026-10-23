import { test, expect, type Page } from "@playwright/test";

async function enter(page: Page) {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
}
async function fillBrief(page: Page) {
  await page
    .getByLabel("Design title", { exact: true })
    .fill("My blend comparison");
  await page
    .getByLabel("What do you want to learn?")
    .fill("Compare repeatability of three ratios.");
  await page
    .getByLabel("Prepare · What changes and what stays fixed?")
    .fill("Change A:B ratio; keep volume constant.");
  await page
    .getByLabel("Test · What will you measure, and how?")
    .fill("Reader response in arbitrary teaching units, mapped to sample IDs.");
  await page
    .getByLabel("Optimize · How will you choose the next experiment?")
    .fill("Repeat variable results before exploring a new ratio.");
  await page
    .getByLabel("What controls and repeats make the comparison trustworthy?")
    .fill("Two repeats and a blank.");
}

test("research workflow filters, source, adaptation and persistent private brief", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await enter(page);
  await page
    .getByRole("button", { name: "Workflow marketplace", exact: true })
    .click();
  await page.getByLabel("Search workflows").fill("no-matching-material");
  await expect(page.getByText("No matching workflows yet.")).toBeVisible();
  await page.getByRole("button", { name: "Reset filters" }).click();
  await page.getByLabel("Filter by domain").selectOption("Energy");
  await expect(page.getByRole("button", { name: /^Explore / })).toHaveCount(1);
  await page
    .getByRole("button", { name: "Explore Find a better electrolyte" })
    .click();
  await expect(
    page.getByRole("link", { name: "Read the primary paper" }),
  ).toHaveAttribute(
    "href",
    "https://www.nature.com/articles/s41467-022-32938-1",
  );
  await expect(
    page.getByText("Clio liquid-handling platform + Dragonfly"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Adapt this workflow" }).click();
  await expect(page).toHaveURL(/#\/discovery\/clio$/);
  await expect(
    page.getByRole("button", { name: "Save design brief" }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Move Mix and redisperse earlier" })
    .click();
  await page
    .getByRole("button", { name: /Imagine a measurement raster/ })
    .click();
  await fillBrief(page);
  await page.getByRole("button", { name: "Save design brief" }).click();
  await expect(
    page.getByText(
      "Design saved to your notebook. It is not an executable protocol.",
    ),
  ).toBeVisible();
  await page.reload();
  await page
    .getByRole("button", { name: /My blend comparison 2 preparation methods/ })
    .click();
  await expect(page.getByLabel("What do you want to learn?")).toHaveValue(
    "Compare repeatability of three ratios.",
  );
  await expect(
    page.getByRole("button", { name: /Imagine a measurement raster/ }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByRole("button", { name: "Move Mix and redisperse earlier" }),
  ).toBeDisabled();
  const notebook = await (await page.request.get("/api/discovery")).json();
  expect(notebook.briefs[0].status).toBe("design_only");
  expect(notebook.briefs[0].source_id).toBe("clio");
  expect(await (await page.request.get("/api/sessions")).json()).toEqual([]);
  expect(errors).toEqual([]);
});

test("discovery decisions, unsaved guard, conflict recovery and phone layout", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await enter(page);
  await page
    .getByRole("button", { name: "Discovery studio", exact: true })
    .click();
  await page
    .getByRole("button", { name: /03 Optimize the next batch/ })
    .click();
  await page.getByLabel("Declare C the winner from its value of 10.").check();
  await expect(
    page.getByText(/A single high value is not enough/),
  ).toBeVisible();
  await page
    .getByLabel(
      "Repeat B and C, checking preparation and measurement variation.",
    )
    .check();
  await expect(page.getByText(/Investigate reproducibility/)).toBeVisible();
  await fillBrief(page);
  page.once("dialog", (d) => d.dismiss());
  await page.getByRole("button", { name: "Learning lab", exact: true }).click();
  await expect(page.getByLabel("Design title", { exact: true })).toHaveValue(
    "My blend comparison",
  );
  // Another tab saves first; the local draft must survive the resulting conflict.
  await page.request.put("/api/discovery", {
    data: { expected_version: 0, briefs: [] },
  });
  await page.getByRole("button", { name: "Save design brief" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Your draft is still here.",
  );
  await expect(page.getByLabel("Design title", { exact: true })).toHaveValue(
    "My blend comparison",
  );
  await page.getByRole("button", { name: "Reload saved designs" }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.getByRole("button", { name: "Save design brief" }).click();
  await expect(
    page.getByText(
      "Design saved to your notebook. It is not an executable protocol.",
    ),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page
    .getByRole("button", { name: "Workflow marketplace", exact: true })
    .click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page
    .getByRole("button", { name: "Explore A gantry with another job" })
    .click();
  await expect(
    page.getByText(/does not establish Flex tool compatibility/),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("same-design conflicts keep both authors changes and a lost save response does not duplicate a brief", async ({
  page,
}) => {
  await enter(page);
  await page
    .getByRole("button", { name: "Discovery studio", exact: true })
    .click();
  await fillBrief(page);
  // Lose one committed response without tearing down interception during recovery.
  let saves = 0;
  await page.route("**/api/discovery", async (route) => {
    if (route.request().method() !== "PUT") return route.continue();
    saves += 1;
    if (saves !== 1) return route.continue();
    const committed = await route.fetch();
    expect(committed.ok()).toBe(true);
    await route.abort("failed");
  });
  await page.getByRole("button", { name: "Save design brief" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Your draft is still here.",
  );
  expect(saves).toBe(1);
  await page.getByRole("button", { name: "Reload saved designs" }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.getByRole("button", { name: "Save design brief" }).click();
  await expect(
    page.getByText(
      "Design saved to your notebook. It is not an executable protocol.",
    ),
  ).toBeVisible();
  expect(saves).toBe(2);
  let notebook = await (await page.request.get("/api/discovery")).json();
  expect(notebook.briefs).toHaveLength(1);
  const id = notebook.briefs[0].id;
  await page
    .getByLabel("What do you want to learn?")
    .fill("My local question remains unsaved.");
  notebook.briefs[0].objective = "A concurrent update from another tab.";
  await page.request.put("/api/discovery", {
    data: { expected_version: notebook.version, briefs: notebook.briefs },
  });
  await page.getByRole("button", { name: "Save design brief" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Your draft is still here.",
  );
  await page.getByRole("button", { name: "Reload saved designs" }).click();
  await expect(
    page.getByText(/A newer version of this design is saved/),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Save design brief" }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Keep my draft as a new design" })
    .click();
  await page.getByRole("button", { name: "Save design brief" }).click();
  await expect(
    page.getByText(
      "Design saved to your notebook. It is not an executable protocol.",
    ),
  ).toBeVisible();
  notebook = await (await page.request.get("/api/discovery")).json();
  expect(notebook.briefs).toHaveLength(2);
  expect(
    notebook.briefs.find((b: { id: string }) => b.id === id).objective,
  ).toBe("A concurrent update from another tab.");
  expect(
    notebook.briefs.find((b: { id: string }) => b.id !== id).objective,
  ).toBe("My local question remains unsaved.");
});

test("cancelling a move from an unsaved design creates no experiment", async ({
  page,
}) => {
  await enter(page);
  await page
    .getByRole("button", { name: "Discovery studio", exact: true })
    .click();
  await fillBrief(page);
  page.once("dialog", (d) => d.dismiss());
  await page.getByRole("button", { name: "Practice liquid handling" }).click();
  await expect(page.getByLabel("Design title", { exact: true })).toHaveValue(
    "My blend comparison",
  );
  expect(await (await page.request.get("/api/sessions")).json()).toEqual([]);
  let prompts = 0;
  page.on("dialog", async (d) => {
    prompts++;
    await d.accept();
  });
  await page.getByRole("button", { name: "Practice liquid handling" }).click();
  await expect(page).toHaveURL(/#\/lab\//);
  expect(prompts).toBe(1);
  expect(await (await page.request.get("/api/sessions")).json()).toHaveLength(
    1,
  );
});

test("pending sandbox creation freezes the design and cannot redirect a later page", async ({
  page,
}) => {
  await enter(page);
  await page
    .getByRole("button", { name: "Discovery studio", exact: true })
    .click();
  await expect(page.getByRole("button", { name: "New design" })).toBeEnabled();
  let release!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/sessions", async (route) => {
    if (route.request().method() === "POST") {
      await held;
      await route.continue();
    } else await route.continue();
  });
  await page.getByRole("button", { name: "Practice liquid handling" }).click();
  await expect(page.getByLabel("Design title", { exact: true })).toBeDisabled();
  await page
    .getByRole("button", { name: "Workflow marketplace", exact: true })
    .click();
  const result = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/sessions") &&
      response.request().method() === "POST",
  );
  release();
  await result;
  await expect(
    page.getByRole("heading", { name: "Workflow marketplace", exact: true }),
  ).toBeVisible();
  await expect(page).toHaveURL(/#\/marketplace$/);
  await page.getByRole("button", { name: /My experiments/ }).click();
  await expect(
    page.getByRole("button", { name: /My serial dilution/ }),
  ).toBeVisible();
});

test("saving a design disables method and gantry edits until acknowledged", async ({
  page,
}) => {
  await enter(page);
  await page
    .getByRole("button", { name: "Discovery studio", exact: true })
    .click();
  await expect(page.getByRole("button", { name: "New design" })).toBeEnabled();
  await fillBrief(page);
  let release!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/discovery", async (route) => {
    if (route.request().method() === "PUT") await held;
    await route.continue();
  });
  await page.getByRole("button", { name: "Save design brief" }).click();
  try {
    await expect(
      page.getByRole("button", { name: /Imagine a measurement raster/ }),
    ).toBeDisabled();
    await expect(
      page.getByLabel("Design title", { exact: true }),
    ).toBeDisabled();
  } finally {
    release();
  }
  await expect(
    page.getByText(
      "Design saved to your notebook. It is not an executable protocol.",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /Imagine a measurement raster/ }),
  ).toBeEnabled();
});
