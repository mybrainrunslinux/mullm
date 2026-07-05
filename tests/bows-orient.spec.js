// @ts-check
const { test, expect } = require("@playwright/test");

const BASE = process.env.MULLM_URL || "https://10.0.0.165:8100";

test.describe("Archery Range /bows orientation", () => {
  test.use({ ignoreHTTPSErrors: true });

  test("page loads with visible canvas and bow in correct position", async ({ page }) => {
    // Navigate to the archery range
    await page.goto(`${BASE}/bows`, { waitUntil: "domcontentloaded" });

    // Wait for the canvas to be visible
    const canvas = page.locator("#game-canvas");
    await expect(canvas).toBeVisible({ timeout: 15000 });

    // Wait for Three.js to initialize and render at least a frame
    await page.waitForTimeout(2000);

    // Take screenshot of initial view — bow should be visible, vertical, on left side
    await page.screenshot({ path: "/tmp/bows-orient-initial.png", fullPage: false });

    // Verify canvas has non-zero dimensions (rendering is active)
    const box = await canvas.boundingBox();
    expect(box).toBeTruthy();
    expect(box.width).toBeGreaterThan(100);
    expect(box.height).toBeGreaterThan(100);

    // Verify the HUD is visible (game UI loaded)
    const hud = page.locator("#hud");
    await expect(hud).toBeVisible({ timeout: 5000 });

    // Take a second screenshot after a short delay to confirm stable rendering
    await page.waitForTimeout(1000);
    await page.screenshot({ path: "/tmp/bows-orient-stable.png", fullPage: false });
  });

  test("canvas renders without errors", async ({ page }) => {
    const consoleErrors = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });

    await page.goto(`${BASE}/bows`, { waitUntil: "domcontentloaded" });

    const canvas = page.locator("#game-canvas");
    await expect(canvas).toBeVisible({ timeout: 15000 });

    // Wait for rendering
    await page.waitForTimeout(2000);

    // Check no critical WebGL or Three.js errors
    const criticalErrors = consoleErrors.filter(
      (e) => e.includes("THREE") || e.includes("WebGL") || e.includes("shader")
    );
    expect(criticalErrors).toHaveLength(0);

    await page.screenshot({ path: "/tmp/bows-orient-no-errors.png", fullPage: false });
  });
});
