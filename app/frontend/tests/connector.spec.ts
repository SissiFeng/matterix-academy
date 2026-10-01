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
  let entered = false;
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    // Bootstrap probes are expected to reject the visitor before guest login.
    const url = message.location().url;
    if (
      !entered &&
      message.text().includes("401 (Unauthorized)") &&
      /\/api\/(me|courses|sessions)$/.test(url)
    )
      return;
    if (message.type() === "error") errors.push(message.text());
  });
  await enterExplorer(page);
  entered = true;
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
    page.getByRole("heading", { name: "Curated source map" }),
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

test("developer compares parameter meaning, completion, properties, composition and errors", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await enterExplorer(page);
  await page
    .getByRole("button", { name: "API ↔ SiLA mapping", exact: true })
    .click();
  await page.getByRole("button", { name: "Rate", exact: true }).click();
  await expect(page.getByLabel("Rate mapping")).toContainText("dimensionless");
  await expect(page.getByText(/It is not 1 µL\/s/)).toBeVisible();
  await page
    .getByText("Inspect the actual mapping code", { exact: true })
    .click();
  await page
    .getByRole("button", { name: "Units and constraints", exact: true })
    .click();
  await expect(page.getByLabel("Mapping implementation source")).toContainText(
    "_DIMENSIONLESS_RATE",
  );
  await expect(
    page.getByRole("link", { name: "Open pinned implementation" }),
  ).toHaveAttribute(
    "href",
    /2a9c3004400325d7816c80065a2282a4ad6b5b70.*#L80-L84$/,
  );
  for (const [capability, dimension, expected, answer] of [
    [
      "Move to a position",
      "Default speed",
      "speed if speed > 0 else None",
      "Translate it to the vendor default representation",
    ],
    [
      "Set a temperature",
      "Accept a target",
      "target acceptance",
      "No, this command promises target acceptance; use the wait command for the controller target condition",
    ],
    [
      "Read changing state",
      "Missing target",
      "target_active=false",
      "There is no active target; zero is a placeholder",
    ],
    [
      "Compose an operation",
      "Operation boundary",
      "shared operation lock",
      "No; report the partial state and use an explicit recovery procedure",
    ],
    [
      "Translate a failure",
      "No response",
      "ModuleNotRespondingError",
      "Report uncertainty and reconcile observed state before deciding whether a retry is appropriate",
    ],
  ]) {
    await page
      .getByRole("button", { name: new RegExp("^" + capability) })
      .click();
    await page.getByRole("button", { name: dimension, exact: true }).click();
    await expect(page.getByLabel(`${dimension} mapping`)).toContainText(
      expected,
    );
    await page.getByRole("radio", { name: answer, exact: true }).check();
    await page
      .getByRole("button", { name: "Check this interpretation" })
      .click();
    await expect(
      page.getByText("The contract supports that interpretation."),
    ).toBeVisible();
  }
  expect(errors).toEqual([]);
});

test("developer follows SDK, HTTP and protocol boundaries and six development deliverables", async ({
  page,
}) => {
  await enterExplorer(page);
  await page
    .getByRole("button", { name: "Build a connector", exact: true })
    .click();
  await expect(page).toHaveURL(/#\/connector\/development$/);
  await page
    .getByRole("button", { name: "Connector explorer", exact: true })
    .click();
  await expect(page).toHaveURL(/#\/connector\/development$/);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Build a connector", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "HTTP API", exact: true }).click();
  await expect(
    page.getByText("Generic design pattern", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Follow the next boundary" }).click();
  await expect(
    page.getByText("Observe the vendor job until a defined outcome"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Follow the next boundary" }).click();
  await expect(
    page.getByText("Map progress, result or uncertainty"),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Follow the next boundary" }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Device protocol", exact: true })
    .click();
  await expect(
    page.getByText("Encode a documented device command"),
  ).toBeVisible();
  const expected = [
    "Capability inventory",
    "Feature and capability mapping",
    "Controller / I/O implementation",
    "Registered Feature with status and results",
    "Offline adapter and SiLA client tests",
    "Versioned acceptance record and recovery guide",
  ];
  for (let i = 0; i < expected.length; i++) {
    await expect(page.getByText(expected[i], { exact: true })).toBeVisible();
    if (i < expected.length - 1)
      await page
        .getByRole("button", { name: "Next development step", exact: true })
        .click();
  }
  await expect(
    page.getByRole("button", { name: "Next development step", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("radio", { name: "A command that sets a target", exact: true })
    .check();
  await expect(
    page.getByText(/Setting a target changes the device/),
  ).toBeVisible();
  await page
    .getByRole("radio", {
      name: "An observable Property that reports state",
      exact: true,
    })
    .check();
  await expect(
    page.getByText(/Expose reported state as a Property/),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Build a connector", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Return to API ↔ SiLA mapping", exact: true })
    .click();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "API ↔ SiLA mapping", exact: true }),
  ).toBeVisible();
});

test("developer mapping and build views fit a phone without hiding source", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await enterExplorer(page);
  await page
    .getByRole("button", { name: "API ↔ SiLA mapping", exact: true })
    .click();
  await page.getByRole("button", { name: /^Set a temperature/ }).click();
  await page
    .getByText("Inspect the actual mapping code", { exact: true })
    .click();
  await page
    .getByRole("button", { name: "Wait and cancellation", exact: true })
    .click();
  await expect(page.getByLabel("Mapping implementation source")).toContainText(
    "await self._controller.deactivate()",
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page
    .getByRole("button", { name: "Build a connector", exact: true })
    .click();
  await page.getByRole("button", { name: "HTTP API", exact: true }).click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
