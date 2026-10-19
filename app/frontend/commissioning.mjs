// Live browser acceptance. Never included in default tests or CI.
// Invoking with --confirm-live may execute native work and incur KVS/compute charges.
import { captureRun } from "./commissioning-response.mjs";
import { chromium, expect } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
const args = process.argv.slice(2);
if (
  !args.includes("--confirm-live") ||
  !process.env.ACADEMY_COMMISSIONING_URL
) {
  throw new Error(
    "Requires --confirm-live and ACADEMY_COMMISSIONING_URL after resource/run authorization. No live action was started.",
  );
}
const url = new URL(process.env.ACADEMY_COMMISSIONING_URL);
if (
  url.username ||
  url.password ||
  url.search ||
  (url.protocol !== "https:" &&
    !(url.protocol === "http:" && url.hostname === "127.0.0.1"))
) {
  throw new Error(
    "Use the reviewed HTTPS Onboarding origin (or loopback preview), without credentials or query parameters.",
  );
}
const output = path.resolve(
  process.env.ACADEMY_COMMISSIONING_OUTPUT ??
    "../../build/commissioning/browser",
);
await mkdir(output, { recursive: true, mode: 0o700 });
const context = await chromium.launchPersistentContext(
  path.join(output, "private-browser-profile"),
  { headless: false },
);
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
let posts = 0;
let latest;
let currentRunId;
let serverReport;
const reportRead = [];
page.on("request", (request) => {
  if (
    request.method() === "POST" &&
    new URL(request.url()).origin === url.origin &&
    new URL(request.url()).pathname === "/api/runs"
  )
    posts++;
});
page.on("response", (response) => {
  const responseUrl = new URL(response.url());
  if (responseUrl.origin !== url.origin) return;
  const pathname = responseUrl.pathname;
  if (response.ok()) {
    const pending = response.json().then((value) => {
      const captured = captureRun(
        response.request().method(),
        pathname,
        value,
        currentRunId,
        latest,
      );
      currentRunId = captured.currentRunId;
      latest = captured.latest;
    });
    reportRead.push(pending.catch(() => {}));
  }
  if (response.ok() && pathname === "/api/commissioning/report") {
    reportRead.push(
      response
        .json()
        .then((value) => {
          serverReport = value;
        })
        .catch(() => {}),
    );
  }
});
await writeFile(
  path.join(output, "browser-report.json"),
  JSON.stringify({ status: "pending" }) + "\n",
  { mode: 0o600 },
);
let refreshVerified = false;
const browserRuns = [];
try {
  await page.goto(new URL("/#/sim", url).href);
  console.log(
    "Sign in manually in the opened browser if required. Waiting for an authorized commissioning window.",
  );
  await expect(page.getByText(/Operator commissioning window/)).toBeVisible({
    timeout: 300000,
  });
  const newExperiment = page.getByRole("button", {
    name: "New experiment",
    exact: true,
  });
  if (await newExperiment.isVisible()) await newExperiment.click();
  for (let index = 0; index < 2; index++) {
    latest = undefined;
    currentRunId = undefined;
    const before = posts;
    await page
      .getByRole("button", { name: "Run mixing experiment", exact: true })
      .click();
    const video = page.getByLabel("Live native Isaac simulation");
    await expect
      .poll(
        async () =>
          video.evaluate(
            (element) => element.getVideoPlaybackQuality().totalVideoFrames,
          ),
        { timeout: 240000 },
      )
      .toBeGreaterThan(0);
    const frames = await video.evaluate(
      (element) => element.getVideoPlaybackQuality().totalVideoFrames,
    );
    const relayVerified = await page.evaluate(async () => {
      for (const peer of window.__commissioningPeers ?? []) {
        const stats = await peer.getStats();
        for (const row of stats.values()) {
          if (
            row.type !== "candidate-pair" ||
            row.state !== "succeeded" ||
            !row.nominated
          )
            continue;
          const local = stats.get(row.localCandidateId);
          const remote = stats.get(row.remoteCandidateId);
          if (
            local?.candidateType === "relay" &&
            remote?.candidateType === "relay"
          )
            return true;
        }
      }
      return false;
    });
    if (!relayVerified)
      throw new Error(
        "The actual video connection did not confirm relay-only ICE",
      );
    if (index === 0) {
      // Do not submit again after reload: the selected session must recover its saved run.
      const runId = latest?.run_id;
      if (!runId)
        throw new Error("No bound native run was observed before refresh");
      await page.reload();
      await expect.poll(() => latest?.run_id, { timeout: 30000 }).toBe(runId);
      if (posts !== before + 1) throw new Error("Reload submitted another run");
      refreshVerified = true;
    }
    await expect
      .poll(() => latest?.cleanup?.reset_verified, { timeout: 1800000 })
      .toBe(true);
    if (
      latest.status !== "completed" ||
      latest.completed_steps !== 5 ||
      latest.total_steps !== 5 ||
      posts !== before + 1
    ) {
      throw new Error(
        "Expected one completed native workflow with all five steps and verified cleanup",
      );
    }
    browserRuns.push({
      run_id: latest.run_id,
      frames_decoded: frames,
      relay_verified: relayVerified,
      completed_steps: latest.completed_steps,
    });
    await page.screenshot({
      path: path.join(output, `run-${index + 1}.png`),
      fullPage: true,
    });
    if (index === 0)
      await page
        .getByRole("button", { name: "New experiment", exact: true })
        .click();
  }
  // Read the persisted owner-scoped receipt through the same authenticated browser/API layer.
  serverReport = await page.evaluate(async () => {
    const config = await (await fetch("/api/config")).json();
    let headers = {};
    if (config.auth === "cognito") {
      const key = `oidc.user:${config.issuer}:${config.client_id}`;
      const user = JSON.parse(sessionStorage.getItem(key) ?? "null");
      if (!user?.access_token)
        throw new Error("Sign in with the configured training account");
      headers = { Authorization: `Bearer ${user.access_token}` };
    }
    const response = await fetch("/api/commissioning/report", {
      headers,
      credentials: "same-origin",
    });
    if (!response.ok)
      throw new Error("Could not read authenticated commissioning evidence");
    return response.json();
  });
  await Promise.allSettled(reportRead);
  await writeFile(
    path.join(output, "browser-report.json"),
    JSON.stringify(
      {
        status: "completed",
        submission_posts: posts,
        refresh_verified: refreshVerified,
        browser_runs: browserRuns,
        server_report: serverReport,
      },
      null,
      2,
    ) + "\n",
    { mode: 0o600 },
  );
  console.log(
    "Browser receipts saved. Correlate them with the runtime inventory and native run artifacts; this does not qualify the worker.",
  );
} catch (error) {
  await writeFile(
    path.join(output, "browser-report.json"),
    JSON.stringify({
      status: "failed",
      error: error.name,
      submission_posts: posts,
    }) + "\n",
    { mode: 0o600 },
  );
  throw error;
} finally {
  await context.close();
}
