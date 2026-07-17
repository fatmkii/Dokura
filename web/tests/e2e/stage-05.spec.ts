import { expect, test, type Page } from "@playwright/test";


async function login(page: Page): Promise<void> {
  const response = await page.request.post("/api/v1/auth/login", {
    data: { username: "admin", password: "admin" },
  });
  expect(response.status()).toBe(200);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "内容库" })).toBeVisible();
}


test("Web 管理闭环使用跨页快照并安全处理部分冲突 @stage5", async ({ page }) => {
  await login(page);

  await expect.poll(async () => {
    const response = await page.request.get("/api/v1/catalog", { params: { page: 1, per_page: 50 } });
    return (await response.json()).total as number;
  }, { timeout: 15_000 }).toBeGreaterThanOrEqual(34);
  await page.reload();

  await test.step("批量移动保留成功项并解释同名冲突", async () => {
    await page.goto("/?q=%E5%90%8C%E5%90%8D&scope=recursive");
    const sameNameChecks = page.getByRole("checkbox", { name: /选择 同名.zip/ });
    await expect(sameNameChecks).toHaveCount(2);
    await sameNameChecks.first().check();
    await sameNameChecks.last().check();
    const batchBar = page.getByText("个当前选择").locator("..").locator("..");
    page.once("dialog", (dialog) => dialog.accept("目标"));
    await batchBar.getByRole("button", { name: "移动", exact: true }).click();
    await expect(page.getByText(/移动成功 1 项，失败 1 项/)).toBeVisible();
    await expect(page.getByText(/目标名称.*冲突|目标名称已存在/)).toBeVisible();
  });

  await test.step("筛选 0–3 星、跨分页全选、确认并永久删除", async () => {
    await page.goto("/?per_page=25&rating_max=3");
    await expect(page.getByRole("link", { name: "[验收作者] 跨页删除 00.zip", exact: true })).toBeVisible();
    await expect(page.getByText("1 / 2")).toBeVisible();
    await page.getByRole("button", { name: /选择全部结果 30/ }).click();
    await expect(page.getByText("个快照项目")).toBeVisible();
    await expect(page.getByRole("complementary").getByText("30", { exact: true })).toBeVisible();
    page.once("dialog", (dialog) => dialog.accept());
    const batchBar = page.getByText("个快照项目").locator("..").locator("..");
    await batchBar.getByRole("button", { name: "永久删除", exact: true }).click();
    await expect(page.getByText(/永久删除成功 30 项/)).toBeVisible();
    await expect(page.getByText("没有符合当前条件的内容")).toBeVisible();
  });

  await test.step("非空文件夹拒绝删除且未管理隐藏项仍保留", async () => {
    await page.goto("/");
    const row = page.getByText("非空目录", { exact: true }).locator("..").locator("..");
    page.once("dialog", (dialog) => dialog.accept());
    await row.getByRole("button", { name: "永久删除" }).click();
    await expect(page.getByText(/只能删除实际为空的文件夹/)).toBeVisible();
    await expect(page.getByRole("button", { name: /非空目录 非空目录/ })).toBeVisible();
  });

  await test.step("任务轮询、日志筛选与归档下载可用", async () => {
    let taskRequests = 0;
    page.on("request", (incoming) => {
      if (new URL(incoming.url()).pathname === "/api/v1/admin/tasks") taskRequests += 1;
    });
    await page.getByRole("link", { name: "后台任务" }).click();
    await expect(page.getByRole("heading", { name: "后台任务" })).toBeVisible();
    await expect.poll(() => taskRequests, { timeout: 5_000 }).toBeGreaterThanOrEqual(2);
    await page.getByRole("link", { name: "日志" }).click();
    await expect(page.getByRole("heading", { name: "日志" })).toBeVisible();
    const stoppedAt = taskRequests;
    await page.waitForTimeout(2200);
    expect(taskRequests).toBe(stoppedAt);
    await page.getByRole("button", { name: "INFO" }).click();
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("link", { name: /下载日志归档/ }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe("dokura-logs.zip");
  });

  await test.step("设置页只显示旧 APIkey 后四位并提供缓存清理入口", async () => {
    await page.goto("/settings");
    await expect(page.getByRole("heading", { name: "设置" })).toBeVisible();
    await expect(page.getByText(/完整旧 key 无法再次查看/)).toBeVisible();
    await expect(page.getByRole("button", { name: "清理缓存" })).toBeVisible();
  });
});
