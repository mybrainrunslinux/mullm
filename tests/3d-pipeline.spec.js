// 3D Pipeline end-to-end test
// Tests: text-to-3D one-shot, preview workflow, image upload, gallery display
const { test, expect } = require("@playwright/test");

const BASE = process.env.MULLM_URL || "https://localhost:8100";

test.describe("3D Pipeline — end to end", () => {
  test.use({ ignoreHTTPSErrors: true });

  test("/3d page loads with status cards showing green", async ({ page }) => {
    await page.goto(`${BASE}/3d`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(4000);

    // Status grid should exist
    const grid = page.locator("#status-grid");
    await expect(grid).toBeVisible();

    // muLLM Router should be green/Online
    const routerCard = grid.locator(".status-card").first();
    await expect(routerCard).toContainText("Online");

    // GPU VRAM should show a number
    const vramText = await grid.locator(".status-card").last().textContent();
    expect(vramText).toContain("GB");
  });

  test("/3d page has generate form with correct controls", async ({ page }) => {
    await page.goto(`${BASE}/3d`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2000);

    // Text prompt textarea
    await expect(page.locator("#gen-prompt")).toBeVisible();

    // Style dropdown
    await expect(page.locator("#gen-style")).toBeVisible();

    // Source dropdown with Auto as default
    const source = page.locator("#gen-source");
    await expect(source).toBeVisible();
    const defaultVal = await source.inputValue();
    expect(defaultVal).toBe("auto");

    // Workflow dropdown
    await expect(page.locator("#gen-workflow")).toBeVisible();

    // Generate button
    const btn = page.locator("#gen-btn");
    await expect(btn).toBeVisible();
    await expect(btn).toContainText("Generate 3D Model");

    // Input mode tabs
    await expect(page.locator("#tab-text")).toBeVisible();
    await expect(page.locator("#tab-image")).toBeVisible();
  });

  test("pipeline diagram steps are clickable and show details", async ({ page }) => {
    await page.goto(`${BASE}/3d`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2000);

    // Click "Classify" step
    const classifyStep = page.locator(".pipeline-step").nth(1);
    await classifyStep.click();

    // Detail panel should appear
    const detail = page.locator("#detail-classify");
    await expect(detail).toBeVisible();
    await expect(detail).toContainText("complexity");

    // Click again to close
    await classifyStep.click();
    await expect(detail).not.toBeVisible();
  });

  test("Free VRAM button works", async ({ page }) => {
    await page.goto(`${BASE}/3d`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(3000);

    // Find and click Free VRAM button
    const btn = page.locator("button", { hasText: "Free VRAM" });
    await expect(btn).toBeVisible();
    await btn.click();

    // Should show a toast
    await page.waitForTimeout(2000);
  });

  test("ComfyUI status shows as running", async ({ page }) => {
    // Check via API
    const response = await page.request.get(`${BASE}/api/comfyui/status`);
    expect(response.ok()).toBeTruthy();
    const data = await response.json();
    expect(data.running).toBe(true);
    expect(data.gpu).toContain("5090");
  });

  test("existing 3D assets appear in gallery", async ({ page }) => {
    await page.goto(`${BASE}/3d`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(4000);

    // Gallery should have asset cards
    const cards = page.locator(".asset-card:not(.skeleton):not(.generating)");
    const count = await cards.count();
    expect(count).toBeGreaterThan(0);

    // First card should have a name
    const firstName = await cards.first().locator(".asset-name").textContent();
    expect(firstName.length).toBeGreaterThan(0);
  });

  test("one-shot Direct text-to-3D generates and appears in gallery", async ({ page }) => {
    test.setTimeout(180000); // 3 minutes

    await page.goto(`${BASE}/3d`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(3000);

    // Count assets before
    const beforeCount = await page.locator(".asset-card:not(.skeleton):not(.generating)").count();

    // Fill prompt
    await page.fill("#gen-prompt", "test cube");
    await page.selectOption("#gen-style", "low-poly");
    await page.selectOption("#gen-source", "comfyui");
    await page.selectOption("#gen-workflow", "direct");

    // Click generate
    await page.click("#gen-btn");

    // Should show generating card immediately
    await page.waitForTimeout(2000);
    const genCard = page.locator(".asset-card.generating");
    // May or may not be visible depending on timing

    // Wait for completion — poll the gallery for a new asset
    let found = false;
    for (let i = 0; i < 60; i++) {
      await page.waitForTimeout(3000);
      // Check if gallery refreshed with new asset
      const afterCount = await page.locator(".asset-card:not(.skeleton):not(.generating)").count();
      if (afterCount > beforeCount) {
        found = true;
        break;
      }
      // Also check progress text
      const progress = await page
        .locator("#progress-label-text")
        .textContent()
        .catch(() => "");
      if (progress.includes("Complete") || progress.includes("$0.00")) {
        // Refresh gallery manually
        await page.evaluate(() => {
          if (typeof fetchAssets === "function") fetchAssets();
        });
        await page.waitForTimeout(2000);
        const finalCount = await page.locator(".asset-card:not(.skeleton):not(.generating)").count();
        if (finalCount > beforeCount) {
          found = true;
          break;
        }
      }
    }

    expect(found).toBe(true);
  });

  test("/api/3d-assets returns assets with metadata", async ({ page }) => {
    const response = await page.request.get(`${BASE}/api/3d-assets`);
    expect(response.ok()).toBeTruthy();
    const data = await response.json();
    expect(data.total).toBeGreaterThan(0);
    expect(data.assets[0]).toHaveProperty("name");
    expect(data.assets[0]).toHaveProperty("url");
    expect(data.assets[0]).toHaveProperty("source");
  });

  test("Image to 3D tab switches correctly", async ({ page }) => {
    await page.goto(`${BASE}/3d`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2000);

    // Click Image to 3D tab
    await page.click("#tab-image");

    // Upload area should be visible, text area hidden
    await expect(page.locator("#input-image-area")).toBeVisible();
    await expect(page.locator("#input-text-area")).not.toBeVisible();

    // Click back to Text
    await page.click("#tab-text");
    await expect(page.locator("#input-text-area")).toBeVisible();
    await expect(page.locator("#input-image-area")).not.toBeVisible();
  });
});
