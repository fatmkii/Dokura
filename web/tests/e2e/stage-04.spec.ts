import { expect, test, type Page, type Route } from "@playwright/test";

const image = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64");
const fileId = "11111111-1111-4111-8111-111111111111";

const file = {
  kind: "file",
  id: fileId,
  name: "[森林社 (林一)] 安静的收藏.zip",
  relative_path: "收藏/画集/[森林社 (林一)] 安静的收藏.zip",
  display_path: "画集/[森林社 (林一)] 安静的收藏.zip",
  size: 15_728_640,
  modified_ns: 1_784_208_600_000_000_000,
  rating: 2,
  status: "ready",
  cover_status: "complete",
  content_version: "v1",
  tags: [
    { id: 1, category: "author", value: "林一" },
    { id: 2, category: "language", value: "中文" },
  ],
};

const detail = {
  ...file,
  title: "安静的收藏",
  event: null,
  creator_raw: "森林社 (林一)",
  circle: "森林社",
  translated: false,
  parser_version: "1.0.0",
  parse_confidence: 0.95,
  parse_warnings: [],
  unclassified_tags: ["全彩"],
  last_error: null,
  device: 2049,
  inode: 88001,
  created_at: "2026-07-16T09:00:00Z",
  updated_at: "2026-07-17T09:00:00Z",
  page_count: 40,
  unavailable_page_count: 1,
  cover_cache_bytes: 86_240,
  pages: Array.from({ length: 40 }, (_, index) => ({
    number: index + 1,
    unavailable: index === 7,
    unavailable_reason: index === 7 ? "decode_error" : null,
  })),
  rating_updated_at: "2026-07-17T09:00:00Z",
};

interface MockOptions {
  missingDetail?: boolean;
  ratingFailure?: boolean;
  catalogRequests?: string[];
  previewRequests?: number[];
  originalRequests?: number[];
}

async function json(route: Route, value: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });
}

async function mockApi(page: Page, options: MockOptions = {}): Promise<void> {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/api/v1/auth/session") return json(route, { username: "admin", principal: "web" });
    if (path === "/api/v1/auth/login") return json(route, { username: "admin", default_password: true });
    if (path === "/api/v1/auth/logout") return route.fulfill({ status: 204 });
    if (path === "/api/v1/catalog") {
      options.catalogRequests?.push(url.search);
      return json(route, {
        items: [
          { kind: "directory", name: "画集", relative_path: "收藏/画集" },
          { ...file, rating: file.rating },
        ],
        page: Number(url.searchParams.get("page") ?? 1),
        per_page: Number(url.searchParams.get("per_page") ?? 50),
        total: 102,
        pages: 3,
        result_version: "test-v1",
      });
    }
    if (path === "/api/v1/tags") return json(route, { items: [{ id: 1, category: "author", value: "林一", uses: 12 }, { id: 2, category: "language", value: "中文", uses: 31 }, { id: 3, category: "source", value: "原创", uses: 8 }] });
    if (path === `/api/v1/files/${fileId}`) {
      if (options.missingDetail) return json(route, { error: { message: "文件不存在" } }, 404);
      return json(route, detail);
    }
    if (path === `/api/v1/files/${fileId}/rating`) {
      if (options.ratingFailure) return json(route, { error: { message: "保存失败" } }, 500);
      const rating = request.postDataJSON().rating;
      return json(route, { id: fileId, rating, updated_at: "2026-07-17T10:00:00Z" });
    }
    if (path.endsWith("/cover")) return route.fulfill({ status: 200, contentType: "image/png", body: image });
    const preview = path.match(/\/pages\/(\d+)\/preview$/);
    if (preview) {
      options.previewRequests?.push(Number(preview[1]));
      return route.fulfill({ status: 200, contentType: "image/png", body: image });
    }
    const original = path.match(/\/pages\/(\d+)\/original$/);
    if (original) {
      options.originalRequests?.push(Number(original[1]));
      return route.fulfill({ status: 200, contentType: "image/png", body: image });
    }
    return json(route, { error: { message: "测试未定义接口" } }, 404);
  });
}

test("登录后进入内容库并提示修改默认密码", async ({ page }) => {
  await mockApi(page);
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: /让收藏留在/ })).toBeVisible();
  await page.getByLabel("用户名").fill("admin");
  await page.getByLabel("密码").fill("admin");
  await page.getByRole("button", { name: /进入内容库/ }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "内容库" })).toBeVisible();
  await expect(page.getByText(/当前仍在使用默认密码/)).toBeVisible();
  await expect(page.locator(".search-field").getByText("300 ms")).toHaveCount(0);
  await expect(page.locator(".directory-open small")).toHaveCount(0);
});

