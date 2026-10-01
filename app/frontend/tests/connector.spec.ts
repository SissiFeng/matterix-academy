import { expect, test, type Page } from "@playwright/test";

async function enterExplorer(page: Page) {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Casey");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page
    .getByRole("button", { name: "Connector explorer", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /From an idea/ }),
  ).toBeVisible();
}

test("connector learner follows actors, inspects pinned code and applies each responsibility", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await enterExplorer(page);
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.getByRole("button", { name: "API", exact: true }).click();
  await expect(
    page.getByText(
      "A defined way for one program to ask another to do something or return information.",
    ),
  ).toBeVisible();
  await page.getByRole("button", { name: "Next step", exact: true }).click();
  await expect(page.getByText("Step 2 of 4", { exact: true })).toBeVisible();
  await expect(
    page.getByText(
      "I send the mount, volume and rate through the connector’s API.",
    ),
  ).toBeVisible();
  await page.getByRole("button", { name: "Actual code", exact: true }).click();
  await expect(page.getByLabel("Verbatim connector source")).toContainText(
    "@sila.ObservableCommand(errors=_LIQUID_ERRORS)",
  );
  await expect(
    page.getByRole("link", { name: "Open this exact source" }),
  ).toHaveAttribute(
    "href",
    /2a9c3004400325d7816c80065a2282a4ad6b5b70.*#L355-L364$/,
  );
  await page
    .getByRole("radio", {
      name: "The animation reaching its last frame",
      exact: true,
    })
    .check();
  await page
    .getByRole("button", { name: "Check understanding", exact: true })
    .click();
  await expect(
    page.getByText("Look at the responsibility again."),
  ).toBeVisible();
  await page
    .getByRole("radio", {
      name: "The command’s reported execution outcome",
      exact: true,
    })
    .check();
  await page
    .getByRole("button", { name: "Check understanding", exact: true })
    .click();
  await expect(page.getByText("That reasoning holds.")).toBeVisible();
  for (const answer of [
    "Use the coordinated path, shared lock and applicable ownership checks",
    "It stays blocked by the ownership policy",
    "The simulated API action completed; physical volume accuracy remains unverified",
  ]) {
    await page
      .getByRole("button", { name: "Next module", exact: true })
      .click();
    await page.getByRole("radio", { name: answer, exact: true }).check();
    await page
      .getByRole("button", { name: "Check understanding", exact: true })
      .click();
    await expect(page.getByText("That reasoning holds.")).toBeVisible();
  }
  await expect(
    page.getByText("4 / 4 ideas checked", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Three different simulation contexts" }),
  ).toBeVisible();
  await page
    .getByText("See how the connector selects simulator or physical hardware", {
      exact: true,
    })
    .click();
  await expect(page.getByLabel("Verbatim connector source")).toContainText(
    "OT3API.build_hardware_simulator",
  );
  expect(errors).toEqual([]);
});

test("connector source map explains mode boundaries and reload preserves the page", async ({
  page,
}) => {
  await enterExplorer(page);
  await page.getByRole("button", { name: "Source map", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Curated source map" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: /Run ownership ProtocolRunAuthority/ })
    .click();
  await expect(page.getByLabel("Verbatim connector source")).toContainText(
    "if state.owns_hardware:",
  );
  await expect(
    page.getByText(/It is not an extra hop in every connector-unit aspiration/),
  ).toBeVisible();
  await page
    .getByRole("button", { name: /Backend selection Connector initialization/ })
    .click();
  await expect(page.getByLabel("Verbatim connector source")).toContainText(
    "OT3API.build_hardware_controller()",
  );
  await expect(
    page.getByText(
      /This is initialization, not a call made on each aspiration/,
    ),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: /From an idea/ }),
  ).toBeVisible();
});

test("connector trace playback is controllable and source stays readable on a phone", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await enterExplorer(page);
  await page.getByRole("button", { name: "Play trace", exact: true }).click();
  await expect(page.getByText("Step 2 of 4", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Pause playback", exact: true })
    .click();
  await page.getByRole("button", { name: "Reset trace", exact: true }).click();
  await expect(page.getByText("Step 1 of 4", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Actual code", exact: true }).click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "Source map", exact: true }).click();
  await page
    .getByRole("button", { name: /Execution reports report_progress calls/ })
    .click();
  await expect(page.getByLabel("Verbatim connector source")).toContainText(
    "OperationPhase.CANCELLED",
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
