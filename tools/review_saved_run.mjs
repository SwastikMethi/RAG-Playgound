// Read-only rendered review of the live smoke's persisted run; makes no model calls.
import { chromium } from "@playwright/test";
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import assert from "node:assert/strict";

const report = JSON.parse(readFileSync(".data/release/live-report.json", "utf8"));
const token = readFileSync(".env", "utf8").split(/\r?\n/).find((line) => line.startsWith("RAG_APP_TOKEN="))?.slice(14);
assert(token && report.status === "passed");
const output = ".data/release/visuals";
mkdirSync(output, { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
await page.addInitScript((value) => sessionStorage.setItem("rag-token", value), token);
try {
  await page.goto("http://127.0.0.1:8780");
  await page.getByLabel("Project", { exact: true }).selectOption(report.project_id);
  await page.getByRole("button", { name: "History", exact: true }).click();
  await page.locator(".history-list > button").filter({ hasText: "What does NEBULA-42 mean" }).click();
  await page.locator(".answer-lane").first().getByRole("button", { name: "E1", exact: true }).waitFor();
  assert.equal(await page.locator(".answer-lane").count(), 6);
  assert.equal(await page.getByLabel("Question for all selected lanes").inputValue(), "What does NEBULA-42 mean, and how should I recover? Cite the supplied source.");
  assert.equal(await page.locator(".comparison-setup").getAttribute("open"), null);
  assert.match(await page.locator(".comparison-setup > summary").innerText(), /6 selected · Ready/);
  for (const [width, height] of [[1440, 900], [1024, 768], [390, 844]]) {
    await page.setViewportSize({ width, height });
    await page.locator(".answer-grid").scrollIntoViewIfNeeded();
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `Overflow at ${width}`);
    await page.screenshot({ path: `${output}/six-lanes-${width}.png`, fullPage: true });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  let inspected = 0;
  for (const [i, lane] of report.lanes.entries()) {
    const card = page.locator(".answer-lane").nth(i);
    await card.getByRole("button", { name: "workflow", exact: true }).click();
    const steps = card.locator(".step-list button");
    for (let j = 0; j < await steps.count(); j++) {
      await steps.nth(j).click();
      const panel = page.getByRole("complementary", { name: "Execution step" });
      const text = await panel.innerText();
      for (const heading of ["Purpose", "Input", "Action and result", "Measured duration"]) assert(text.toLowerCase().includes(heading.toLowerCase()), `${lane.technique}: missing ${heading}`);
      const stepName = await steps.nth(j).innerText();
      if (stepName.includes("Rerank passages")) assert.match(await panel.locator(".rank-table").innerText(), /fictional-clock-guide/);
      if (stepName.includes("Expand parents")) assert.match(text, /Matched child passages/);
      inspected++;
      if (stepName.match(/Rerank|Expand parent|Navigate sections/) || j === 1) await page.screenshot({ path: `${output}/workflow-${lane.technique}.png` });
      await page.getByRole("button", { name: "Close inspector" }).click();
    }
    await card.getByRole("button", { name: "answer", exact: true }).click();
  }
  const slider = page.getByLabel("Replay position");
  const max = Number(await slider.getAttribute("max"));
  for (const [label, value] of [["start", 0], ["middle", Math.floor(max / 2)], ["end", max]]) {
    await slider.fill(String(value));
    await page.locator(".answer-grid").scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${output}/replay-${label}.png` });
  }
  await page.getByRole("button", { name: "Show final answer" }).click();
  await page.getByLabel("Replay speed").selectOption("4");
  await page.getByRole("checkbox", { name: "Compress long waits" }).check();
  await page.getByRole("button", { name: "Previous step" }).click();
  await page.getByRole("button", { name: "Next step" }).click();
  await page.getByRole("button", { name: "Show final answer" }).click();
  assert.equal((await page.locator(".answer-text").allTextContents()).filter((text) => text.includes("NEBULA-42")).length, 6);
  // Chromium CSS zoom exercises doubled control/text size and overflow at a desktop viewport.
  await page.evaluate(() => document.documentElement.style.zoom = "2");
  await page.locator(".comparison-setup > summary").click();
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  await page.screenshot({ path: `${output}/zoom-200.png`, fullPage: true });
  await page.evaluate(() => document.documentElement.style.zoom = "1");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByLabel("Compare lane").selectOption("5");
  const citation = page.locator(".answer-lane.mobile-active").getByRole("button", { name: "E1", exact: true });
  await citation.focus();
  await page.keyboard.press("Enter");
  await page.getByRole("dialog", { name: "Source evidence" }).waitFor();
  await page.screenshot({ path: `${output}/pageindex-source-mobile.png` });
  await page.keyboard.press("Escape");
  assert(await citation.evaluate((element) => element === document.activeElement));
  const projects = await (await page.request.get("http://127.0.0.1:8780/api/v1/projects?limit=100", { headers: { Authorization: `Bearer ${token}` } })).json();
  const reviewedStates = [];
  await page.setViewportSize({ width: 1440, height: 900 });
  for (const status of ["cancelled", "failed"]) {
    for (const project of projects.items.filter((p) => p.name.startsWith("Live release check"))) {
      const history = await (await page.request.get(`http://127.0.0.1:8780/api/v1/projects/${project.id}/runs?status=${status}`, { headers: { Authorization: `Bearer ${token}` } })).json();
      if (!history.items.length) continue;
      await page.getByLabel("Project", { exact: true }).selectOption(project.id);
      await page.getByRole("button", { name: "History", exact: true }).click();
      await page.getByRole("combobox", { name: "Status", exact: true }).selectOption(status);
      await page.locator(".history-list > button").filter({ hasText: history.items[0].question }).first().click();
      await page.getByLabel("Replay position").waitFor();
      await page.screenshot({ path: `${output}/${status}-desktop.png`, fullPage: true });
      reviewedStates.push(status);
      break;
    }
  }
  assert.deepEqual(reviewedStates, ["cancelled", "failed"]);
  assert.deepEqual(errors, []);
  writeFileSync(".data/release/visual-review.json", JSON.stringify({ status: "passed", viewports: [[1440, 900], [1024, 768], [390, 844]], zoom: "200% CSS zoom in Chromium", reducedMotion: true, inspectedSteps: inspected, replayFrames: [0, Math.floor(max / 2), max], reviewedStates, browserErrors: errors }, null, 2));
  console.log(JSON.stringify({ status: "passed", inspectedSteps: inspected, screenshots: output }));
} finally {
  await browser.close();
}
