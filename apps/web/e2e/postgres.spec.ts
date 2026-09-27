import { test, expect } from "@playwright/test";

test("read-only PostgreSQL preview, snapshot, answer and credential removal", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Application token").fill("fixture-browser-token-no-real-access");
  await page.getByRole("button", { name: "Open workspace" }).click();
  await page.getByText("New project", { exact: true }).click();
  const name = "PostgreSQL browser " + Date.now();
  await page.getByLabel("New project name").fill(name);
  await page.getByRole("button", { name: "Create workspace project" }).click();
  await expect(page.getByLabel("Project", { exact: true }).locator("option:checked")).toHaveText(name);
  await page.getByRole("button", { name: "Sources", exact: true }).click();
  await page.getByRole("button", { name: "Connect PostgreSQL" }).click();
  for (const [label, value] of Object.entries({ "Connection name": "Browser fixture", Host: "127.0.0.1", Port: "6544", Database: "ragplayground_browser_test", Username: "rag_browser_reader", Password: "browser-fixture-only", "Allowed schemas (comma separated)": "browser_fixture" })) {
    await page.getByLabel(label, { exact: true }).fill(value);
  }
  await page.getByRole("combobox", { name: "TLS", exact: true }).selectOption("disable");
  await page.getByRole("button", { name: "Save and inspect" }).click();
  await expect(page.getByLabel("Approved relation").locator("option")).toHaveCount(2);
  await page.getByLabel("Approved relation").selectOption("0");
  await expect(page.getByLabel("Key column id")).toBeChecked();
  await expect(page.getByLabel("Text column body")).toBeChecked();
  await page.getByRole("button", { name: "Preview five records" }).click();
  await expect(page.locator(".snapshot-preview")).toContainText("NEBULA-42 means clock drift");
  await page.screenshot({ path: "test-results/postgres-desktop.png", fullPage: true });
  await page.getByRole("button", { name: "Capture snapshot", exact: true }).click();
  await expect(page.getByRole("button", { name: "Close inspector" })).not.toBeVisible({ timeout: 20000 });
  await page.getByRole("button", { name: "Use selected sources" }).click();
  await page.getByRole("button", { name: /Keyword · BM25/ }).click();
  await page.getByRole("button", { name: "Prepare selected" }).click();
  await expect(page.getByText("Ready to compare", { exact: true })).toBeVisible();
  await page.getByLabel("Question for all selected lanes").fill("What does NEBULA-42 mean?");
  await page.getByRole("button", { name: "Ask all lanes" }).click();
  await expect(page.locator(".answer-text")).toContainText("Synchronize the system clock");
  await page.getByRole("button", { name: "E1", exact: true }).click();
  await expect(page.locator(".evidence-label")).toContainText('Record {"id":1}');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "test-results/postgres-evidence-mobile.png", fullPage: true });
  await page.getByRole("button", { name: "Close inspector" }).click();
  await page.getByRole("button", { name: "Sources", exact: true }).click();
  await page.getByRole("button", { name: "Connect PostgreSQL" }).click();
  await page.getByLabel("Database connection").selectOption({ index: 1 });
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Remove connection" }).click();
  await expect(page.getByLabel("Database connection").locator("option")).toHaveCount(1);
});
