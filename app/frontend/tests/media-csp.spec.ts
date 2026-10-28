import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

// Exercise the actual Terraform header in Chromium, rather than the fake
// WebSocket implementation used by native UI contract fixtures.
test("CSP permits Canadian KVS signaling while blocking other regions and hosts", async ({
  page,
}) => {
  const source = readFileSync(path.resolve("../../infra/main.tf"), "utf8");
  const template = source.match(/content_security_policy = "([^"]+)"/);
  expect(template).not.toBeNull();
  const policy = template![1]
    .replaceAll("${var.region}", "ca-central-1")
    .replace(
      "${aws_cognito_user_pool.learners.endpoint}",
      "cognito-idp.ca-central-1.amazonaws.com/example",
    )
    .replace(
      "${aws_cognito_user_pool_domain.learners.domain}",
      "academy-example",
    );
  await page.route("**/csp-check", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/html",
      headers: { "Content-Security-Policy": policy },
      body: "<!doctype html><title>Native signaling policy check</title>",
    }),
  );
  await page.goto("/csp-check");
  const blocked = await page.evaluate(async () => {
    const violations: string[] = [];
    const listener = (event: SecurityPolicyViolationEvent) => {
      if (event.effectiveDirective === "connect-src")
        violations.push(event.blockedURI);
    };
    document.addEventListener("securitypolicyviolation", listener);
    const sockets = [
      "wss://v-csp-check.kinesisvideo.ca-central-1.amazonaws.com/",
      "wss://v-csp-check.kinesisvideo.us-east-1.amazonaws.com/",
      "wss://untrusted.invalid/",
    ].map((url) => new WebSocket(url));
    await new Promise((resolve) => setTimeout(resolve, 500));
    for (const socket of sockets) socket.close();
    document.removeEventListener("securitypolicyviolation", listener);
    return violations;
  });
  expect(
    blocked.some((url) => url.includes("ca-central-1.amazonaws.com")),
  ).toBe(false);
  expect(blocked.some((url) => url.includes("us-east-1.amazonaws.com"))).toBe(
    true,
  );
  expect(blocked.some((url) => url.includes("untrusted.invalid"))).toBe(true);
});
