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
  const projectName = "Browser journey " + Date.now();
  await page
    .getByLabel("New project name")
    .fill(projectName);
  await page.getByRole("button", { name: "Create workspace project" }).click();
  await expect(page.getByLabel("Project", { exact: true }).locator("option:checked")).toHaveText(projectName);
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
  const sourceDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download original source" }).click();
  expect((await sourceDownload).suggestedFilename()).toBe("source.txt");
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
  await page.getByText("Your feedback", { exact: true }).click();
  await page.getByLabel("Was this answer useful?").selectOption("helpful");
  await page.getByLabel("Answer note", { exact: true }).fill("The source supports this answer.");
  await page.getByRole("button", { name: "Save feedback", exact: true }).click();
  await expect(page.getByText("Feedback saved", { exact: true })).toBeVisible();
  await page.getByText("Your comparison notes", { exact: true }).click();
  await page.getByLabel("Preferred answer").selectOption({ index: 1 });
  await page.getByLabel("Comparison note", { exact: true }).fill("Checked the cited passage.");
  await page.getByRole("button", { name: "Save comparison note", exact: true }).click();
  await expect(page.getByText("Comparison note saved", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "History", exact: true }).click();
  await page.getByLabel("Search question history").fill("NEBULA-42");
  await page.getByRole("combobox", { name: "Status", exact: true }).selectOption("completed");
  await page.locator(".history-list > button").first().click();
  await page.getByText("Your feedback · helpful", { exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Answer note", exact: true })).toHaveValue("The source supports this answer.");
  await page.getByText("Your feedback · helpful", { exact: true }).click();
  await page.getByRole("button", { name: "Run this lane again" }).click();
  await expect(page.locator(".answer-text")).toContainText("Synchronize the clock");
  await expect(page.getByText("Saved comparison", { exact: false })).toBeVisible();
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
  await page.getByRole("button", { name: "E1", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: "Source evidence" })).toBeVisible();
  await page.keyboard.press("Tab");
  expect(await page.evaluate(() => !!document.activeElement?.closest('[role="dialog"]'))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "E1", exact: true })).toBeFocused();
  await page.getByRole("button", { name: "Setup", exact: true }).click();
  await expect(page.getByText("Database, migrations and artifact storage are ready.")).toBeVisible();
  await page.screenshot({ path: "test-results/setup-mobile.png", fullPage: true });
  await page.getByRole("button", { name: "Sources", exact: true }).click();
  await page.getByRole("button", { name: "Delete clock-guide.md", exact: true }).click();
  await expect(page.getByRole("button", { name: "Delete source permanently" })).toBeDisabled();
  await page.getByLabel("Delete this source and all listed dependent content").check();
  await page.getByRole("button", { name: "Delete source permanently" }).click();
  await expect(page.getByRole("button", { name: "Delete source permanently" })).not.toBeVisible({ timeout: 20000 });
  await page.getByRole("button", { name: "History", exact: true }).click();
  await expect(page.locator(".history-list > button")).toHaveCount(0);
});
