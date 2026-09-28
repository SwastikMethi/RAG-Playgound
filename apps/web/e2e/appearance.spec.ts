import { test, expect } from "@playwright/test";

test("sidebar stays pinned and the chosen color theme persists", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".rail")).toHaveCSS("position", "sticky");
  await page.getByRole("button", { name: "Use dark mode" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.screenshot({ path: "test-results/dark-mode-desktop.png", fullPage: true });
  await page.getByRole("button", { name: "Use light mode" }).click();

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".rail")).toHaveCSS("position", "static");
});