test("URL 刷新恢复目录、分页、搜索、筛选和排序状态", async ({ page }) => {
  await mockApi(page);
  const url = "/?path=%E6%94%B6%E8%97%8F&page=2&per_page=25&q=%E6%A3%AE%E6%9E%97&scope=recursive&tag=1&rating_min=2&rating_max=4&sort=modified&direction=desc";
  await page.goto(url);
  await expect(page.getByRole("heading", { name: "收藏" })).toBeVisible();
  await expect(page.getByRole("searchbox", { name: "搜索文件名" })).toHaveValue("森林");
  await expect(page.getByRole("button", { name: /author:林一/ })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: /source:原创/ })).toBeVisible();
  await expect(page.getByLabel("排序")).toHaveValue("modified");
  await page.reload();
  await expect(page).toHaveURL(new RegExp("page=2.*q="));
  await expect(page.getByRole("searchbox", { name: "搜索文件名" })).toHaveValue("森林");
  await page.getByRole("button", { name: "画集" }).click();
  await expect(page).toHaveURL(/path=%E6%94%B6%E8%97%8F\/?%E7%94%BB%E9%9B%86/);
  await page.goBack();
  await expect(page.getByRole("heading", { name: "收藏" })).toBeVisible();
  await expect(page).toHaveURL(new RegExp("page=2"));
  await page.goto("/?page=0&per_page=999&sort=unknown&direction=sideways");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "内容库" })).toBeVisible();
});

test("搜索严格等待 300ms 且只提交最后输入", async ({ page }) => {
  const catalogRequests: string[] = [];
  await mockApi(page, { catalogRequests });
  await page.goto("/");
  await expect(page.getByRole("link", { name: file.name, exact: true })).toBeVisible();
  catalogRequests.length = 0;
  const search = page.getByRole("searchbox", { name: "搜索文件名" });
  await search.fill("森");
  await search.fill("森林");
  await search.fill("森林社");
  await expect.poll(() => catalogRequests.map((query) => new URLSearchParams(query).get("query"))).toEqual(["森林社"]);
});

test("筛选排序写入 URL，评分失败会回滚并提示", async ({ page }) => {
  await mockApi(page, { ratingFailure: true });
  await page.goto("/");
  await page.getByRole("button", { name: /author:林一/ }).click();
  await expect(page).toHaveURL(/tag=1/);
  await page.getByLabel("排序").selectOption("rating");
  await expect(page).toHaveURL(/sort=rating/);
  const row = page.getByRole("article").filter({ hasText: file.name });
  await row.getByRole("button", { name: "4 星" }).click();
  await expect(page.getByText("评分保存失败，已恢复原值")).toBeVisible();
  await expect(row.getByRole("button", { name: "2 星" })).toHaveAttribute("aria-pressed", "true");
  await expect(row.getByText(/未评分|2\.0/)).toHaveCount(0);
});

test("详情只请求可见预览，进入阅读器后才请求原图", async ({ page }) => {
  const previewRequests: number[] = [];
  const originalRequests: number[] = [];
  await mockApi(page, { previewRequests, originalRequests });
  await page.goto(`/files/${fileId}`);
  await expect(page.getByRole("heading", { name: file.name })).toBeVisible();
  await expect(page.locator(".detail-cover img")).toBeVisible();
  await expect(page.locator(".detail-intro").getByText(detail.relative_path)).toHaveCount(0);
  await expect(page.locator(".detail-actions").getByText(/未评分|2\.0/)).toHaveCount(0);
  await expect(page.locator(".detail-actions .rating-star").first()).toHaveCSS("font-size", "32px");
  await expect(page.locator(".detail-back button")).toHaveCSS("font-size", "24px");
  await page.getByRole("heading", { name: "内容预览" }).scrollIntoViewIfNeeded();
  await expect.poll(() => previewRequests.length).toBeGreaterThan(0);
  expect(previewRequests.length).toBeLessThan(40);
  expect(originalRequests).toEqual([]);
  await page.getByRole("button", { name: "阅读第 1 页" }).click();
  await expect(page).toHaveURL(new RegExp(`/reader/${fileId}/1`));
  await expect.poll(() => originalRequests).toEqual([1]);
});

test("已删除文件显示明确错误页", async ({ page }) => {
  await mockApi(page, { missingDetail: true });
  await page.goto(`/files/${fileId}`);
  await expect(page.getByRole("heading", { name: "文件不存在" })).toBeVisible();
  await expect(page.getByRole("button", { name: "返回内容库" })).toBeVisible();
});

test("阅读器键盘、边界和尺寸变化保持当前页", async ({ page }) => {
  const originalRequests: number[] = [];
  await mockApi(page, { originalRequests });
  await page.goto(`/reader/${fileId}/1`);
  await expect(page.getByRole("button", { name: "上一页" })).toBeDisabled();
  await page.keyboard.press("ArrowRight");
  await expect(page).toHaveURL(new RegExp(`/reader/${fileId}/2`));
  await page.keyboard.press("End");
  await expect(page).toHaveURL(new RegExp(`/reader/${fileId}/40`));
  await expect(page.getByRole("button", { name: "下一页" })).toBeDisabled();
  await page.setViewportSize({ width: 720, height: 1000 });
  await expect(page).toHaveURL(new RegExp(`/reader/${fileId}/40`));
  await page.keyboard.press("Home");
  await expect(page).toHaveURL(new RegExp(`/reader/${fileId}/1`));
  await page.keyboard.press("Escape");
  await expect(page).toHaveURL(new RegExp(`/files/${fileId}`));
});

test("主题、200% 字体缩放、窄屏和宽屏无关键横向溢出", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  await page.getByLabel("主题").selectOption("dark");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.getByLabel("主题")).toHaveValue("dark");
  for (const viewport of [{ width: 360, height: 800 }, { width: 1600, height: 900 }]) {
    await page.setViewportSize(viewport);
    await page.evaluate(() => { document.documentElement.style.fontSize = "200%"; });
    await expect(page.getByRole("searchbox", { name: "搜索文件名" })).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  }
});
