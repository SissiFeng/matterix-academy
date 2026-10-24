import { expect, test, type Page } from "@playwright/test";

async function enter(page: Page) {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Morgan");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await expect(
    page.getByRole("heading", { name: "Welcome to the lab, Morgan." }),
  ).toBeVisible();
}

async function connect(page: Page) {
  await page.getByRole("button", { name: "Sim → Real", exact: true }).click();
  await page
    .getByRole("button", { name: "Connect an instrument", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Connect your instrument." }),
  ).toBeVisible();
  await expect(page.getByLabel("Instrument connection name")).toBeVisible();
}

async function create(page: Page, model: "Flex" | "OT-2" = "Flex") {
  await page
    .getByRole("radio", { name: `Opentrons ${model}`, exact: true })
    .check();
  await page
    .getByLabel("Instrument connection name")
    .fill(`Teaching bench ${model}`);
  await page
    .getByRole("button", { name: "Save instrument connection", exact: true })
    .click();
  await expect(page).toHaveURL(/#\/connect\/[a-f0-9-]+$/);
  await expect(
    page.getByRole("button", { name: "Create pairing code", exact: true }),
  ).toBeEnabled();
  return page.url().split("/").at(-1)!;
}

test("real local API: save, refresh, pair, expire and revoke without claiming instrument readiness", async ({
  page,
}, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await enter(page);
  await connect(page);
  await expect(
    page.getByLabel("Connected computer’s operating system"),
  ).toHaveValue("macos");
  await expect(
    page.getByRole("button", { name: "Download companion", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("checkbox", { name: /I am using the computer connected/ })
    .check();
  await expect(
    page.getByRole("button", { name: "Download companion", exact: true }),
  ).toBeDisabled();
  const id = await create(page);
  await page.screenshot({
    path: testInfo.outputPath("connector-setup-desktop.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Create pairing code", exact: true })
    .click();
  const code = await page
    .getByLabel("Pairing code", { exact: true })
    .textContent();
  expect(code).toBeTruthy();
  expect(page.url()).not.toContain(code);
  const stored = await page.evaluate(() =>
    JSON.stringify({
      local: { ...localStorage },
      session: { ...sessionStorage },
    }),
  );
  expect(stored).not.toContain(code);
  const saved = await page.request.get(`/api/connections/${id}`);
  expect(saved.ok()).toBe(true);
  expect(await saved.json()).toMatchObject({
    status: "pairing",
    qualified: false,
    probe: null,
  });
  await page.reload();
  await expect(page.getByLabel("Instrument connection name")).toHaveValue(
    "Teaching bench Flex",
  );
  await expect(page.getByLabel("Pairing code", { exact: true })).toHaveCount(0);
  await page
    .getByRole("button", { name: "Create a new pairing code", exact: true })
    .click();
  await expect(page.getByLabel("Pairing code", { exact: true })).toBeVisible();
  const replacement = await page
    .getByLabel("Pairing code", { exact: true })
    .textContent();
  expect(replacement).not.toBe(code);
  await page.clock.install();
  await page.clock.fastForward(601_000);
  await expect(
    page.getByText(
      "This pairing code has expired. Create a new code to continue.",
    ),
  ).toBeVisible();
  await expect(page.getByLabel("Pairing code", { exact: true })).toHaveCount(0);
  await page
    .getByRole("button", { name: "Revoke this pairing", exact: true })
    .click();
  await expect(
    page.getByText(
      "This computer’s pairing has been revoked. Revocation is not a physical emergency stop.",
    ),
  ).toBeVisible();
  await page.reload();
  expect(
    await (await page.request.get(`/api/connections/${id}`)).json(),
  ).toMatchObject({ status: "revoked", qualified: false });
  await expect(
    page.getByRole("button", { name: "Request physical run", exact: true }),
  ).toBeDisabled();
  expect(errors).toEqual([]);
});

test("real local API: OT-2 connection fits a phone and remains blocked without native evidence", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await enter(page);
  await connect(page);
  const id = await create(page, "OT-2");
  const saved = await (await page.request.get(`/api/connections/${id}`)).json();
  expect(saved.instrument).toBe("ot2");
  await page
    .getByRole("button", { name: "Refresh read-only checks", exact: true })
    .click();
  await expect(
    page.getByText("No instrument report has been received."),
  ).toBeVisible();
  await expect(
    page.getByText("Not qualified for physical execution."),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("connector-setup-mobile.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("real local API: a saved Studio design opens setup, but teaching completion cannot enable a physical run", async ({
  page,
}) => {
  await enter(page);
  await page
    .getByRole("button", { name: "Meet the instruments", exact: true })
    .click();
  const stories = page.getByTestId("instrument-stories");
  await stories
    .getByRole("button", { name: "Opentrons Flex", exact: true })
    .click();
  await stories.getByRole("button", { name: "Transfer", exact: true }).click();
  await stories
    .getByRole("button", { name: "Use this workflow", exact: true })
    .click();
  await expect(page.getByTestId("workflow-studio")).toBeVisible();
  const sessionId = page.url().split("/").at(-1)!;
  await page
    .getByRole("button", { name: "Run teaching simulation", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Teaching model checks", exact: true }),
  ).toBeVisible({ timeout: 25000 });
  await page
    .getByRole("button", { name: "Connect an instrument", exact: true })
    .click();
  await expect(page.getByLabel("Saved Studio workflow")).toHaveValue(sessionId);
  const id = await create(page);
  await expect(
    page.getByText("Physical run blocked", { exact: true }),
  ).toBeVisible();
  const response = await page.request.get(
    `/api/connections/${id}/preflight?session_id=${sessionId}`,
  );
  expect(response.ok()).toBe(true);
  const preflight = await response.json();
  expect(preflight.ready).toBe(false);
  expect(preflight.native_run_id).toBeNull();
  await expect(
    page.getByRole("button", { name: "Request physical run", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("checkbox", { name: /I have reviewed this exact workflow/ }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Open design & native Matterix", exact: true })
    .click();
  await expect(page).toHaveURL(new RegExp(`#\\/lab\\/${sessionId}$`));
  await expect(page.getByTestId("workflow-studio")).toBeVisible();
});

test("real local API: a lost save response is recovered by reading the original connection", async ({
  page,
}) => {
  await enter(page);
  await connect(page);
  let saves = 0;
  await page.route("**/api/connections/*", async (route) => {
    if (route.request().method() !== "PUT") return route.continue();
    saves += 1;
    const result = await route.fetch();
    expect(result.ok()).toBe(true);
    await route.abort("failed");
  });
  const id = await create(page);
  await expect(
    page.getByText(
      "The connection was saved. Its current state has been recovered.",
    ),
  ).toBeVisible();
  expect(saves).toBe(1);
  await page
    .getByRole("button", { name: "Refresh connection", exact: true })
    .click();
  expect(saves).toBe(1);
  expect(
    await (await page.request.get(`/api/connections/${id}`)).json(),
  ).toMatchObject({ display_name: "Teaching bench Flex", version: 1 });
});

test("real local API: stale pairing commands reconcile before an explicit retry", async ({
  page,
}) => {
  await enter(page);
  await connect(page);
  const id = await create(page);
  const connection = await (
    await page.request.get(`/api/connections/${id}`)
  ).json();
  const elsewhere = await page.request.post(`/api/connections/${id}/pairing`, {
    data: { expected_version: connection.version },
  });
  expect(elsewhere.ok()).toBe(true);
  await page
    .getByRole("button", { name: "Create pairing code", exact: true })
    .click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByLabel("Pairing code", { exact: true })).toHaveCount(0);
  await expect(
    page.getByRole("button", {
      name: "Create a new pairing code",
      exact: true,
    }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Create a new pairing code", exact: true })
    .click();
  await expect(page.getByLabel("Pairing code", { exact: true })).toBeVisible();
});

test("browser fixture only: uncertain physical submission is reconciled after refresh and never replayed", async ({
  page,
}) => {
  // Only the physical authority/readiness responses below are browser fixtures.
  // This test submits no connector command and proves no native or physical execution.
  await enter(page);
  await page
    .getByRole("button", { name: "Meet the instruments", exact: true })
    .click();
  const stories = page.getByTestId("instrument-stories");
  await stories
    .getByRole("button", { name: "Opentrons Flex", exact: true })
    .click();
  await stories.getByRole("button", { name: "Transfer", exact: true }).click();
  await stories
    .getByRole("button", { name: "Use this workflow", exact: true })
    .click();
  await expect(page.getByTestId("workflow-studio")).toBeVisible();
  const sessionId = page.url().split("/").at(-1)!;
  const session = await (
    await page.request.get(`/api/sessions/${sessionId}`)
  ).json();
  await page
    .getByRole("button", { name: "Connect an instrument", exact: true })
    .click();
  const id = await create(page);
  const connection = await (
    await page.request.get(`/api/connections/${id}`)
  ).json();
  const nativeRunId = "018f3b56-0f49-4efb-aa21-a44b7e7cccca";
  let submittedId = "";
  let submissions = 0;
  let receipts = 0;
  await page.route(`**/api/connections/${id}`, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    await route.fulfill({
      json: {
        ...connection,
        status: "paired",
        qualified: true,
        active_run_id: submittedId || null,
      },
    });
  });
  await page.route(`**/api/connections/${id}/preflight?*`, async (route) => {
    await route.fulfill({
      json: {
        ready: true,
        enabled: true,
        connection_id: id,
        session_id: sessionId,
        session_version: session.version,
        plan_hash: "a".repeat(64),
        native_run_id: nativeRunId,
        issues: [],
      },
    });
  });
  await page.route(`**/api/connections/${id}/runs`, async (route) => {
    expect(route.request().method()).toBe("POST");
    const body = route.request().postDataJSON();
    expect(body.acknowledge_physical_motion).toBe(true);
    expect(body.session_id).toBe(sessionId);
    expect(body.native_run_id).toBe(nativeRunId);
    submissions += 1;
    submittedId = body.run_id;
    await route.abort("failed");
  });
  await page.route(`**/api/connections/${id}/runs/*`, async (route) => {
    expect(route.request().method()).toBe("GET");
    receipts += 1;
    expect(route.request().url()).toContain(submittedId);
    await route.fulfill({
      json: {
        run_id: submittedId,
        connection_id: id,
        version: 2,
        status: "unknown",
        session_id: sessionId,
        native_run_id: nativeRunId,
        plan_hash: "a".repeat(64),
        instrument: "flex",
        created_at: Date.now() / 1000,
        updated_at: Date.now() / 1000,
        stop_requested: false,
        receipt: null,
        reason: "Browser fixture: physical outcome requires reconciliation.",
      },
    });
  });
  await page
    .getByRole("button", { name: "Refresh connection", exact: true })
    .click();
  await expect(
    page.getByText("Server preflight ready", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Request physical run", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("checkbox", { name: /I have reviewed this exact workflow/ })
    .check();
  await page
    .getByRole("button", { name: "Request physical run", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Physical run: unknown", exact: true }),
  ).toBeVisible();
  expect(submissions).toBe(1);
  expect(receipts).toBeGreaterThan(0);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Physical run: unknown", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Saved Studio workflow")).toHaveValue(sessionId);
  await expect(
    page.getByRole("button", { name: "Request physical run", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Refresh physical run", exact: true })
    .click();
  expect(submissions).toBe(1);
  // The local service contains the saved connection, but no physical run from this fixture.
  expect(
    (
      await page.request.get(`/api/connections/${id}/runs/${submittedId}`)
    ).status(),
  ).toBe(404);
});

test("browser fixture only: bound operator resolution survives refresh and permits a new run without replay", async ({
  page,
}) => {
  // Resolution and motion authority are fixtures. No physical command is sent.
  await enter(page);
  await page
    .getByRole("button", { name: "Meet the instruments", exact: true })
    .click();
  const stories = page.getByTestId("instrument-stories");
  await stories.getByRole("button", { name: "Transfer", exact: true }).click();
  await stories
    .getByRole("button", { name: "Use this workflow", exact: true })
    .click();
  await expect(page.getByTestId("workflow-studio")).toBeVisible();
  const sessionId = page.url().split("/").at(-1)!;
  const session = await (
    await page.request.get(`/api/sessions/${sessionId}`)
  ).json();
  await page
    .getByRole("button", { name: "Connect an instrument", exact: true })
    .click();
  const id = await create(page);
  const connection = await (
    await page.request.get(`/api/connections/${id}`)
  ).json();
  const oldRunId = "018f3b56-0f49-4efb-aa21-a44b7e7ccccb";
  const nativeRunId = "018f3b56-0f49-4efb-aa21-a44b7e7cccca";
  const planHash = "a".repeat(64);
  const audit = {
    request: {
      expected_version: 2,
      resolution_id: "018f3b56-0f49-4efb-aa21-a44b7e7ccccc",
      connection_id: id,
      installation_id: "018f3b56-0f49-4efb-aa21-a44b7e7ccccd",
      plan_hash: planHash,
      instrument: "flex",
      protocol_id: "fixture-protocol",
      robot_run_id: "fixture-robot-run",
      no_run_created: false,
      stopped: true,
      released: true,
      operator_id: "fixture-operator",
      evidence_sha256: "b".repeat(64),
      detail: "Browser fixture: operator confirmed stopped and released.",
    },
    resolved_at: Date.now() / 1000,
    historical_status: "unknown",
    replay_authorized: false,
  };
  let resolution: typeof audit | null = null;
  let returnedRunId = oldRunId;
  let freshPreflight = true;
  const submissions: string[] = [];
  await page.route(`**/api/connections/${id}`, async (route) => {
    await route.fulfill({
      json: {
        ...connection,
        status: "paired",
        qualified: true,
        active_run_id: null,
      },
    });
  });
  await page.route(`**/api/connections/${id}/preflight?*`, async (route) => {
    await route.fulfill({
      json: {
        ready: freshPreflight,
        enabled: true,
        connection_id: id,
        session_id: sessionId,
        session_version: session.version,
        plan_hash: planHash,
        native_run_id: nativeRunId,
        issues: freshPreflight
          ? []
          : [{ code: "probe", message: "Fixture: waiting for fresh checks" }],
      },
    });
  });
  const snapshot = () => ({
    run_id: returnedRunId,
    connection_id: id,
    version: 3,
    status: "unknown",
    session_id: sessionId,
    native_run_id: nativeRunId,
    plan_hash: planHash,
    instrument: "flex",
    created_at: Date.now() / 1000,
    updated_at: Date.now() / 1000,
    stop_requested: true,
    receipt: null,
    reason: "Browser fixture: original physical outcome remains unknown.",
    resolution,
  });
  await page.route(`**/api/connections/${id}/runs/*`, async (route) => {
    expect(route.request().method()).toBe("GET");
    await route.fulfill({ json: snapshot() });
  });
  await page.route(`**/api/connections/${id}/runs`, async (route) => {
    expect(route.request().method()).toBe("POST");
    const body = route.request().postDataJSON();
    submissions.push(body.run_id);
    expect(body.run_id).not.toBe(oldRunId);
    expect(body.acknowledge_physical_motion).toBe(true);
    returnedRunId = body.run_id;
    resolution = null;
    await route.fulfill({
      json: { ...snapshot(), status: "queued", version: 1 },
    });
  });
  await page.evaluate(
    ({ id, oldRunId, sessionId }) => {
      sessionStorage.setItem(`academy-physical-run-v1:${id}`, oldRunId);
      sessionStorage.setItem(`academy-connector-workflow-v1:${id}`, sessionId);
    },
    { id, oldRunId, sessionId },
  );
  await page.reload();
  const requestRun = page.getByRole("button", {
    name: "Request physical run",
    exact: true,
  });
  const consent = page.getByRole("checkbox", {
    name: /I have reviewed this exact workflow/,
  });
  await expect(
    page.getByRole("heading", { name: "Physical run: unknown", exact: true }),
  ).toBeVisible();
  await expect(consent).toBeDisabled();
  const refresh = () =>
    page
      .getByRole("button", { name: "Refresh physical run", exact: true })
      .click();
  for (const invalid of [
    {
      ...audit,
      request: { ...audit.request, connection_id: "another-connection" },
    },
    { ...audit, request: { ...audit.request, plan_hash: "c".repeat(64) } },
    { ...audit, replay_authorized: true },
    { ...audit, request: { ...audit.request, released: false } },
  ]) {
    resolution = invalid;
    await refresh();
    await expect(consent).toBeDisabled();
    await expect(requestRun).toBeDisabled();
  }
  resolution = audit;
  returnedRunId = "018f3b56-0f49-4efb-aa21-a44b7e7cccce";
  await refresh();
  await expect(consent).toBeDisabled();
  returnedRunId = oldRunId;
  freshPreflight = false;
  await refresh();
  await expect(
    page.getByText(
      /An operator verified that this instrument is stopped and released/,
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Physical run: unknown", exact: true }),
  ).toBeVisible();
  await expect(requestRun).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Request instrument stop", exact: true }),
  ).toHaveCount(0);
  freshPreflight = true;
  await page.reload();
  await expect(
    page.getByText(
      /An operator verified that this instrument is stopped and released/,
    ),
  ).toBeVisible();
  await expect(consent).toBeEnabled();
  await expect(consent).not.toBeChecked();
  await expect(requestRun).toBeDisabled();
  expect(submissions).toEqual([]);
  await consent.check();
  await requestRun.click();
  expect(submissions).toHaveLength(1);
  expect(submissions[0]).not.toBe(oldRunId);
});

test("published download refreshes its temporary URL after a long setup pause", async ({
  page,
}) => {
  await enter(page);
  let catalogs = 0;
  await page.route("**/api/connectors/catalog**", async (route) => {
    const source = await (await route.fetch()).json();
    catalogs += 1;
    await route.fulfill({
      json: {
        ...source,
        companion: {
          status: "available",
          platforms: ["macos"],
          version: "0.2.0",
          reason:
            "Reviewed desktop package fixture; no installation is executed.",
          download_url: `https://private-packages.example/bridge-${catalogs}.zip`,
        },
      },
    });
  });
  let requested = "";
  await page.route("https://private-packages.example/**", async (route) => {
    requested = route.request().url();
    expect(route.request().headers().authorization).toBeUndefined();
    expect(route.request().headers().referer).toBeUndefined();
    await route.fulfill({
      status: 200,
      body: "DOWNLOAD TEST FIXTURE ONLY",
      headers: {
        "Content-Type": "application/zip",
        "Content-Disposition": 'attachment; filename="fixture.zip"',
      },
    });
  });
  await connect(page);
  await page
    .getByRole("checkbox", { name: /I am using the computer connected/ })
    .check();
  await page.clock.install();
  await page.clock.fastForward(601_000);
  const download = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download companion for macOS", exact: true })
    .click();
  await download;
  expect(catalogs).toBe(2);
  expect(requested).toBe("https://private-packages.example/bridge-2.zip");
  await expect(
    page.getByRole("heading", { name: "Connect your instrument." }),
  ).toBeVisible();
});
