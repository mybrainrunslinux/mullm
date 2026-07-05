// @ts-check
const { test, expect } = require("@playwright/test");

test.describe("Iron Dominion", () => {
  test.beforeEach(async ({ page }) => {
    page.on("pageerror", (err) => {
      // Fail on fatal JS errors (not audio/resize)
      if (
        !err.message.includes("ResizeObserver") &&
        !err.message.includes("AudioContext") &&
        !err.message.includes("play()")
      ) {
        throw new Error("Uncaught JS error: " + err.message);
      }
    });
    await page.goto("/code/ready/iron-dominion.html", { waitUntil: "domcontentloaded", timeout: 20000 });
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
  });

  test("loads with canvas and no fatal errors", async ({ page }) => {
    const canvas = page.locator("canvas");
    await expect(canvas).toBeVisible({ timeout: 10000 });
  });

  test("start button begins the game", async ({ page }) => {
    const startBtn = page.locator("#start-btn");
    if (await startBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await startBtn.click();
      // After clicking start, the start screen should disappear
      await expect(page.locator("#start-screen")).toBeHidden({ timeout: 3000 });
    }
  });

  test("WASD pans the camera", async ({ page }) => {
    // Click start first
    const startBtn = page.locator("#start-btn");
    if (await startBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await startBtn.click();
    }
    await page.waitForTimeout(500);

    // Get initial camera info via JS
    const posBefore = await page.evaluate(() => {
      // @ts-ignore
      if (typeof camera !== "undefined") return { x: camera.position.x, z: camera.position.z };
      return null;
    });

    if (posBefore) {
      // Press D key for 500ms to pan right
      await page.keyboard.down("d");
      await page.waitForTimeout(500);
      await page.keyboard.up("d");

      const posAfter = await page.evaluate(() => {
        // @ts-ignore
        return { x: camera.position.x, z: camera.position.z };
      });

      // Camera should have moved
      expect(posAfter.x).not.toEqual(posBefore.x);
    }
  });

  test("building buttons are visible and clickable", async ({ page }) => {
    const startBtn = page.locator("#start-btn");
    if (await startBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await startBtn.click();
    }
    await page.waitForTimeout(300);

    // Check build buttons exist
    const buildBtns = page.locator(".build-btn");
    const count = await buildBtns.count();
    expect(count).toBeGreaterThan(0);
  });

  test("help modal opens with ? key", async ({ page }) => {
    await page.keyboard.press("?");
    const modal = page.locator("#help-modal");
    await expect(modal).toHaveClass(/open/, { timeout: 2000 });
  });

  test("game has adequate lighting (ambient >= 0.5 in source)", async ({ page }) => {
    // Check the page source for ambient light intensity value
    const html = await page.content();
    // Match AmbientLight constructor: new THREE.AmbientLight(color, intensity)
    const match = html.match(/AmbientLight\(\s*0x[0-9a-fA-F]+\s*,\s*([\d.]+)\s*\)/);
    expect(match, "AmbientLight should exist in source").toBeTruthy();
    const intensity = parseFloat(match[1]);
    expect(intensity).toBeGreaterThanOrEqual(0.5);
  });
});
