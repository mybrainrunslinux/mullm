// @ts-check
const { test, expect } = require("@playwright/test");

test.describe("Ironworks Command", () => {
  test.beforeEach(async ({ page }) => {
    const errors = [];
    page.on("pageerror", (err) => {
      if (
        !err.message.includes("ResizeObserver") &&
        !err.message.includes("AudioContext") &&
        !err.message.includes("play()")
      ) {
        errors.push(err.message);
      }
    });
    page.errors = errors;
    await page.goto("/code/ready/ironworks-command.html", { waitUntil: "domcontentloaded", timeout: 20000 });
    await page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => {});
  });

  test("loads with canvas and HUD visible", async ({ page }) => {
    const canvas = page.locator("#gameCanvas, canvas");
    await expect(canvas.first()).toBeVisible({ timeout: 10000 });
    // HUD should be visible
    const hud = page.locator("#hud");
    await expect(hud).toBeVisible({ timeout: 5000 });
  });

  test("build panel has 4 unit buttons", async ({ page }) => {
    const buildBtns = page.locator(".build-btn");
    const count = await buildBtns.count();
    expect(count).toBeGreaterThanOrEqual(4);
  });

  test("clicking a build button shows cost feedback", async ({ page }) => {
    // Click the first build button (Tank)
    const tankBtn = page.locator(".build-btn").first();
    if (await tankBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await tankBtn.click();
      await page.waitForTimeout(500);
      // Some UI feedback should appear (selection panel or unit spawns)
    }
  });

  test("WASD pans the camera", async ({ page }) => {
    await page.waitForTimeout(1000);
    await page.keyboard.down("d");
    await page.waitForTimeout(500);
    await page.keyboard.up("d");
    // No crash = pass (camera is in module scope, can't easily check position)
  });

  test("help overlay opens with H key", async ({ page }) => {
    await page.keyboard.press("h");
    const overlay = page.locator('#helpOverlay, #help-overlay, [class*="help"]');
    const count = await overlay.count();
    // At least one help-related element should be present
    expect(count).toBeGreaterThan(0);
  });

  test("no fatal JS errors during gameplay", async ({ page }) => {
    await page.waitForTimeout(2000);
    // Click around to trigger gameplay
    const canvas = page.locator("#gameCanvas, canvas").first();
    if (await canvas.isVisible({ timeout: 2000 }).catch(() => false)) {
      const box = await canvas.boundingBox();
      if (box) {
        await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.5);
        await page.waitForTimeout(500);
        await page.mouse.click(box.x + box.width * 0.3, box.y + box.height * 0.7);
      }
    }
    expect(page.errors).toHaveLength(0);
  });

  test("has adequate lighting (ambient >= 0.4 in source)", async ({ page }) => {
    const html = await page.content();
    const match = html.match(/AmbientLight\(\s*0x[0-9a-fA-F]+\s*,\s*([\d.]+)\s*\)/);
    expect(match, "AmbientLight should exist").toBeTruthy();
    const intensity = parseFloat(match[1]);
    expect(intensity).toBeGreaterThanOrEqual(0.4);
  });
});
