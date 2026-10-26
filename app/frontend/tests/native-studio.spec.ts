import { expect, test, type Page } from "@playwright/test";
import type { Session } from "../src/types";
import type { SimulationRun } from "../src/simulationTypes";
import { makeStudioExperiment } from "../src/studioContent";
import { readFile } from "node:fs/promises";

async function savedStudio(page: Page, instrument: "flex" | "ot2" = "flex") {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Native studio learner");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  const experiment = makeStudioExperiment(instrument, "transfer");
  experiment.actions[1].volume = 75;
  experiment.actions[2].volume = 75;
  const response = await page.request.post("/api/sessions", {
    data: experiment,
  });
  expect(response.ok()).toBe(true);
  return (await response.json()) as Session;
}

function fixtureRun(session: Session, runId: string) {
  return {
    run_id: runId,
    session_id: session.id,
    version: 1,
    status: "queued",
    plan_hash: "a".repeat(64),
    scene: "workflow-studio-flex",
    instrument: "flex",
    evidence: "pending",
    completed_steps: 0,
    total_steps: session.experiment.actions.length,
    stale_seconds: 0,
    supported_controls: [],
    control: null,
    cleanup: null as { reset_verified: boolean } | null,
    snapshot: null as SimulationRun["snapshot"],
  };
}

function preflight(session: Session, ready = true) {
  return {
    session_id: session.id,
    session_version: session.version,
    plan_hash: "a".repeat(64),
    instrument: session.experiment.instrument,
    scene: `workflow-studio-${session.experiment.instrument}`,
    enabled: true,
    ready,
    message: ready
      ? "A fixture worker supports this exact saved plan."
      : "The previous run is reserved until native reset is verified.",
    issues: ready
      ? []
      : [{ code: "active_run", message: "Verified native reset is required." }],
  };
}

