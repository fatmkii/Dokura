import { expect, test } from "@playwright/test";

test("shows the Dokura stage-zero shell", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle("Dokura");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("你的收藏");
});
