// Explicit, live Cognito/browser acceptance. No mocks, admin-confirmed users,
// stored tokens, HAR, traces, or native/GPU execution are used by this harness.
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { chromium, expect } from "@playwright/test";
import {
  acceptanceOrigin,
  apiPath,
  authEvent,
  checkedIdentity,
  deniedWithoutMutation,
  finalStatus,
  privateDirectory,
  registrationObservation,
} from "./learner-acceptance-helpers.mjs";
import {
  courseJourney,
  dilutionJourney,
  firstTransferJourney,
} from "./learner-acceptance-journeys.mjs";

const flags = new Set(process.argv.slice(2));
if (!flags.has("--confirm-live") || !flags.has("--dedicated-qa-accounts"))
  throw new Error(
    "Requires --confirm-live --dedicated-qa-accounts. This creates teaching records for two real learners; existing course progress is preserved unless --restart-qa-course is also provided.",
  );
const origin = acceptanceOrigin(process.env.ACADEMY_LEARNER_URL ?? "");
const loginTimeout = Number(
  process.env.ACADEMY_LEARNER_LOGIN_TIMEOUT ?? 300000,
);
assert.ok(
  Number.isInteger(loginTimeout) &&
    loginTimeout >= 30000 &&
    loginTimeout <= 900000,
  "The manual login timeout must be 30–900 seconds.",
);
const output = path.resolve(
  process.env.ACADEMY_LEARNER_OUTPUT ??
    `../../build/learner-acceptance/${new Date().toISOString().replaceAll(":", "-")}`,
);
await privateDirectory(output);
const runId = randomUUID();
const report = {
  schema: "academy.learner-acceptance/1",
  acceptance_id: runId,
  origin,
  started_at: new Date().toISOString(),
  evidence: "live-authenticated-cloud-synthetic-teaching",
  status: "running",
  stage: "configuration",
  checks: {
    new_signup_and_email_confirmation: false,
    two_verified_cognito_accounts: false,
    first_transfer: false,
    course_completion: false,
    course_refresh_no_replay: false,
    dilution_save_refresh: false,
    dilution_reset_second_run: false,
    cross_owner_read_write_denied: false,
    stale_write_rejected: false,
    logout_reauthentication_restore: false,
    course_restart: false,
  },
  accounts: [],
  sessions: [],
  native_acceptance: "not-tested",
  email_delivery: "not-observed-by-browser-harness",
};
async function saveReport() {
  const temporary = path.join(output, `.${randomUUID()}.json`);
  await writeFile(temporary, JSON.stringify(report, null, 2) + "\n", {
    mode: 0o600,
    flag: "wx",
  });
  await rename(temporary, path.join(output, "learner-report.json"));
}
async function stage(name) {
  report.stage = name;
  console.log(`Learner acceptance: ${name}`);
  await saveReport();
}
let config;
let cognitoOrigin;
let browser;
const actors = [];

async function makeActor(label) {
  // Nonpersistent, isolated contexts discard credentials on close. No auth export.
  const context = await browser.newContext();
  const page = await context.newPage();
  const actor = {
    label,
    context,
    page,
    mutations: 0,
    authEvents: [],
    identity: null,
  };
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (
      url.origin === origin &&
      url.pathname.startsWith("/api/") &&
      ["POST", "PUT", "PATCH", "DELETE"].includes(request.method())
    )
      actor.mutations++;
    const event = authEvent(
      { url: request.url(), method: request.method() },
      cognitoOrigin,
    );
    if (event) actor.authEvents.push(event);
  });
  actors.push(actor);
  return actor;
}

