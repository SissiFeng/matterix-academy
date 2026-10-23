// Explicit live acceptance only. This may execute two native GPU runs and incur charges.
// Never run by default tests or CI. Login is manual; credentials remain in an ephemeral browser.
import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { chromium, expect } from "@playwright/test";
import {
  acceptanceOrigin,
  privateDirectory,
} from "./learner-acceptance-helpers.mjs";
import {
  captureRun,
  isFreshRecovery,
  videoUsesCurrentRelay,
} from "./commissioning-response.mjs";
import {
  checkedStudioRequest,
  checkSavedPlan,
  checkRunBinding,
  checkCompletedRun,
  checkServerReport,
} from "./studio-commissioning-contract.mjs";

const args = process.argv.slice(2);
const requestPath = args[args.indexOf("--request") + 1];
assert.ok(
  args.includes("--confirm-live") &&
    args.includes("--request") &&
    requestPath &&
    !requestPath.startsWith("--"),
  "Requires --confirm-live --request <reviewed operator JSON>. No live action was started.",
);
const origin = acceptanceOrigin(process.env.ACADEMY_COMMISSIONING_URL ?? "");
const request = checkedStudioRequest(
  JSON.parse(await readFile(requestPath, "utf8")),
);
const output = path.resolve(
  process.env.ACADEMY_COMMISSIONING_OUTPUT ??
    `../../build/commissioning/studio-${new Date().toISOString().replaceAll(":", "-")}`,
);
await privateDirectory(output);
const report = {
  schema: "academy.studio-browser-commissioning/1",
  status: "pending",
  grant_id: request.grant_id,
  submission_posts: 0,
  refresh_verified: false,
  browser_runs: [],
  server_report: null,
};
const reportPath = path.join(output, "browser-report.json");
await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", {
  mode: 0o600,
  flag: "wx",
});
const save = () =>
  writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", {
    mode: 0o600,
  });
