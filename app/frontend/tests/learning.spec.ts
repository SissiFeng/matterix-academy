import { test, expect, type Page } from "@playwright/test";

async function startLesson(page: Page) {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Lin");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page
    .getByRole("button", { name: "开始 Flex 入门", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /让 100 µL 液体/ }),
  ).toBeVisible();
}

async function tour(page: Page) {
  for (const name of ["移液器", "吸头架", "源容器", "目标孔板", "废弃槽"]) {
    await page.getByRole("button", { name, exact: true }).click();
    await expect(
      page.getByText(
        `已探索 ${["移液器", "吸头架", "源容器", "目标孔板", "废弃槽"].indexOf(name) + 1} / 5 个对象。`,
        { exact: false },
      ),
    ).toBeVisible();
  }
  await page.getByLabel("孔板中的一个孔", { exact: true }).click();
  await page.getByRole("button", { name: "去准备实验", exact: true }).click();
}

async function prepare(page: Page) {
  for (const name of [
    "移液器与吸头",
    "耗材与位置",
    "起始液量",
    "本次练习的范围",
  ]) {
    const checkbox = page.getByRole("checkbox", { name: new RegExp(name) });
    await checkbox.click();
    await expect(checkbox).toBeChecked();
  }
  await page.getByRole("button", { name: "先预测液量", exact: true }).click();
}

async function predict(page: Page, volume: number) {
  await page.getByLabel("源容器剩余").fill(String(1000 - volume));
  await page.getByLabel("吸头内液量").fill(String(volume));
  await page.getByLabel("目标 A1 孔液量").fill("0");
  await page.getByRole("button", { name: "检查我的预测", exact: true }).click();
  await expect(
    page.getByText("预测正确。吸液先把液体装进吸头，目标孔此时仍为空。"),
  ).toBeVisible();
  await page.getByRole("button", { name: "进入操作练习", exact: true }).click();
}

test("novice learns equipment, predicts, executes each step, reflects and retries 50 uL", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await startLesson(page);
  await expect(
    page.getByRole("button", { name: "去准备实验", exact: true }),
  ).toBeDisabled();
  await tour(page);
  await expect(
    page.getByLabel("目标孔板槽位").locator("option[value='D3']"),
  ).toHaveCount(0);
  await prepare(page);
  await page.getByLabel("源容器剩余").fill("900");
  await page.getByLabel("吸头内液量").fill("0");
  await page.getByLabel("目标 A1 孔液量").fill("100");
  await page.getByRole("button", { name: "检查我的预测", exact: true }).click();
  await expect(page.getByText(/再想一想：吸液/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "进入操作练习", exact: true }),
  ).toBeDisabled();
  await predict(page, 100);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "取一个新吸头", exact: true }),
  ).toBeVisible();
  for (const next of [
    "吸取 100 µL",
    "排出 100 µL",
    "弃去用过的吸头",
    "转移完成。现在解释它。",
  ]) {
    await page.getByRole("button", { name: "执行下一步", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: next, exact: true }),
    ).toBeVisible();
  }
  await page
    .getByRole("button", { name: "解释结果并再试一次", exact: true })
    .click();
  await page.getByLabel("从源容器直接到达目标孔", { exact: true }).click();
  await expect(page.getByText(/吸液时目标孔还没有收到液体/)).toBeVisible();
  await page
    .getByLabel("从源容器进入吸头，目标孔仍为空", { exact: true })
    .click();
  await expect(
    page.getByText("操作与理解均已完成", { exact: true }),
  ).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page
    .getByRole("button", { name: "挑战 50 µL 转移", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /让 50 µL 液体/ }),
  ).toBeVisible();
  await prepare(page);
  await predict(page, 50);
  await page.getByRole("button", { name: "连续运行", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "转移完成。现在解释它。", exact: true }),
  ).toBeVisible({ timeout: 15000 });
  expect(errors).toEqual([]);
});

test("remote remains honest and lesson fits a phone", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await startLesson(page);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: /远程 3D/ }).click();
  await expect(
    page.getByText("实验室尚未配置 Ubuntu 仿真连接。课程与教学练习仍可使用。"),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "真实 3D 仿真等待接入" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "重新检查连接" }).click();
  await expect(
    page.getByText("实验室尚未配置 Ubuntu 仿真连接。课程与教学练习仍可使用。"),
  ).toBeVisible();
});

test("unfinished prediction is protected and changing deck invalidates readiness", async ({
  page,
}) => {
  await startLesson(page);
  await tour(page);
  await prepare(page);
  await page.getByLabel("源容器剩余").fill("900");
  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByRole("button", { name: "返回课程", exact: true }).click();
  await expect(page.getByLabel("源容器剩余")).toHaveValue("900");
  await predict(page, 100);
  await page.getByRole("button", { name: /预测变化 先想/ }).click();
  await page.getByLabel("源容器剩余").fill("0");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: /准备台面 检查/ }).click();
  await page.getByRole("button", { name: /预测变化 先想/ }).click();
  await expect(page.getByLabel("源容器剩余")).toHaveValue("900");
  await page.getByRole("button", { name: /准备台面 检查/ }).click();
  await page.getByLabel("吸头架槽位").selectOption("C1");
  await expect(
    page.getByRole("checkbox", { name: /移液器与吸头/ }),
  ).not.toBeChecked();
  await page.getByRole("button", { name: /逐步运行 观察/ }).click();
  await expect(
    page.getByRole("button", { name: "执行下一步", exact: true }),
  ).toBeDisabled();
});

test("a correct prediction is recognized even before other prerequisites", async ({
  page,
}) => {
  await startLesson(page);
  await page.getByRole("button", { name: /预测变化 先想/ }).click();
  await page.getByLabel("源容器剩余").fill("900");
  await page.getByLabel("吸头内液量").fill("100");
  await page.getByLabel("目标 A1 孔液量").fill("0");
  await page.getByRole("button", { name: "检查我的预测", exact: true }).click();
  await expect(
    page.getByText("预测正确。吸液先把液体装进吸头，目标孔此时仍为空。"),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "进入操作练习", exact: true }),
  ).toBeDisabled();
});

test("a lost step response reloads its saved result without replaying it", async ({
  page,
}) => {
  await startLesson(page);
  await tour(page);
  await prepare(page);
  await predict(page, 100);
  let sent = 0;
  await page.route(
    "**/api/sessions/*/advance",
    async (route) => {
      sent += 1;
      // The server commits the step, but the browser loses its response.
      await route.fetch();
      await route.abort("failed");
    },
    { times: 1 },
  );
  await page.getByRole("button", { name: "执行下一步", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "吸取 100 µL", exact: true }),
  ).toBeVisible();
  expect(sent).toBe(1);
  await page.getByRole("button", { name: "执行下一步", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "排出 100 µL", exact: true }),
  ).toBeVisible();
});
