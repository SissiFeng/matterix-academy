import { expect, test } from "@playwright/test";

test("the start page maps every stop on both routes to its page", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Roadmap learner");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();

  const learning = page.getByRole("region", { name: "Learning route" });
  const using = page.getByRole("region", { name: "Using route" });
  await expect(learning.getByRole("listitem")).toHaveCount(5);
  await expect(using.getByRole("listitem")).toHaveCount(5);

  const start = page.getByRole("button", { name: "Start here", exact: true });
  const stops: [typeof learning, string, RegExp, string][] = [
    [
      learning,
      "Meet the robot",
      /#\/instruments$/,
      "What the robot is made of",
    ],
    [learning, "Learn by level", /#\/learn$/, "Learning lab"],
    [learning, "Simulate", /#\/sim$/, "Four sources. One mixture."],
    [learning, "Adapt a workflow", /#\/marketplace$/, "Workflow marketplace"],
    [learning, "Compare with classmates", /#\/groups$/, "Study groups"],
    [using, "Add a device", /#\/onboard$/, "Add a device"],
    [using, "Practise on its twin", /#\/twin$/, "Teaching twin"],
    [using, "Plan the bench", /#\/plan$/, "Plan your workcell"],
    [using, "Check readiness", /#\/readiness$/, "Real-device readiness"],
    [using, "Review runs", /#\/runs$/, "Teaching runs"],
  ];
  for (const [route, name, url, heading] of stops) {
    await route.getByRole("button", { name }).click();
    await expect(page).toHaveURL(url);
    await expect(
      page.getByRole("heading", { name: heading, exact: true }),
    ).toBeVisible();
    await start.click();
  }
});
