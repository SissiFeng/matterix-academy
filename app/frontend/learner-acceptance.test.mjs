import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, stat, symlink, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import {
  acceptanceOrigin,
  apiPath,
  authEvent,
  checkedIdentity,
  completedTeaching,
  deniedWithoutMutation,
  finalStatus,
  privateDirectory,
  registrationObservation,
} from "./learner-acceptance-helpers.mjs";

test("live acceptance rejects local, credential-bearing and callback URLs", () => {
  assert.equal(acceptanceOrigin("https://example.com"), "https://example.com");
  for (const url of [
    "http://127.0.0.1:5174",
    "https://secret@example.com",
    "https://example.com/auth/callback?code=secret",
    "https://example.com/#/workflow-course",
  ])
    assert.throws(() => acceptanceOrigin(url));
});

test("API probes cannot send tokens to other origins or native execution routes", () => {
  assert.equal(apiPath("/api/sessions"), "/api/sessions");
  assert.equal(
    apiPath("/api/sessions/60d8588d-7638-4b7f-b66e-cf3c2ad3b314/reset"),
    "/api/sessions/60d8588d-7638-4b7f-b66e-cf3c2ad3b314/reset",
  );
  for (const value of [
    "https://attacker.example/api/me",
    "//attacker.example/api/me",
    "/api/me?owner=other",
    "/api/runs",
    "/api/sessions/../runs",
  ])
    assert.throws(() => apiPath(value));
});

test("registration evidence requires POSTs to the configured Cognito origin", () => {
  const origin = "https://example.auth.ca-central-1.amazoncognito.com";
  assert.equal(
    authEvent(
      { method: "POST", url: `${origin}/confirmUser?code=secret` },
      origin,
    ),
    "confirmation_submitted",
  );
  assert.equal(
    authEvent({ method: "GET", url: `${origin}/signup` }, origin),
    null,
  );
  assert.equal(
    authEvent(
      { method: "POST", url: "https://attacker.example/signup" },
      origin,
    ),
    null,
  );
});

test("real isolation cannot be accepted with one identity or unverified email", () => {
  const identity = { status: 200, email_verified: true, subject: "learner-a" };
  assert.match(checkedIdentity(identity), /^[a-f0-9]{64}$/);
  assert.throws(() => checkedIdentity(identity, "learner-a"));
  assert.throws(() => checkedIdentity({ ...identity, status: 401 }));
  assert.throws(() => checkedIdentity({ ...identity, email_verified: false }));
});

test("isolation failures and writes despite denial cannot pass", () => {
  const record = { version: 5, status: "completed" };
  deniedWithoutMutation(404, record, { ...record });
  assert.throws(() => deniedWithoutMutation(200, record, record));
  assert.throws(() =>
    deniedWithoutMutation(404, record, { ...record, version: 6 }),
  );
});

test("teaching acceptance refuses native or incomplete evidence", () => {
  const session = {
    engine: "teaching",
    evidence: "synthetic",
    status: "completed",
    cursor: 12,
    assessment: { passed: true },
  };
  completedTeaching(session, 12);
  assert.throws(() =>
    completedTeaching({ ...session, evidence: "native" }, 12),
  );
  assert.throws(() => completedTeaching(session, 4));
});

test("missing registration is incomplete even if other checks pass", () => {
  assert.equal(finalStatus({ login: true, registration: false }), "incomplete");
  assert.equal(finalStatus({ login: true, registration: true }), "passed");
});

test("evidence directory tightens permissions and rejects symlinks", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "academy-acceptance-"));
  try {
    const output = path.join(root, "output");
    await privateDirectory(output);
    assert.equal((await stat(output)).mode & 0o777, 0o700);
    const link = path.join(root, "link");
    await symlink(output, link);
    await assert.rejects(privateDirectory(link));
  } finally {
    await rm(root, { recursive: true });
  }
});

test("failed signup/confirmation followed by an existing verified login never passes registration", () => {
  const observations = registrationObservation(
    ["signup_submitted", "confirmation_submitted"],
    { status: 200, email_verified: true, subject: "existing-account" },
  );
  assert.equal(observations.signup_submitted, true);
  assert.equal(observations.confirmation_submitted, true);
  assert.equal(observations.authenticated_verified_email, true);
  assert.equal(observations.new_registration_verified, false);
  assert.equal(
    finalStatus({
      teaching: true,
      registration: observations.new_registration_verified,
    }),
    "incomplete",
  );
});
