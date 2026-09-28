import { test, expect } from "@playwright/test";

test("multi-file uploads explain the corpus limit and allow 50 sources", async ({ page }) => {
  test.setTimeout(120000);
  let submittedCorpora = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && /\/corpus-versions$/.test(request.url())) submittedCorpora++;
  });
  await page.goto("/");
  await page.getByText("New project", { exact: true }).click();
  const projectName = "Source limit " + Date.now();
  await page.getByLabel("New project name").fill(projectName);
  await page.getByRole("button", { name: "Create workspace project" }).click();
  await expect(page.getByLabel("Project", { exact: true }).locator("option:checked")).toHaveText(projectName);
  await page.getByRole("button", { name: "Sources", exact: true }).click();
  await page.locator("input[type=file]").setInputFiles(Array.from({ length: 51 }, (_, i) => ({
    name: `source-${i + 1}.txt`,
    mimeType: "text/plain",
    buffer: Buffer.from(`Document ${i + 1}: NEBULA-42 means clock drift.`),
  })));
  await expect(page.locator(".source-footer")).toContainText(/51 \/ 50 selected · .+ \/ 100 MiB/, { timeout: 20000 });
  await expect(page.getByRole("alert")).toContainText("Select at most 50 sources per corpus. Deselect 1 source to continue.");
  await expect(page.getByRole("button", { name: "Use selected sources" })).toBeDisabled();
  expect(submittedCorpora).toBe(0);
  await page.getByRole("button", { name: "Use selected sources" }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: "test-results/source-limit-warning-desktop.png" });
  const lastSource = page.getByLabel("Include source-51.txt", { exact: true });
  await expect(lastSource).toBeEnabled({ timeout: 90000 });
  await lastSource.uncheck();
  await expect(page.locator(".source-footer")).toContainText("50 / 50 selected");
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.screenshot({ path: "test-results/fifty-sources-desktop.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Use selected sources" }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: "test-results/fifty-sources-mobile.png" });
  const frozen = page.waitForResponse((response) => response.request().method() === "POST" && /\/corpus-versions$/.test(response.url()));
  await page.getByRole("button", { name: "Use selected sources" }).click();
  const response = await frozen;
  expect(response.status()).toBe(201);
  expect((await response.json()).source_ids).toHaveLength(50);
  await expect(page.getByRole("combobox", { name: "CORPUS" }).locator("option:checked")).toContainText("50 sources");
  expect(submittedCorpora).toBe(1);
});
