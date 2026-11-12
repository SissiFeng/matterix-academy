import { expect, test } from "@playwright/test";

test("an example workcell opens with a layout the arm can run", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "This is my first time" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page.goto("/#/plan");
  await page.getByRole("tab", { name: "1 · Describe" }).click();

  const examples = page.getByRole("region", { name: "Example workcells" });
  await expect(examples.getByRole("listitem")).toHaveCount(8);
  // The hand-set synthesis workcell is listed with the planned examples.
  await expect(
    examples.getByRole("link", { name: /Synthesis workcell/ }),
  ).toHaveAttribute("href", "#/onboard/case-synthesis-cell");
  await examples
    .getByRole("button", { name: /Flex, plate sealer, plate reader/ })
    .click();

  // It lands on the layout, with both transfers planned and simulated.
  await expect(page.getByRole("tab", { name: "4 · Layout" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  const paths = page.getByRole("button", { name: /^Step \d+ · / });
  // Two transfers are planned and simulated, which a busy runner takes a while over.
  await expect(paths).toHaveCount(2, { timeout: 60_000 });
  await expect(paths.first()).toContainText("cm min clearance");
  await expect(
    page.getByRole("button", { name: "Save layout" }),
  ).toBeDisabled();

  // The workflow is laid out in time, one lane per instrument, with the arm's joints,
  // a log of every step and where the sample is.
  const data = page.getByRole("region", { name: "Workflow timeline" });
  await expect(data.getByText(/^0\.0 \/ \d+\.\d s$/)).toBeVisible();
  const joints = data.getByRole("group", { name: "Arm joints" });
  await expect(joints.getByRole("meter")).toHaveCount(6);
  await expect(joints.getByText("Waiting")).toBeVisible();
  await expect(
    data.getByRole("list", { name: "Run log" }).getByRole("listitem"),
  ).toHaveCount(6);
  await expect(data.getByText("No sample loaded yet.")).toBeVisible();
  // Choosing a transfer plays it: the arm is doing something and carries the sample.
  await paths.first().click();
  await expect(
    joints.getByText(/Lower into|Lift from|Transit to/),
  ).toBeVisible();
  await expect(data.getByText("carried by UR5e arm")).toBeVisible();
  await expect(joints.getByText(/\d+\.\d cm to /)).toBeVisible();
  await data.getByRole("button", { name: "Pause workflow" }).click();
  // Dragging to the end leaves the sample where the workflow puts it.
  await data.getByLabel("Workflow time").press("End");
  await expect(
    data.getByRole("cell", { name: /^Plate reader \(CLARIOstar Plus\)/ }),
  ).toBeVisible();
  await page.screenshot({
    path: "/tmp/academy-layout-data.png",
    fullPage: true,
  });
  // No language model is configured here, so layout requests are not offered.
  await expect(page.getByLabel("Change this layout")).toHaveCount(0);

  // Opening another example asks before replacing the first.
  await page.getByRole("tab", { name: "1 · Describe" }).click();
  page.once("dialog", (dialog) => dialog.dismiss());
  await examples.getByRole("button", { name: /OT-2 to Flex/ }).click();
  await page.getByRole("tab", { name: "2 · Instruments" }).click();
  await expect(page.getByText("Plate sealer (a4S)").first()).toBeVisible();
  expect(errors).toEqual([]);
});

test("a layout request in plain words lands on the draft for review", async ({
  page,
}) => {
  test.setTimeout(120_000);
  // This server has no language model: the catalog says it has one and its answer is canned.
  let asked = "";
  await page.route("**/api/twins/layout/refine", async (route) => {
    const sent = route.request().postDataJSON();
    asked = sent.text;
    const reader = sent.placements[2];
    await route.fulfill({
      json: {
        bench: sent.bench,
        placements: sent.placements.map((p: { twin_id: string; x: number }) =>
          p.twin_id === reader.twin_id
            ? { ...p, x: Number((p.x - 0.05).toFixed(2)), kept: true }
            : p,
        ),
        constraints: [{ kind: "zone", twin_id: reader.twin_id, side: "left" }],
        applied: [
          "Plate reader (CLARIOstar Plus) moved 0.05 m toward the left",
          "Plate reader (CLARIOstar Plus) on the left",
        ],
        skipped: ["Centrifuge"],
        unclear: "",
        search: true,
        model: "Amazon Nova Pro",
      },
    });
  });
  await page.route(/\/api\/twins(\/examples\/[a-z0-9-]+)?$/, async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    if (response.ok() && Array.isArray(body.twins))
      body.refine_available = true;
    await route.fulfill({ response, json: body });
  });
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "This is my first time" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page.goto("/#/plan");
  await page.getByRole("tab", { name: "1 · Describe" }).click();
  await page
    .getByRole("region", { name: "Example workcells" })
    .getByRole("button", { name: /Flex to plate reader/ })
    .click();
  const path = page.getByRole("button", { name: /^Step 3 · / });
  await expect(path).toContainText("cm min clearance", { timeout: 60_000 });

  const request = page.getByLabel("Change this layout");
  const refine = page.getByRole("button", { name: "Refine" });
  await expect(refine).toBeDisabled();
  await request.fill("Move the reader 5 cm left and put the centrifuge away");
  await refine.click();
  await expect(
    page.getByText(
      "Plate reader (CLARIOstar Plus) moved 0.05 m toward the left",
    ),
  ).toBeVisible();
  await expect(page.getByText("Not applied: Centrifuge")).toBeVisible();
  expect(asked).toBe("Move the reader 5 cm left and put the centrifuge away");
  // The change is on the draft: checked again, and waiting to be saved.
  await expect(path).toContainText("cm min clearance");
  await expect(page.getByRole("button", { name: "Save layout" })).toBeEnabled();
  await expect(request).toHaveValue("");
  // A preference is the learner's to keep: it is saved only when they say so.
  await page.getByRole("button", { name: "Save these preferences" }).click();
  await expect(
    page.getByText("Search layouts to place the instruments this way."),
  ).toBeVisible();
});
