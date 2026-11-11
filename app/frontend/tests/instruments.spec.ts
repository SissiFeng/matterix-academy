import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

test("instrument twins run a multi-device workflow on the mock contract", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "This is my first time" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page
    .getByRole("button", { name: "Meet the instruments", exact: true })
    .click();
  // The instruments page teaches; planning your own workcell has its own page.
  await expect(page.getByTestId("instrument-stories")).toBeVisible();
  await page
    .getByRole("button", { name: /Bring your own instruments/ })
    .click();
  await expect(page).toHaveURL(/#\/plan$/);
  const studio = page.getByRole("region", { name: "Plan your workcell" });
  await expect(studio).toBeVisible();
  // Without Astra the description step says so and the manual path stays open.
  await expect(
    studio.getByRole("button", { name: "Draft roles and steps" }),
  ).toBeDisabled();
  await expect(studio.getByText(/Drafting needs Astra/)).toBeVisible();
  await studio.getByRole("button", { name: /Skip to instruments/ }).click();
  await expect(page).toHaveURL(/#\/plan\/instruments$/);
  await expect(
    studio.getByText("Astra is not configured on this server."),
  ).toBeVisible();

  for (const name of ["Heating station", "Plate reader", "Transfer robot"]) {
    await page.getByRole("button", { name, exact: true }).click();
  }
  const confirm = studio.getByRole("button", { name: "Confirm twin" });
  await expect(confirm).toHaveCount(3);
  for (let i = 3; i > 0; i--) {
    await confirm.first().click();
    await expect(confirm).toHaveCount(i - 1);
  }
  await page.reload();
  await expect(studio.getByText("Confirmed")).toHaveCount(3);

  await page.getByRole("tab", { name: "3 · Workflow" }).click();
  const add = page.getByRole("button", { name: "Add step" });
  await add.click();
  await add.click();
  await studio.getByLabel("Step 2 operation").selectOption("heat");
  await studio.getByLabel("Step 2 temperature").fill("42");
  await add.click();
  await studio
    .getByLabel("Step 3 instrument")
    .selectOption({ label: "Sample transfer robot" });
  await expect(studio.getByLabel("Step 3 to")).toHaveValue(/.+/);
  await add.click();
  await studio
    .getByLabel("Step 4 instrument")
    .selectOption({ label: "Plate reader" });
  await studio.getByLabel("Step 4 operation").selectOption("read");
  // The heater's deep-well plate holds 500 µL; the reader's plate does not.
  await studio.getByLabel("Step 1 volume").fill("500");
  await studio.getByRole("button", { name: "Save workflow" }).click();
  await expect(studio.getByRole("alert")).toContainText(
    "500 µL exceeds Plate reader's 300 µL limit",
  );
  await studio.getByLabel("Step 1 volume").fill("150");
  await studio.getByRole("button", { name: "Save workflow" }).click();
  await studio.getByRole("button", { name: "Run on mock connectors" }).click();
  await expect(
    studio.getByText("4. Plate reader · Read → 150 µL, 42 °C, not mixed"),
  ).toBeVisible();
  await expect(
    page.getByText("Synthetic · in-process mock contract"),
  ).toBeVisible();

  await page.screenshot({
    path: "/tmp/academy-instruments-workflow-desktop.png",
    fullPage: true,
  });

  // Detail is added only against a recorded failure residual.
  await studio.getByRole("tab", { name: "2 · Instruments" }).click();
  const reader = studio.locator("article", { hasText: "Plate reader" });
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

  await page.getByRole("tab", { name: "5 · Connectors" }).click();
  await expect(
    studio.getByRole("radio", { name: /Real device/ }).first(),
  ).toBeDisabled();
  await studio
    .getByRole("button", { name: "View mock connector" })
    .first()
    .click();
  await expect(
    studio.getByText("HeatingStationMock.sila.xml", { exact: true }),
  ).toBeVisible();
  await expect(studio.locator("pre").first()).toContainText(
    "<Identifier>Heat</Identifier>",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("tab", { name: "3 · Workflow" }).click();
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
  await page.screenshot({
    path: "/tmp/academy-instruments-workflow-mobile.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});

async function openInstruments(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "This is my first time" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page
    .getByRole("button", { name: "Plan a layout", exact: true })
    .click();
  await page.getByRole("tab", { name: "2 · Instruments" }).click();
}

async function enterInstruments(page: import("@playwright/test").Page) {
  await openInstruments(page);
  await page
    .getByRole("button", { name: "Heating station", exact: true })
    .click();
}

test("catalog refresh preserves instrument edits and navigation protects drafts", async ({
  page,
}) => {
  await enterInstruments(page);
  await page
    .getByLabel("Instrument name", { exact: true })
    .fill("My edited heater");
  await page.getByRole("button", { name: "Plate reader", exact: true }).click();
  await expect(
    page.getByLabel("Instrument name", { exact: true }).first(),
  ).toHaveValue("My edited heater");
  page.once("dialog", (dialog) => dialog.dismiss());
  await page
    .getByRole("button", { name: "Simulation lab", exact: true })
    .click();
  await expect(
    page.getByLabel("Instrument name", { exact: true }).first(),
  ).toHaveValue("My edited heater");
  await page.getByRole("button", { name: "Confirm twin" }).first().click();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "USD", exact: true }).first().click();
  expect((await download).suggestedFilename()).toBe("My edited heater.usda");
});

test("a stale workflow save preserves local steps and can be reconciled", async ({
  page,
}) => {
  await enterInstruments(page);
  await page.getByRole("button", { name: "Confirm twin" }).click();
  await page.getByRole("tab", { name: "3 · Workflow" }).click();
  await page.getByRole("button", { name: "Add step" }).click();
  await page.getByRole("button", { name: "Add step" }).click();
  await page.getByLabel("Step 2 operation").selectOption("heat");
  await page.getByLabel("Step 2 temperature").fill("42");
  const current = await (await page.request.get("/api/twins")).json();
  const competing = await page.request.post("/api/twins", {
    data: {
      expected_version: current.version,
      id: crypto.randomUUID(),
      template_id: "reader",
    },
  });
  expect(competing.ok()).toBe(true);
  await page.getByRole("button", { name: "Save workflow" }).click();
  await expect(page.getByRole("alert")).toContainText("This record changed");
  await expect(page.getByLabel("Step 2 temperature")).toHaveValue("42");
  await page.getByRole("button", { name: "Save workflow" }).click();
  await expect(
    page.getByRole("button", { name: "Run on mock connectors" }),
  ).toBeEnabled();
  const saved = await (await page.request.get("/api/twins")).json();
  expect(saved.steps[1].value).toBe(42);
  await page
    .getByRole("button", { name: "Connector explorer", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Open instrument mock connectors" })
    .click();
  await expect(
    page.getByRole("tab", { name: "5 · Connectors" }),
  ).toHaveAttribute("aria-selected", "true");
  const downloaded = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download runnable SiLA bundle" })
    .click();
  expect((await downloaded).suggestedFilename()).toMatch(
    /^mock-workcell-.*\.zip$/,
  );
  await page
    .getByRole("button", { name: "Simulation lab", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Design a multi-device workflow" })
    .click();
  await expect(page.getByRole("tab", { name: "3 · Workflow" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
});

test("a SimReady asset starts an attributed twin that becomes a mock connector", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await enterInstruments(page);
  await page
    .getByRole("button", { name: "Add Microplate reader", exact: true })
    .click();
  const card = page.locator("article", {
    hasText: "SimReady asset · ForgeCAD",
  });
  await expect(
    card.getByRole("link", { name: /Microplate reader © ForgeCAD, CC-BY-4.0/ }),
  ).toHaveAttribute("href", /huggingface\.co\/datasets\/ForgeCAD\//);
  await card.getByRole("button", { name: "Confirm twin" }).click();
  await expect(card.getByText("revision 1")).toBeVisible();
  await page.getByRole("tab", { name: "5 · Connectors" }).click();
  await page
    .getByRole("button", { name: "View mock connector" })
    .last()
    .click();
  await expect(
    page.getByText("MicroplateReaderMock.sila.xml", { exact: true }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("a ChemLab asset starts a non-commercial reference twin", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await enterInstruments(page);
  await page.getByLabel("Search the asset library").fill("xpr204e");
  await expect(page.getByText("1 match", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Add Analytical balance (XPR204E)" })
    .click();
  const card = page.locator("article", {
    hasText: "ChemLab model · CC-BY-NC-4.0",
  });
  await expect(
    card.getByRole("link", { name: /XPR204E .* © MBZUAI, CC-BY-NC-4.0/ }),
  ).toHaveAttribute(
    "href",
    /huggingface\.co\/datasets\/MBZUAI\/ChemLab-Assets\//,
  );
  await card.getByRole("button", { name: "Confirm twin" }).click();
  await expect(card.getByText("revision 1")).toBeVisible();
  expect(errors).toEqual([]);
});

test("a photo match swaps the Astra sketch for the catalogued footprint", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const id = "8f0c2a1e-6b7d-4c3a-9e2f-1a2b3c4d5e6f";
  let photo: Record<string, unknown> | null = null;
  let matched: unknown = null;
  // Astra is not configured in e2e, so the photo outcome is stubbed at the API edge.
  await page.route("**/api/twins", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const catalog = await (await route.fetch()).json();
    if (!photo) {
      const { results } = await (
        await page.request.get("/api/twins/library?q=balance")
      ).json();
      const xpr = results.find((r: { id: string }) => r.id === "mt_xpr204e");
      photo = {
        id,
        status: "draft",
        confirmed: false,
        mode: "mock",
        source: "astra_image",
        spec: { ...catalog.templates.reader, name: "Benchtop balance" },
        asset: null,
        identification: {
          library_id: "chemlab:mt_xpr204e",
          alternatives: [],
          maker: "METTLER TOLEDO",
          model: "XPR204E",
          confidence: "high",
          evidence: "XPR204E badge on the terminal",
        },
        matches: [{ ...xpr, suggested_by: "astra", verified: true }],
        message: "",
        evidence: "synthetic",
        revision: 0,
        residuals: [],
      };
    }
    await route.fulfill({ json: { ...catalog, twins: [photo] } });
  });
  await page.route(`**/api/twins/${id}/match`, async (route) => {
    matched = route.request().postDataJSON();
    const catalog = await (await page.request.get("/api/twins")).json();
    const twin = {
      ...photo,
      source: "chemlab_asset",
      spec: {
        ...catalog.templates.reader,
        name: "Analytical balance (XPR204E)",
      },
      asset: {
        id: "mt_xpr204e",
        label: "METTLER TOLEDO XPR204E analytical balance",
        provider: "MBZUAI ChemLab-Assets",
        license: "CC-BY-NC-4.0",
        attribution:
          "METTLER TOLEDO XPR204E analytical balance model © MBZUAI, CC-BY-NC-4.0, via ChemLab-Assets",
        repo: "MBZUAI/ChemLab-Assets",
        revision: "pinned",
        path: "assets/mt_xpr204e",
        url: "https://huggingface.co/datasets/MBZUAI/ChemLab-Assets",
      },
    };
    await route.fulfill({
      json: { ...catalog, version: catalog.version + 1, twins: [twin] },
    });
  });
  await openInstruments(page);
  const matches = page.getByRole("region", { name: "Library matches" });
  await expect(
    matches.getByText("Astra read METTLER TOLEDO XPR204E"),
  ).toBeVisible();
  await expect(matches.getByText("Label confirmed")).toBeVisible();
  await matches
    .getByRole("button", { name: "Use Analytical balance (XPR204E) footprint" })
    .click();
  await expect(matches.getByRole("button", { name: /footprint/ })).toHaveText(
    "In use",
  );
  expect(matched).toMatchObject({
    collection: "chemlab",
    asset_id: "mt_xpr204e",
  });
  await expect(
    page.getByText("ChemLab model · CC-BY-NC-4.0", { exact: true }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("an instrument missing from the library points to photo and templates", async ({
  page,
}) => {
  await enterInstruments(page);
  await page.getByLabel("Search the asset library").fill("no such instrument");
  await expect(page.getByText("0 matches", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Not in the library. Photograph it or start from a generic"),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", {
      name: "Not sure of the model, or not listed?",
    }),
  ).toBeVisible();
});

test("bench layout plans a collision-checked arm path for each transfer", async ({
  page,
}) => {
  // A long journey of planned paths; CI runners take about twice a laptop's time.
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await enterInstruments(page);
  for (const name of ["Plate reader", "Transfer robot"])
    await page.getByRole("button", { name, exact: true }).click();
  const confirm = page.getByRole("button", { name: "Confirm twin" });
  for (let i = 3; i > 0; i--) {
    await confirm.first().click();
    await expect(confirm).toHaveCount(i - 1);
  }

  await page.getByRole("tab", { name: "3 · Workflow" }).click();
  const add = page.getByRole("button", { name: "Add step" });
  await add.click();
  await add.click();
  await page
    .getByLabel("Step 2 instrument")
    .selectOption({ label: "Sample transfer robot" });
  await page
    .getByLabel("Step 2 from")
    .selectOption({ label: "From Heating station" });
  await page.getByLabel("Step 2 to").selectOption({ label: "To Plate reader" });
  await page.getByLabel("Step 1 volume").fill("150");
  await page.getByRole("button", { name: "Save workflow" }).click();
  await expect(
    page.getByRole("button", { name: "Save workflow" }),
  ).toBeDisabled();

  // A suggested layout is checked against the saved workflow straight away.
  await page.getByRole("tab", { name: "4 · Layout" }).click();
  const path = page.getByRole("button", {
    name: /Step 2 · Heating station → Plate reader/,
  });
  await expect(path).toContainText("cm min clearance");
  // The path was run in the rigid-body simulation, and says what that covers.
  await expect(path).toContainText(/\d+\.\d s · .*% joint torque/);
  await expect(
    page.getByText("simulated in MuJoCo", { exact: true }),
  ).toBeVisible();
  await page
    .getByText(/Simulated in MuJoCo [\d.]+, not run on a robot/)
    .click();
  await expect(page.getByText(/No cables,\s+calibrated poses/)).toBeVisible();

  // Keyboard placement moves the footprint in 10 cm steps.
  const heater = page.getByRole("button", { name: /^Heating station at x/ });
  await heater.focus();
  await page.keyboard.press("Shift+ArrowUp");
  await expect(heater).toHaveAttribute("aria-label", /z 0\.01 m/);

  // Overlap is caught locally and blocks saving.
  await page.getByLabel("Heating station x").fill("0");
  await expect(
    page.getByText(
      /Sample transfer robot, Heating station overlap or leave the bench/,
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Save layout" }),
  ).toBeDisabled();
  await page.getByLabel("Heating station x").fill("-0.54");

  // An out-of-reach station is explained by the server and cannot be saved.
  await page.getByRole("button", { name: /^Plate reader at x/ }).focus();
  await page.getByLabel("Plate reader x").fill("0.95");
  await page.getByLabel("Plate reader z").fill("0.6");
  await expect(
    page.getByText(
      /Plate reader's top access point: it is .* m from the UR5e shoulder/,
    ),
  ).toBeVisible();
  await page.getByRole("button", { name: "Save layout" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "arm reaches about 0.85 m",
  );
  await page
    .getByRole("alert")
    .getByRole("button", { name: "Dismiss" })
    .click();

  await page.getByLabel("Plate reader x").fill("0.54");
  await page.getByLabel("Plate reader z").fill("0.11");
  await expect(path).toContainText("cm min clearance");
  await page.getByRole("button", { name: "Save layout" }).click();
  await expect(
    page.getByRole("button", { name: "Save layout" }),
  ).toBeDisabled();
  // The saved path exports as an action chain for the UR5e SiLA connector.
  const download = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download step 2 as a UR5e action chain" })
    .click();
  const file = await (await download).path();
  const chain = JSON.parse(readFileSync(file, "utf8"));
  expect(chain.schema).toBe("ur5e.action-chain/2");
  expect(chain.provenance.evidence).toBe("synthetic");
  expect(chain.waypoints.length).toBeGreaterThan(1);
  expect(chain.waypoints.length).toBeLessThanOrEqual(24);
  await page.screenshot({
    path: "/tmp/academy-instruments-layout-desktop.png",
    fullPage: true,
  });

  // A layout names the instruments whose sizes nobody compared with the real thing.
  const unchecked = page.getByText(
    /Sizes not checked against the real instrument: .*Heating station/,
  );
  await expect(unchecked).toBeVisible();
  await page.getByRole("tab", { name: "2 · Instruments" }).click();
  const sized = page.getByLabel(/Sizes checked against the real instrument/);
  await expect(sized).toHaveCount(3);
  for (let i = 0; i < 3; i++) {
    await sized.nth(i).click();
    await expect(sized.nth(i)).toBeChecked();
  }
  await page.getByRole("tab", { name: "4 · Layout" }).click();
  await expect(path).toBeVisible();
  await expect(unchecked).toBeHidden();

  await page.reload();
  await page.getByRole("tab", { name: "3 · Workflow" }).click();
  await expect(page.getByText(/collision-free arm path/)).toBeVisible();
  await page.getByRole("button", { name: "Run on mock connectors" }).click();
  await expect(
    page.getByText(/Transfer sample · UR5e path .* m, .* cm clearance/),
  ).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("tab", { name: "4 · Layout" }).click();
  await expect(path).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
  await page.screenshot({
    path: "/tmp/academy-instruments-layout-mobile.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});

test("layout search keeps pinned instruments and compares measured options", async ({
  page,
}) => {
  // Each search chunk runs up to 6 s of planning; CI runners are slower than laptops.
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await enterInstruments(page);
  for (const name of ["Plate reader", "Transfer robot"])
    await page.getByRole("button", { name, exact: true }).click();
  const confirm = page.getByRole("button", { name: "Confirm twin" });
  for (let i = 3; i > 0; i--) {
    await confirm.first().click();
    await expect(confirm).toHaveCount(i - 1);
  }
  await page.getByRole("tab", { name: "3 · Workflow" }).click();
  const add = page.getByRole("button", { name: "Add step" });
  await add.click();
  await add.click();
  await page
    .getByLabel("Step 2 instrument")
    .selectOption({ label: "Sample transfer robot" });
  await page
    .getByLabel("Step 2 from")
    .selectOption({ label: "From Heating station" });
  await page.getByLabel("Step 2 to").selectOption({ label: "To Plate reader" });
  await page.getByLabel("Step 1 volume").fill("150");
  await page.getByRole("button", { name: "Save workflow" }).click();
  await expect(
    page.getByRole("button", { name: "Save workflow" }),
  ).toBeDisabled();

  await page.getByRole("tab", { name: "4 · Layout" }).click();
  // Pin the heater somewhere the default layout does not put it.
  await page.getByRole("button", { name: /^Heating station at x/ }).focus();
  await page.getByLabel("Heating station x").fill("-0.6");
  await page.getByLabel("Heating station z").fill("-0.3");
  await page.getByLabel("Keep here when searching").check();
  await expect(
    page.getByRole("radio", { name: "Around 1 kept" }),
  ).toBeChecked();
  await page.getByRole("button", { name: "Search layouts" }).click();
  const first = page.getByRole("button", { name: /^Layout \d+/ }).first();
  await expect(first).toContainText("s run", { timeout: 60_000 });
  await expect(first).toContainText("cm reach margin");
  await page.getByRole("button", { name: "Stop" }).click();
  await expect(
    page.getByText(/layouts? from \d+ of \d+ starting/),
  ).toBeVisible();
  // Every metric can order the list; dominated layouts are hidden by default.
  await page.getByLabel("Sort by").selectOption("clearance_m");
  await expect(page.getByLabel("Best trade-offs only")).toBeChecked();
  // Replanning with every instrument 2 cm off scores how forgiving a layout is.
  await page.getByRole("button", { name: "Stress test" }).click();
  await expect(
    page.getByText(/holds \d+% of 2 cm misplacements/).first(),
  ).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "Stop test" }).click();
  await expect(
    page.getByLabel("Sort by").getByRole("option", {
      name: "Placement tolerance",
    }),
  ).toBeAttached();
  const option = page.getByRole("button", { name: /^Layout \d+/ }).first();
  await option.click();
  await expect(option).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByRole("button", { name: /^Heating station at x/ }),
  ).toHaveAttribute("aria-label", /x -0\.6 m, z -0\.3 m/);
  const path = page.getByRole("button", {
    name: /Step 2 · Heating station → Plate reader/,
  });
  await expect(path).toContainText("cm min clearance");
  await page.getByRole("button", { name: "Save layout" }).click();
  await expect(
    page.getByRole("button", { name: "Save layout" }),
  ).toBeDisabled();
  await page.screenshot({
    path: "/tmp/academy-instruments-layout-search.png",
    fullPage: true,
  });
  // Kept instruments are saved with the layout.
  await page.reload();
  await page.getByRole("button", { name: /^Heating station at x/ }).focus();
  await expect(page.getByLabel("Keep here when searching")).toBeChecked();

  // Too small a bench is explained instead of returning a broken layout.
  await page.getByRole("radio", { name: "Whole bench" }).check();
  await page.getByLabel("Bench width (m)").fill("0.8");
  await page.getByLabel("Bench depth (m)").fill("0.6");
  await page.getByRole("button", { name: "Search layouts" }).click();
  await expect(page.getByText(/No feasible layout/)).toBeVisible({
    timeout: 60_000,
  });
  expect(errors).toEqual([]);
});

test("browser fixture only: a drafted description lists roles and guides instrument choice", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const brief = {
    id: "b1",
    text: "Heat a plate to 37 °C, then read it.",
    status: "draft",
    message: "",
    bindings: {},
    draft: {
      roles: [
        {
          key: "heater",
          name: "Heating station",
          operations: ["load", "heat"],
          vessel: "plate",
          query: "plate heater",
        },
        {
          key: "reader",
          name: "Plate reader",
          operations: ["load", "read"],
          vessel: "plate",
          query: "microplate reader",
        },
      ],
      steps: [
        {
          role: "heater",
          operation: "load",
          source_role: "",
          target_role: "",
          value: 150,
        },
        {
          role: "heater",
          operation: "heat",
          source_role: "",
          target_role: "",
          value: 37,
        },
      ],
      assumptions: ["Four plates reduced to one tracked sample."],
    },
  };
  // Every catalog the server returns carries the drafted brief.
  await page.route("**/api/twins**", async (route) => {
    const response = await route.fetch();
    const body = await response.json().catch(() => null);
    if (!body || !Array.isArray(body.twins)) return route.fulfill({ response });
    await route.fulfill({
      response,
      json: { ...body, brief, astra_available: true },
    });
  });
  await openInstruments(page);
  await page.getByRole("tab", { name: "1 · Describe" }).click();
  await expect(page.getByLabel("Workflow description")).toHaveValue(brief.text);
  await expect(page.getByRole("button", { name: "Redraft" })).toBeEnabled();
  const roles = page.getByRole("region", { name: "Instrument roles" });
  await expect(roles.getByText("Heating station")).toBeVisible();
  await expect(roles.getByText("Not chosen")).toHaveCount(2);
  await expect(
    page
      .getByRole("region", { name: "Drafted steps" })
      .getByText("Heating station · Heat 37 °C"),
  ).toBeVisible();
  await page.getByText("Assumptions").click();
  await expect(
    page.getByText("Four plates reduced to one tracked sample."),
  ).toBeVisible();

  await page.getByRole("button", { name: /Choose instruments/ }).click();
  const bindings = page.getByRole("region", {
    name: "Instruments for your workflow",
  });
  await expect(bindings.getByLabel("Plate reader instrument")).toHaveValue("");
  await bindings.getByRole("button", { name: "Find" }).last().click();
  await expect(page.getByLabel("Search the asset library")).toHaveValue(
    "microplate reader",
  );
  await expect(
    bindings.getByRole("button", { name: "Find" }).last(),
  ).toHaveAttribute("aria-pressed", "true");
  // The workflow tab says what is missing before drafted steps can be used.
  await page
    .getByRole("button", { name: "Heating station", exact: true })
    .click();
  await page.getByRole("button", { name: "Confirm twin" }).click();
  await page.getByRole("tab", { name: "3 · Workflow" }).click();
  await expect(
    page.getByRole("button", { name: "Use drafted steps" }),
  ).toBeDisabled();
  await expect(
    page.getByText("Choose an instrument for Heating station."),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("tab", { name: "2 · Instruments" }).click();
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
  await page.screenshot({
    path: "/tmp/academy-plan-roles-mobile.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