async function api(actor, endpoint, method = "GET", body) {
  apiPath(endpoint);
  assert.ok(["GET", "PUT", "POST"].includes(method));
  return actor.page.evaluate(
    async ({ origin, config, endpoint, method, body }) => {
      if (location.origin !== origin)
        throw new Error("Return to Academy after sign-in.");
      const saved = JSON.parse(
        sessionStorage.getItem(
          `oidc.user:${config.issuer}:${config.client_id}`,
        ) ?? "null",
      );
      const response = await fetch(endpoint, {
        method,
        headers: {
          ...(saved?.access_token
            ? { Authorization: `Bearer ${saved.access_token}` }
            : {}),
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
      });
      return { status: response.status, body: await response.json() };
    },
    { origin, config, endpoint, method, body },
  );
}

async function read(actor, endpoint) {
  const response = await api(actor, endpoint);
  assert.equal(response.status, 200, `Read failed: ${endpoint}`);
  return response.body;
}

async function signedInIdentity(actor) {
  if (new URL(actor.page.url()).origin !== origin) return null;
  return actor.page.evaluate(async (config) => {
    const saved = JSON.parse(
      sessionStorage.getItem(
        `oidc.user:${config.issuer}:${config.client_id}`,
      ) ?? "null",
    );
    if (!saved?.access_token || !saved?.profile?.sub) return null;
    const response = await fetch("/api/me", {
      headers: { Authorization: `Bearer ${saved.access_token}` },
      cache: "no-store",
      redirect: "error",
    });
    // Tokens remain inside this browser context. These identity values are never logged.
    return {
      status: response.status,
      subject: saved.profile.sub,
      email_verified: saved.profile.email_verified === true,
    };
  }, config);
}

async function manualSignIn(actor, otherSubject, returning = false) {
  await actor.page.goto(origin);
  console.log(
    `In the opened browser for learner ${actor.label}, ${returning ? "sign in again with the SAME learner" : "sign in with a dedicated QA learner"}. ${actor.label === "A" && !returning ? "To verify new registration, create a new allowed-domain account and confirm the emailed code through Cognito." : "Learner B must be a different real account."} Waiting up to ${loginTimeout / 1000} seconds.`,
  );
  await expect
    .poll(
      async () => {
        try {
          actor.identity = await signedInIdentity(actor);
          return actor.identity?.status;
        } catch {
          return undefined;
        }
      },
      { timeout: loginTimeout, intervals: [1000, 2000] },
    )
    .toBe(200);
  const subjectHash = checkedIdentity(actor.identity, otherSubject);
  if (returning) {
    assert.equal(
      subjectHash,
      report.accounts[0].subject_sha256,
      "Reauthenticate the original learner A.",
    );
    return;
  }
  const registration = registrationObservation(
    actor.authEvents,
    actor.identity,
  );
  report.accounts.push({
    learner: actor.label,
    subject_sha256: subjectHash,
    verified_email: true,
    registration_observations: registration,
  });
  // Requests and an existing verified login cannot establish successful new signup.
  // An operator must separately record actual registration and mailbox delivery.
  const profile = await read(actor, "/api/me");
  if (!profile.onboarded) {
    await actor.page
      .getByLabel("Your name", { exact: true })
      .fill(`Acceptance learner ${actor.label}`);
    await actor.page
      .getByRole("button", { name: "Continue", exact: true })
      .click();
    await actor.page
      .getByRole("button", { name: "Continue", exact: true })
      .click();
    await actor.page
      .getByRole("button", { name: "Open my workspace", exact: true })
      .click();
  }
  await expect(
    actor.page.getByRole("button", { name: "Sign out", exact: true }),
  ).toBeVisible();
}

async function freshCourse(actor) {
  const course = await read(actor, "/api/workflow-course");
  if (course.version === 0) return course;
  assert.ok(
    flags.has("--restart-qa-course"),
    "Existing course progress found. Use fresh QA accounts or explicitly pass --restart-qa-course for dedicated QA data.",
  );
  const result = await api(actor, "/api/workflow-course", "POST", {
    expected_version: course.version,
    action: "restart",
  });
  assert.equal(result.status, 200);
  return result.body;
}

try {
  await stage("configuration");
  const configResponse = await fetch(`${origin}/api/config`, {
    redirect: "error",
  });
  assert.equal(configResponse.status, 200);
  config = await configResponse.json();
  assert.equal(
    config.auth,
    "cognito",
    "Live acceptance requires real Cognito.",
  );
  assert.equal(new URL(config.app_url).origin, origin);
  assert.equal(new URL(config.issuer).protocol, "https:");
  cognitoOrigin = acceptanceOrigin(config.cognito_domain);
  const versionResponse = await fetch(`${origin}/version.json`, {
    redirect: "error",
  });
  assert.equal(versionResponse.status, 200);
  const version = await versionResponse.json();
  assert.match(version.commit, /^[a-f0-9]{40}$/);
  assert.equal(typeof version.version, "string");
  report.release = {
    source_commit: version.commit,
    version: version.version,
  };
  browser = await chromium.launch({ headless: false });
  await stage("learner-a-manual-signup-or-login");
  const a = await makeActor("A");
  await manualSignIn(a);
  await stage("learner-b-manual-login");
  const b = await makeActor("B");
  await manualSignIn(b, a.identity.subject);
  report.checks.two_verified_cognito_accounts = true;
  // Preserve personal course data before running any course command.
  await stage("dedicated-qa-preflight");
  const existingSessions = await read(a, "/api/sessions");
  assert.ok(
    !existingSessions.some(
      (item) => item.experiment.course_id === "flex-first-transfer",
    ),
    "Learner A already has a Flex lesson. Use an unused dedicated QA learner to avoid changing prior learning progress.",
  );
  await freshCourse(a);
  const bCourseBefore = await read(b, "/api/workflow-course");
  const bSessionsBefore = await read(b, "/api/sessions");
  await stage("workflow-course-and-refresh");
  await a.page.bringToFront();
  const completedCourse = await courseJourney(a, { read, report });
  assert.deepEqual(await read(b, "/api/workflow-course"), bCourseBefore);
  await stage("dilution-save-reset-and-second-run");
  const completed = await dilutionJourney(a, { read, report, runId });
  await stage("first-transfer-lesson");
  await firstTransferJourney(a, { read, report });
  await stage("cross-owner-read-and-write-denial");
  const endpoint = `/api/sessions/${completed.id}`;
  for (const [method, suffix, body] of [
    ["GET", "", undefined],
    [
      "PUT",
      "",
      { version: completed.version, experiment: completed.experiment },
    ],
    ["POST", "/reset", { version: completed.version }],
  ]) {
    const before = await read(a, endpoint);
    const response = await api(b, endpoint + suffix, method, body);
    deniedWithoutMutation(response.status, before, await read(a, endpoint));
  }
  assert.deepEqual(await read(b, "/api/sessions"), bSessionsBefore);
  assert.deepEqual(await read(b, "/api/workflow-course"), bCourseBefore);
  report.checks.cross_owner_read_write_denied = true;
  const stale = await api(a, "/api/workflow-course", "POST", {
    expected_version: completedCourse.version - 1,
    action: "restart",
  });
  assert.equal(stale.status, 409);
  assert.deepEqual(await read(a, "/api/workflow-course"), completedCourse);
  report.checks.stale_write_rejected = true;
  await stage("logout-and-fresh-authentication");
  await a.page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(a.page.getByRole("button", { name: /Sign in/ })).toBeVisible({
    timeout: 30000,
  });
  assert.equal((await api(a, "/api/me")).status, 401);
  // A new isolated context ensures restoration comes from the cloud, not browser cache.
  await a.context.close();
  const restored = await makeActor("A");
  await manualSignIn(restored, undefined, true);
  await restored.page
    .getByRole("button", { name: "Learning lab", exact: true })
    .click();
  await restored.page
    .getByRole("button", { name: "Open workflow judgment course" })
    .click();
  await expect(
    restored.page.getByRole("heading", { name: "Workflow judgment complete" }),
  ).toBeVisible();
  assert.deepEqual(
    await read(restored, "/api/workflow-course"),
    completedCourse,
  );
  assert.deepEqual(await read(restored, endpoint), completed);
  report.checks.logout_reauthentication_restore = true;
  await stage("course-restart");
  restored.page.once("dialog", (dialog) => dialog.accept());
  await restored.page
    .getByRole("button", { name: "Restart course", exact: true })
    .click();
  await expect(
    restored.page.getByRole("heading", {
      name: "Which claims prevent approval?",
    }),
  ).toBeVisible();
  const resetCourse = await read(restored, "/api/workflow-course");
  assert.equal(resetCourse.phase, "review");
  assert.equal(resetCourse.completed, false);
  assert.equal(resetCourse.trial, null);
  assert.equal(resetCourse.version, completedCourse.version + 1);
  report.checks.course_restart = true;
  report.automated_status = finalStatus(
    Object.fromEntries(
      Object.entries(report.checks).filter(
        ([name]) => name !== "new_signup_and_email_confirmation",
      ),
    ),
  );
  report.status = finalStatus(report.checks);
  report.stage = "finished";
  if (report.status !== "passed") {
    process.exitCode = 2;
    console.log(
      "Automated teaching/isolation checks completed. New registration and mailbox delivery require separate real operator evidence; outgoing signup requests and verified login do not establish successful registration.",
    );
  } else
    console.log(
      "Live Cognito browser flow, teaching, restoration and account isolation checks passed. Mailbox delivery and GPU/native acceptance require separate evidence.",
    );
} catch (error) {
  report.status = "failed";
  // Playwright errors can include URLs or DOM text. Do not persist those.
  report.failure_type = error.name;
  process.exitCode = 1;
  console.error(
    `Acceptance failed during ${report.stage} (${error.name}). No failed mutation was retried.`,
  );
} finally {
  report.finished_at = new Date().toISOString();
  await saveReport();
  await browser?.close();
  console.log(
    `Sanitized evidence: ${path.join(output, "learner-report.json")}`,
  );
}