const browser = await chromium.launch({ headless: false });
const context = await browser.newContext();
await context.addInitScript(() => {
  const NativePeer = window.RTCPeerConnection;
  window.__commissioningPeers = [];
  window.RTCPeerConnection = class extends NativePeer {
    constructor(config, constraints) {
      super(config, constraints);
      window.__commissioningPeers.push(this);
    }
  };
});
const page = await context.newPage();
let navigation = 0;
let sequence = 0;
let minimumSequence = 0;
let currentRunId;
let latest;
let recovery;
let recoveredRun;
let activeSession;
let responseFailure;
const origins = new WeakMap();
const pendingReads = new Set();
page.on("framenavigated", (frame) => {
  if (frame === page.mainFrame()) navigation++;
});
page.on("request", (req) => {
  origins.set(req, { navigation, sequence: ++sequence });
  const target = new URL(req.url());
  if (
    target.origin === origin &&
    target.pathname === "/api/runs" &&
    req.method() === "POST"
  )
    report.submission_posts++;
});
page.on("response", (response) => {
  const target = new URL(response.url());
  const req = response.request();
  if (
    target.origin !== origin ||
    !response.ok() ||
    !activeSession ||
    !(
      (req.method() === "POST" && target.pathname === "/api/runs") ||
      (req.method() === "GET" &&
        target.pathname === `/api/sessions/${activeSession.id}/remote-run`)
    )
  )
    return;
  const sent = origins.get(req);
  const boundSession = activeSession;
  const boundApproved = request.studio.plans[report.browser_runs.length];
  const reading = response
    .json()
    .then((value) => {
      if (
        !sent ||
        sent.sequence < minimumSequence ||
        sent.navigation !== navigation
      )
        return;
      if (value)
        checkRunBinding(value, boundSession, boundApproved, request.studio);
      if (
        recovery &&
        isFreshRecovery({
          method: req.method(),
          pathname: target.pathname,
          value,
          requestNavigation: sent.navigation,
          ...recovery,
        })
      )
        recoveredRun = value;
      ({ currentRunId, latest } = captureRun(
        req.method(),
        target.pathname,
        value,
        currentRunId,
        latest,
      ));
    })
    .catch((error) => {
      responseFailure = error;
    });
  pendingReads.add(reading);
  void reading.finally(() => pendingReads.delete(reading));
});
// The token is used only inside the authenticated browser and is never returned or logged.
async function authenticated(endpoint, method = "GET", body) {
  return page.evaluate(
    async ({ endpoint, method, body, subject }) => {
      const config = await (await fetch("/api/config")).json();
      if (config.auth !== "cognito")
        throw new Error("Real Cognito authentication is required");
      const user = JSON.parse(
        sessionStorage.getItem(
          `oidc.user:${config.issuer}:${config.client_id}`,
        ) ?? "null",
      );
      if (
        !user?.access_token ||
        user.profile?.sub !== subject ||
        user.expires_at * 1000 <= Date.now()
      )
        throw new Error(
          "Sign in with the exact operator-approved Cognito account",
        );
      const response = await fetch(endpoint, {
        method,
        headers: {
          Authorization: `Bearer ${user.access_token}`,
          ...(body ? { "Content-Type": "application/json" } : {}),
        },
        credentials: "same-origin",
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
      if (!response.ok)
        throw new Error(`Authenticated API returned ${response.status}`);
      return response.json();
    },
    { endpoint, method, body, subject: request.subject },
  );
}
const requireNoReplay = (expected) => {
  assert.equal(
    report.submission_posts,
    expected,
    "Native submission count changed; do not retry or replay this acceptance",
  );
  if (responseFailure) throw responseFailure;
};
try {
  await page.goto(origin);
  console.log(
    "Sign in manually with the operator-approved Cognito account and finish onboarding if needed. Waiting up to five minutes. No passwords or codes are collected.",
  );
  await expect
    .poll(
      async () => {
        try {
          return (await authenticated("/api/me")).onboarded === true;
        } catch {
          return false;
        }
      },
      { timeout: 300000 },
    )
    .toBe(true);
  const initial = await authenticated("/api/commissioning/report");
  assert.equal(
    initial.grant_id,
    request.grant_id,
    "The active grant differs from the reviewed file",
  );
  assert.deepEqual(
    initial.runs,
    [],
    "This harness requires an unused grant; reconcile earlier runs instead of retrying",
  );
  for (const [index, approved] of request.studio.plans.entries()) {
    report.stage = `plan-${index + 1}-save`;
    await save();
    // Creating a teaching session is not execution; native submission below must use the visible UI.
    const session = await authenticated(
      "/api/sessions",
      "POST",
      approved.experiment,
    );
    const preflight = await authenticated(
      `/api/sessions/${session.id}/native-preflight`,
    );
    checkSavedPlan(session, approved, preflight, request.studio);
    activeSession = session;
    currentRunId =
      latest =
      recovery =
      recoveredRun =
      responseFailure =
        undefined;
    minimumSequence = sequence + 1;
    await page.goto(`${origin}/#/lab/${session.id}`);
    await page.reload(); // Exercise a durable deep link, including its saved design.
    const panel = page.getByTestId("native-studio-run");
    await expect(page.getByLabel("Workflow name", { exact: true })).toHaveValue(
      approved.experiment.title,
    );
    await expect(page.getByLabel("Step 2 volume", { exact: true })).toHaveValue(
      String(approved.experiment.actions[1].volume),
    );
    await expect(
      panel.getByText(/Operator commissioning window/),
    ).toBeVisible();
    requireNoReplay(index);
    report.stage = `plan-${index + 1}-native-run`;
    await save();
    await panel
      .getByRole("button", {
        name: "Run saved workflow in Matterix",
        exact: true,
      })
      .click();
    await expect
      .poll(
        () => {
          requireNoReplay(index + 1);
          return latest?.run_id;
        },
        { timeout: 30000 },
      )
      .toBeTruthy();
    const video = panel.getByLabel("Live native Isaac simulation", {
      exact: true,
    });
    await expect
      .poll(
        async () => {
          requireNoReplay(index + 1);
          return video.evaluate(
            (element) => element.getVideoPlaybackQuality().totalVideoFrames,
          );
        },
        { timeout: 240000 },
      )
      .toBeGreaterThan(0);
    const frames = await video.evaluate(
      (element) => element.getVideoPlaybackQuality().totalVideoFrames,
    );
    assert.equal(
      await video.evaluate(videoUsesCurrentRelay),
      true,
      "The displayed video must use the current relay-only peer",
    );
    await panel.screenshot({
      path: path.join(output, `run-${index + 1}-live.png`),
    });
    let refreshFrames = 0;
    if (index === 0) {
      recovery = {
        runId: latest.run_id,
        minimumVersion: latest.version,
        minimumNavigation: navigation + 1,
      };
      recoveredRun = undefined;
      await page.reload();
      await expect
        .poll(() => recoveredRun?.run_id, { timeout: 30000 })
        .toBe(recovery.runId);
      requireNoReplay(index + 1);
      // A restored record alone is insufficient: prove the refreshed viewport decodes again.
      await expect
        .poll(
          async () =>
            video.evaluate(
              (element) => element.getVideoPlaybackQuality().totalVideoFrames,
            ),
          { timeout: 120000 },
        )
        .toBeGreaterThan(0);
      refreshFrames = await video.evaluate(
        (element) => element.getVideoPlaybackQuality().totalVideoFrames,
      );
      assert.equal(await video.evaluate(videoUsesCurrentRelay), true);
      report.refresh_verified = true;
    }
    await expect
      .poll(
        () => {
          requireNoReplay(index + 1);
          if (
            ["failed", "cancelled", "outcome_unknown"].includes(latest?.status)
          )
            throw new Error(
              "Native execution did not complete; reconcile the original run before proceeding",
            );
          return latest?.cleanup?.reset_verified;
        },
        { timeout: 1800000 },
      )
      .toBe(true);
    // Stop accepting new reads and drain this run before advancing the approved plan index.
    activeSession = undefined;
    await Promise.allSettled([...pendingReads]);
    requireNoReplay(index + 1);
    checkCompletedRun(latest, session, approved, request.studio);
    report.browser_runs.push({
      run_id: latest.run_id,
      session_id: session.id,
      plan_hash: approved.plan_hash,
      scene: request.studio.scene,
      instrument: request.studio.instrument,
      frames_decoded: frames,
      relay_verified: true,
      refresh_frames_decoded: refreshFrames,
      completed_steps: latest.completed_steps,
    });
    await panel.screenshot({
      path: path.join(output, `run-${index + 1}-reset.png`),
    });
    await save();
  }
  report.server_report = await authenticated("/api/commissioning/report");
  requireNoReplay(2);
  checkServerReport(report.server_report, request, report.browser_runs);
  report.status = "completed";
  report.stage = "browser-receipts-complete";
  await save();
  console.log(
    "Studio browser receipts saved. Correlate them with native artifacts and the reviewed request; these receipts do not qualify a worker or validate fluid physics, chemistry, or hardware.",
  );
} catch (error) {
  report.status = "failed";
  report.error = error.name;
  await save();
  console.error(
    "Acceptance stopped. Reconcile any submitted run; rerunning this harness never retries a previous mutation.",
  );
  throw error;
} finally {
  await context.close();
  await browser.close();
}
