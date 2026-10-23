import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { chmod, lstat, mkdir } from "node:fs/promises";

export function acceptanceOrigin(value) {
  const url = new URL(value);
  if (
    url.protocol !== "https:" ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    url.pathname !== "/"
  )
    throw new Error("Use only the deployed HTTPS Academy origin.");
  return url.origin;
}

export function apiPath(value) {
  if (
    !/^\/api\/(?:me|workflow-course|sessions(?:\/[a-f0-9-]{36}(?:\/(?:learning|advance|reset))?)?)$/.test(
      value,
    )
  )
    throw new Error("Learner acceptance only accesses bounded teaching APIs.");
  return value;
}

export function authEvent(event, cognitoOrigin) {
  const url = new URL(event.url);
  if (url.origin !== cognitoOrigin || event.method !== "POST") return null;
  if (url.pathname === "/signup") return "signup_submitted";
  if (url.pathname === "/confirmUser") return "confirmation_submitted";
  return null;
}

export function checkedIdentity(value, otherSubject) {
  assert.equal(
    value.status,
    200,
    "The real authenticated profile API must succeed.",
  );
  assert.equal(
    value.email_verified,
    true,
    "Cognito must attest a verified email.",
  );
  assert.equal(typeof value.subject, "string");
  assert.ok(value.subject.length > 0, "A Cognito subject is required.");
  if (otherSubject)
    assert.notEqual(
      value.subject,
      otherSubject,
      "Use two different real learners.",
    );
  return createHash("sha256").update(value.subject).digest("hex");
}

export function deniedWithoutMutation(status, before, after) {
  assert.equal(status, 404, "Cross-owner resources must be hidden with 404.");
  assert.deepEqual(after, before, "The owner's record must remain unchanged.");
}

export function completedTeaching(session, steps) {
  assert.equal(session.engine, "teaching");
  assert.equal(session.evidence, "synthetic");
  assert.equal(session.status, "completed");
  assert.equal(session.cursor, steps);
  assert.equal(session.assessment?.passed, true);
}

export async function privateDirectory(directory) {
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const stat = await lstat(directory);
  if (!stat.isDirectory() || stat.isSymbolicLink())
    throw new Error("Acceptance output must be a real private directory.");
  await chmod(directory, 0o700);
}

export function finalStatus(checks) {
  return Object.values(checks).every((value) => value === true)
    ? "passed"
    : "incomplete";
}

// Cognito may return HTTP 200 for failed forms. Submission events and a later
// existing-account login never establish a newly registered, confirmed account.
export function registrationObservation(events, identity) {
  return {
    signup_submitted: events.includes("signup_submitted"),
    confirmation_submitted: events.includes("confirmation_submitted"),
    authenticated_verified_email:
      identity.status === 200 && identity.email_verified === true,
    new_registration_verified: false,
  };
}
