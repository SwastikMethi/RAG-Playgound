import { test, expect } from "@playwright/test";

test("upload, prepare, answer, inspect evidence and replay", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByLabel("Application token")
    .fill("fixture-browser-token-no-real-access");
  await page.getByRole("button", { name: "Open workspace" }).click();
  await expect(
    page.getByText("Fixture demonstration · synthetic model responses"),
  ).toBeVisible();
  await page.getByText("New project", { exact: true }).click();
  await page
    .getByLabel("New project name")
    .fill("Browser journey " + Date.now());
  await page.getByRole("button", { name: "Create workspace project" }).click();
  await page.getByRole("button", { name: "Sources", exact: true }).click();
  await page
    .locator("input[type=file]")
    .setInputFiles({
      name: "clock-guide.md",
      mimeType: "text/markdown",
      buffer: Buffer.from(
        "# Clock recovery\nNEBULA-42 means clock drift. Synchronize the clock before reconnecting. 🪐",
      ),
    });
  await expect(
    page.getByRole("button", { name: "Use selected sources" }),
  ).toBeEnabled({ timeout: 20000 });
  await page.getByRole("button", { name: "Use selected sources" }).click();
  await page.getByRole("button", { name: /Keyword · BM25/ }).click();
  await page.getByRole("button", { name: "Prepare selected" }).click();
  await expect(page.getByText("Ready to compare", { exact: true })).toBeVisible(
    { timeout: 20000 },
  );
  await page
    .getByLabel("Question for all selected lanes")
    .fill("What does NEBULA-42 mean?");
  await page.getByRole("button", { name: "Ask all lanes" }).click();
  await expect(page.locator(".answer-text")).toContainText(
    "Synchronize the clock",
    { timeout: 20000 },
  );
  await expect(
    page.getByText("Saved comparison", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "E1", exact: true }).click();
  await expect(
    page.getByRole("complementary", { name: "Source evidence" }),
  ).toContainText("NEBULA-42 means clock drift");
  await page.getByRole("button", { name: "Close inspector" }).click();
  await page.getByRole("button", { name: "workflow", exact: true }).click();
  await page.locator('.step-list button').filter({hasText:'Keyword search'}).click();
  await expect(page.getByRole('complementary',{name:'Execution step'})).toContainText('Purpose');
  await expect(page.getByRole('complementary',{name:'Execution step'})).toContainText('Measured duration');
  await page.screenshot({path:'test-results/workflow-desktop.png',fullPage:true});
  await page.getByRole('button',{name:'Close inspector'}).click();
  await page.getByRole('button',{name:'answer',exact:true}).click();
  await page.screenshot({
    path: "test-results/bm25-desktop.png",
    fullPage: true,
  });
  await page.getByLabel("Replay position").fill("0");
  await expect(page.locator(".answer-text")).not.toContainText(
    "Fixture demonstration:",
  );
  await page.getByRole("button", { name: "Show final answer" }).click();
  await expect(page.locator(".answer-text")).toContainText(
    "Synchronize the clock",
  );
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await page.getByRole("button", { name: "Build export", exact: true }).click();
  await expect(page.getByRole("button", { name: "Download ZIP", exact: true })).toBeVisible({ timeout: 20000 });
  await expect(page.getByRole("complementary", { name: "Export implementation" })).toContainText("live replay · Not performed");
  await page.screenshot({ path: "test-results/export-desktop.png", fullPage: true });
  const downloading = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download ZIP", exact: true }).click();
  const download = await downloading;
  expect(download.suggestedFilename()).toBe("rag-implementation.zip");
  await page.getByRole("button", { name: "Close inspector" }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "test-results/bm25-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
