// @ts-check
const { test, expect } = require("@playwright/test");
const BASE = process.env.MULLM_URL || "https://127.0.0.1:8100";

test.use({ ignoreHTTPSErrors: true });

test("walks page loads", async ({ page }) => {
  await page.goto(BASE + "/walks");
  await expect(page.locator("canvas")).toBeVisible({ timeout: 5000 });
});

test("play button exists and toggles", async ({ page }) => {
  await page.goto(BASE + "/walks");
  const btn = page.locator("button.control-btn");
  await expect(btn).toBeVisible({ timeout: 5000 });
  // Wait for model auto-load to settle (sets button to Pause)
  await expect(btn).toHaveText(/pause/i, { timeout: 5000 });
  // Click to pause — button should switch to Play
  await btn.click();
  await expect(btn).toHaveText(/play/i, { timeout: 2000 });
  // Click again to play — button should switch back to Pause
  await btn.click();
  await expect(btn).toHaveText(/pause/i, { timeout: 2000 });
});

test("walk/run/waddle presets clickable", async ({ page }) => {
  await page.goto(BASE + "/walks");
  for (const preset of ["Walk", "Run", "Waddle"]) {
    // Use exact text match to avoid collision with GLB clip buttons (lowercase names)
    const btn = page.getByRole("button", { name: preset, exact: true });
    await expect(btn).toBeVisible({ timeout: 3000 });
    await btn.click();
  }
});