test("commissioning export preserves attempted submission across reload and labels missing video incomplete", async ({
  page,
}) => {
  // Synthetic UI contract only: no GPU, real account or rendered video evidence.
  let session = await savedStudio(page);
  let run: ReturnType<typeof fixtureRun> | null = null;
  let posts = 0;
  let reportUnavailable = false;
  const grantId = "11111111-1111-4111-8111-111111111111";
  await page.route(`**/api/sessions/${session.id}`, (route) =>
    route.fulfill({ json: session }),
  );
  await page.route(`**/api/sessions/${session.id}/native-preflight`, (route) =>
    route.fulfill({
      json: { ...preflight(session, !run), commissioning: true },
    }),
  );
  await page.route(`**/api/sessions/${session.id}/remote-run`, (route) =>
    route.fulfill({ json: run }),
  );
  await page.route("**/api/commissioning/report", (route) =>
    reportUnavailable
      ? route.fulfill({ status: 503, json: { detail: "Fixture outage" } })
      : route.fulfill({
          json: {
            grant_id: grantId,
            expires: 9999999999,
            worker_qualified: false,
            runs: run ? [{ run, browser: null }] : [],
          },
        }),
  );
  await page.route("**/api/runs", async (route) => {
    posts++;
    const saved = await page.evaluate(
      (id) =>
        JSON.parse(sessionStorage.getItem(`academy.studio-evidence.${id}`)!),
      grantId,
    );
    expect(saved.submissions).toHaveLength(1); // Persisted before the POST reached the server.
    const request = route.request().postDataJSON();
    expect(saved.submissions[0].run_id).toBe(request.run_id);
    run = fixtureRun(session, request.run_id);
    session = {
      ...session,
      version: session.version + 1,
      remote_active_run: run.run_id,
    };
    await route.fulfill({ status: 201, json: run });
  });
  await page.goto(`/#/lab/${session.id}`);
  await page.reload();
  const panel = page.getByTestId("native-studio-run");
  await panel
    .getByRole("button", {
      name: "Run saved workflow in Matterix",
      exact: true,
    })
    .click();
  await expect.poll(() => posts).toBe(1);
  // Wait for the fixture's persistence assertion and accepted response before reloading.
  await expect(
    panel.getByText("Waiting for a qualified worker", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    panel.getByText("Waiting for a qualified worker", { exact: true }),
  ).toBeVisible();
  await panel.getByText("Acceptance evidence", { exact: true }).click();
  const downloading = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Download acceptance evidence", exact: true })
    .click();
  const download = await downloading;
  const report = JSON.parse(await readFile((await download.path())!, "utf8"));
  expect(report.status).toBe("incomplete");
  expect(report.submission_posts).toBe(1);
  expect(report.refresh_verified).toBe(false);
  expect(report.browser_runs[0].frames_decoded).toBe(0);
  expect(report.browser_runs[0].relay_verified).toBe(false);
  expect(report.server_report.runs[0].run.run_id).toBe(run!.run_id);
  expect(posts).toBe(1);
  await expect(
    panel
      .getByRole("status")
      .filter({ hasText: "Downloaded incomplete evidence" }),
  ).toBeVisible();
  reportUnavailable = true;
  await panel
    .getByRole("button", { name: "Download acceptance evidence", exact: true })
    .click();
  await expect(
    panel.getByRole("status").filter({ hasText: "could not be downloaded" }),
  ).toBeVisible();
  expect(posts).toBe(1);
  await panel.screenshot({ path: "/tmp/academy-commissioning-evidence.png" });
});

test("unqualified studio offers teaching without claiming native support", async ({
  page,
}) => {
  const session = await savedStudio(page, "ot2");
  let posts = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      new URL(request.url()).pathname === "/api/runs"
    )
      posts++;
  });
  await page.goto(`/#/lab/${session.id}`);
  await page.reload();
  const panel = page.getByTestId("native-studio-run");
  await expect(
    panel.getByText("Native execution is unavailable for this saved workflow", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    panel.getByRole("button", {
      name: "Run saved workflow in Matterix",
      exact: true,
    }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Run teaching simulation", exact: true }),
  ).toBeEnabled();
  await expect(
    panel.getByText("No native result yet", { exact: true }),
  ).toBeVisible();
  await expect(panel.locator("video")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Native Matterix", exact: true })
    .click();
  await expect(
    page.getByLabel("Native simulation controls", { exact: true }),
  ).toBeFocused();
  await panel.screenshot({
    path: "/tmp/academy-native-studio-unavailable.png",
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    )
    .toBe(true);
  await page
    .getByRole("button", { name: "Native Matterix", exact: true })
    .click();
  await expect(
    panel.getByRole("heading", { name: "Matterix simulation" }),
  ).toBeInViewport();
  await page.screenshot({
    path: "/tmp/academy-native-studio-unavailable-mobile.png",
  });
  expect(posts).toBe(0);
  await expect(
    panel.getByText("Acceptance evidence", { exact: true }),
  ).toHaveCount(0);
});

test("native UI fixture submits the saved revision once, restores its viewport, waits for reset and permits a second manual run", async ({
  page,
}) => {
  // Contract fixture only: this test never provisions a worker or renders Isaac frames.
  const original = await savedStudio(page);
  let session = structuredClone(original);
  let run: ReturnType<typeof fixtureRun> | null = null;
  const submissions: {
    run_id: string;
    session_id: string;
    expected_version: number;
  }[] = [];
  const viewerRuns: string[] = [];
  await page.route(`**/api/sessions/${session.id}`, (route) =>
    route.fulfill({ json: session }),
  );
  await page.route(`**/api/sessions/${session.id}/native-preflight`, (route) =>
    route.fulfill({ json: preflight(session, !session.remote_active_run) }),
  );
  await page.route(`**/api/sessions/${session.id}/remote-run`, (route) =>
    route.fulfill({ json: run }),
  );
  await page.route("**/api/runs", async (route) => {
    const request = route.request().postDataJSON();
    submissions.push(request);
    expect(request.session_id).toBe(session.id);
    expect(request.expected_version).toBe(session.version);
    expect(Object.keys(request).sort()).toEqual([
      "expected_version",
      "run_id",
      "session_id",
    ]);
    run = fixtureRun(session, request.run_id);
    session = {
      ...session,
      version: session.version + 1,
      remote_active_run: request.run_id,
    };
    await route.fulfill({ status: 201, json: run });
  });
  await page.route("**/api/runs/*/viewer", async (route) => {
    viewerRuns.push(new URL(route.request().url()).pathname.split("/")[3]);
    await route.fulfill({
      status: 503,
      json: { detail: "Fixture has no rendered video" },
    });
  });
  await page.goto(`/#/lab/${session.id}`);
  await page.reload();
  const panel = page.getByTestId("native-studio-run");
  const submit = panel.getByRole("button", {
    name: "Run saved workflow in Matterix",
    exact: true,
  });
  await expect(submit).toBeEnabled();
  await submit.click();
  await expect(
    panel.getByText("Waiting for a qualified worker", { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Workflow name")).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Run teaching simulation", exact: true }),
  ).toBeDisabled();
  expect(submissions).toHaveLength(1);
  run = { ...run!, status: "running", version: 2 };
  await panel
    .getByRole("button", { name: "Check connection", exact: true })
    .click();
  await expect(
    panel.getByText("Running in Matterix", { exact: true }),
  ).toBeVisible();
  await expect(
    panel.getByRole("region", { name: "Isaac live viewport", exact: true }),
  ).toBeVisible();
  await expect(
    panel
      .getByText("Live video is unavailable. The run state remains separate.", {
        exact: true,
      })
      .first(),
  ).toBeVisible();
  expect(viewerRuns).toEqual([run.run_id]);
  await page.reload();
  await expect(
    panel.getByText("Running in Matterix", { exact: true }),
  ).toBeVisible();
  await expect(panel.locator("video")).toHaveJSProperty("srcObject", null);
  expect(submissions).toHaveLength(1);
  expect(
    await page.getByLabel("Step 2 volume", { exact: true }).inputValue(),
  ).toBe("75");
  run = {
    ...run!,
    status: "completed",
    version: 3,
    completed_steps: 4,
    evidence: "native",
    snapshot: {
      run_id: run!.run_id,
      session_id: session.id,
      plan_hash: "a".repeat(64),
      sequence: 4,
      status: "completed",
      observed_at: "2026-10-23T12:00:00Z",
      engine_version: "fixture-only",
      asset_version: "fixture-only",
      error: null,
      steps: Array.from({ length: 4 }, (_, index) => ({
        index,
        status: "completed",
      })),
      native_state: {
        revision: 4,
        observed_at: "2026-10-23T12:00:00Z",
        simulation_tick: 50,
        pipette_volume_ul: 0,
        tip_attached: false,
        well_volumes_ul: { stock: 925, A1: 75, A2: 0, A3: 0 },
        mixing: null,
        studio: {
          instrument: "flex",
          scene: "workflow-studio-flex",
          observation_model: "native-semantic",
          labware_slots: { stock: "D1", plate: "D2", tips: "B1", waste: "D3" },
          waste_volume_ul: 0,
          native_action_index: 12,
          native_action_count: 12,
          native_action: "tip discarded",
        },
      },
    },
  };
  await panel
    .getByRole("button", { name: "Check connection", exact: true })
    .click();
  await expect(
    panel.getByText(
      "The workflow remains reserved until the worker verifies native cleanup and reset.",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(page.getByLabel("Workflow name")).toBeDisabled();
  await expect(panel.getByText("925 µL", { exact: true })).toBeVisible();
  await expect(panel.getByText("75 µL", { exact: true })).toBeVisible();
  await expect(
    panel.getByText(/Native motion and semantic liquid accounting/),
  ).toBeVisible();
  await expect(
    panel.getByText(/not validated fluid physics or chemistry/),
  ).toBeVisible();
  run = { ...run, version: 4, cleanup: { reset_verified: true } };
  session = {
    ...session,
    version: session.version + 1,
    remote_active_run: null,
  };
  await panel
    .getByRole("button", { name: "Check connection", exact: true })
    .click();
  await expect(page.getByLabel("Workflow name")).toBeEnabled();
  await panel
    .getByRole("button", { name: "Run saved workflow again", exact: true })
    .click();
  await expect(
    panel.getByText("Waiting for a qualified worker", { exact: true }),
  ).toBeVisible();
  expect(submissions).toHaveLength(2);
  expect(submissions[1].run_id).not.toBe(submissions[0].run_id);
});

test("an uncertain native submission remains locked across refresh and repeated 404 reads without another POST", async ({
  page,
}) => {
  const session = await savedStudio(page);
  let submissions = 0;
  let lookups = 0;
  await page.route(`**/api/sessions/${session.id}/native-preflight`, (route) =>
    route.fulfill({ json: preflight(session) }),
  );
  await page.route(`**/api/sessions/${session.id}/remote-run`, (route) =>
    route.fulfill({ json: null }),
  );
  await page.route("**/api/runs", async (route) => {
    submissions++;
    await route.abort();
  });
  await page.route(/\/api\/runs\/[a-f0-9-]{36}$/, async (route) => {
    lookups++;
    await route.fulfill({ status: 404, json: { detail: "Not found yet" } });
  });
  await page.goto(`/#/lab/${session.id}`);
  await page.reload();
  const panel = page.getByTestId("native-studio-run");
  await panel
    .getByRole("button", {
      name: "Run saved workflow in Matterix",
      exact: true,
    })
    .click();
  await expect(
    panel.getByText(/A previous submission is unresolved/),
  ).toBeVisible();
  await expect(page.getByLabel("Workflow name")).toBeDisabled();
  await panel
    .getByRole("button", { name: "Check connection", exact: true })
    .click();
  await page.reload();
  await expect(
    panel.getByText(/A previous submission is unresolved/),
  ).toBeVisible();
  await panel
    .getByRole("button", { name: "Check connection", exact: true })
    .click();
  await expect(
    panel.getByRole("button", {
      name: "Run saved workflow in Matterix",
      exact: true,
    }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Run teaching simulation", exact: true }),
  ).toBeDisabled();
  await expect.poll(() => lookups).toBeGreaterThan(1);
  expect(submissions).toBe(1);
});

test("dirty saved-plan checks cannot launch and a preflight mismatch never replaces the design", async ({
  page,
}) => {
  const session = await savedStudio(page, "ot2");
  let submissions = 0;
  await page.route(`**/api/sessions/${session.id}/native-preflight`, (route) =>
    route.fulfill({
      json: {
        ...preflight(session, false),
        message: "No qualified OT-2 scene supports this deck.",
        issues: [
          {
            code: "slot",
            message: "The worker does not support stock in slot 1.",
          },
        ],
      },
    }),
  );
  await page.route("**/api/runs", async (route) => {
    submissions++;
    await route.abort();
  });
  await page.goto(`/#/lab/${session.id}`);
  await page.reload();
  const panel = page.getByTestId("native-studio-run");
  await expect(
    panel.getByText("The worker does not support stock in slot 1.", {
      exact: true,
    }),
  ).toBeVisible();
  await page.getByLabel("Step 2 volume", { exact: true }).fill("60");
  await expect(
    panel.getByText("Save your changes to check and run this exact workflow.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    panel.getByRole("button", {
      name: "Run saved workflow in Matterix",
      exact: true,
    }),
  ).toBeDisabled();
  await panel
    .getByRole("button", { name: "Check connection", exact: true })
    .click();
  await expect(page.getByLabel("Step 2 volume", { exact: true })).toHaveValue(
    "60",
  );
  await expect(
    page.getByRole("button", { name: "Run teaching simulation", exact: true }),
  ).toBeEnabled();
  expect(submissions).toBe(0);
});

test("automatic polling recovery clears a transient connection alert after an earlier successful check", async ({
  page,
}) => {
  const session = await savedStudio(page);
  await page.clock.install();
  let unavailable = false;
  let posts = 0;
  await page.route(`**/api/sessions/${session.id}/native-preflight`, (route) =>
    unavailable
      ? route.fulfill({
          status: 503,
          json: { detail: "Connection temporarily interrupted" },
        })
      : route.fulfill({ json: preflight(session) }),
  );
  await page.route(`**/api/sessions/${session.id}/remote-run`, (route) =>
    route.fulfill({ json: null }),
  );
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      new URL(request.url()).pathname === "/api/runs"
    )
      posts++;
  });
  await page.goto(`/#/lab/${session.id}`);
  await page.reload();
  const panel = page.getByTestId("native-studio-run");
  const submit = panel.getByRole("button", {
    name: "Run saved workflow in Matterix",
    exact: true,
  });
  await expect(submit).toBeEnabled();
  unavailable = true;
  await page.clock.runFor(8001);
  await expect(panel.getByRole("alert")).toHaveText(
    "Connection temporarily interrupted",
  );
  await expect(submit).toBeDisabled();
  unavailable = false;
  await page.clock.runFor(8001);
  await expect(submit).toBeEnabled();
  await expect(panel.getByRole("alert")).toHaveCount(0);
  await expect(panel.getByText(/Connection checks are delayed/)).toHaveCount(0);
  expect(posts).toBe(0);
});

test("an accepted native run stays confirmed and locked when the subsequent session read fails", async ({
  page,
}) => {
  let session = await savedStudio(page);
  await page.clock.install();
  let run: ReturnType<typeof fixtureRun> | null = null;
  let sessionReadFails = false;
  let posts = 0;
  await page.route(`**/api/sessions/${session.id}`, (route) =>
    sessionReadFails
      ? route.fulfill({
          status: 500,
          json: { detail: "Saved workflow details temporarily unavailable" },
        })
      : route.fulfill({ json: session }),
  );
  await page.route(`**/api/sessions/${session.id}/native-preflight`, (route) =>
    route.fulfill({ json: preflight(session, !run) }),
  );
  await page.route(`**/api/sessions/${session.id}/remote-run`, (route) =>
    route.fulfill({ json: run }),
  );
  await page.route("**/api/runs", async (route) => {
    posts++;
    run = fixtureRun(session, route.request().postDataJSON().run_id);
    session = {
      ...session,
      version: session.version + 1,
      remote_active_run: run.run_id,
    };
    sessionReadFails = true;
    await route.fulfill({ status: 201, json: run });
  });
  await page.goto(`/#/lab/${session.id}`);
  await page.reload();
  const panel = page.getByTestId("native-studio-run");
  await page.evaluate(() => {
    const messages: string[] = [];
    (window as Window & { observedAlerts?: string[] }).observedAlerts =
      messages;
    new MutationObserver(() => {
      document
        .querySelectorAll('[role="alert"]')
        .forEach((element) => messages.push(element.textContent ?? ""));
    }).observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
    });
  });
  await panel
    .getByRole("button", {
      name: "Run saved workflow in Matterix",
      exact: true,
    })
    .click();
  await expect(
    panel.getByText("Waiting for a qualified worker", { exact: true }),
  ).toBeVisible();
  await expect(panel.getByRole("alert")).toHaveText(
    "Saved workflow details temporarily unavailable",
  );
  await expect(page.getByLabel("Workflow name")).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Run teaching simulation", exact: true }),
  ).toBeDisabled();
  await expect(
    panel.getByRole("button", {
      name: "Run saved workflow in Matterix",
      exact: true,
    }),
  ).toBeDisabled();
  const alerts = await page.evaluate(
    () =>
      (window as Window & { observedAlerts?: string[] }).observedAlerts ?? [],
  );
  expect(alerts.some((text) => text.includes("No run was submitted"))).toBe(
    false,
  );
  expect(posts).toBe(1);
  sessionReadFails = false;
  await page.clock.runFor(2001);
  await expect(panel.getByRole("alert")).toHaveCount(0);
  await expect(
    panel.getByText("Waiting for a qualified worker", { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Workflow name")).toBeDisabled();
  expect(posts).toBe(1);
});
