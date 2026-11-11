import { expect, test } from "@playwright/test";

test("the synthesis workcell case loads registered assets and runs end to end", async ({
  page,
}) => {
  // Software WebGL in CI renders the full cell slowly.
  test.setTimeout(150000);
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page.getByRole("button", { name: "Add a device", exact: true }).click();
  await page
    .getByRole("button", { name: /Multi-device case: synthesis workcell/ })
    .click();
  await expect(page).toHaveURL(/#\/onboard\/case-synthesis-cell$/);
  await expect(
    page.getByRole("heading", { name: "Synthesis workcell" }),
  ).toBeVisible();
  // Assets are fetched and checked against their registered digests before the scene appears.
  await expect(page.getByText("Loading registered assets…")).toBeHidden({
    timeout: 30000,
  });
  await expect(
    page.getByText(/^Complete run: \d+ s of workcell time/),
  ).toBeVisible();
  await page.getByRole("tab", { name: /Arm chain/ }).click();
  await expect(page.getByRole("tab", { name: /19\/24/ })).toBeVisible();
  await expect(
    page.getByText("Arm, fingers and rack clear every modelled keep-out."),
  ).toBeVisible();
  // The hand-designed chain also runs in the rigid-body simulation.
  await page.getByRole("button", { name: "Simulate in MuJoCo" }).click();
  await expect(page.getByRole("status")).toContainText(
    /Simulated in MuJoCo [\d.]+: \d+\.\d s · \d+% joint torque/,
    { timeout: 30000 },
  );
  await page.getByRole("tab", { name: "Workflow" }).click();
  await page.getByRole("button", { name: /Add 200 µL reagent mix/ }).click();
  const log = page.getByTestId("run-log");
  await expect(log).toContainText(/Balance\s*Stable 67\.\d{3} g/);
  await expect(log).toContainText("Rack released · In OT-2 slot 2");
  await page.getByText("Registered assets (7)").click();
  await expect(
    page.getByText("Universal_Robots_ROS2_Description@0eb1a86"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Device onboarding" }).click();
  await expect(
    page.getByRole("heading", { name: "Identify your physical device" }),
  ).toBeVisible();
});
