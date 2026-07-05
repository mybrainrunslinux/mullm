// Validates: /bench page loads last result, comparison table rows are clickable,
// and clicking a row expands a detail panel with visible content.
const { test, expect } = require("@playwright/test");

const BASE = process.env.MULLM_URL || "https://127.0.0.1:8100";

test("bench page auto-loads last result and row click expands detail panel", async ({ page }) => {
  await page.goto(`${BASE}/bench`, { waitUntil: "networkidle" });

  // Full Suite tab should be active with score cards visible
  await expect(page.locator("#he-full-scores")).toBeVisible({ timeout: 15000 });

  // Comparison table must have rows
  const rows = page.locator("tr.he-result-row");
  await expect(rows.first()).toBeVisible({ timeout: 10000 });
  const count = await rows.count();
  expect(count).toBe(164);

  // Click first row
  const firstRow = rows.first();
  const firstKey = await firstRow.getAttribute("id"); // e.g. he-row-full_HumanEval/0
  const taskKey = firstKey.replace("he-row-", "");
  await firstRow.click();

  // Wait for the detail row to become visible (display: table-row)
  const detailRow = page.locator('[id="he-detail-row-' + taskKey + '"]');
  await expect(detailRow).toBeVisible({ timeout: 3000 });

  // Panel should have actual content (not empty)
  const content = page.locator('[id="he-panel-detail-' + taskKey + '"] .he-detail-content');
  await expect(content).not.toBeEmpty({ timeout: 3000 });
});

test("bench page shows LOCAL 100% in Full Suite scores", async ({ page }) => {
  await page.goto(`${BASE}/bench`, { waitUntil: "networkidle" });

  await expect(page.locator("#he-full-scores")).toBeVisible({ timeout: 15000 });
  const localScore = page.locator("#hf-local-score");
  await expect(localScore).toHaveText("100.0%", { timeout: 5000 });
});
