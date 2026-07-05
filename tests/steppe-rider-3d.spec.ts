// @ts-check
import { test, expect } from "@playwright/test";

const BASE = process.env.MULLM_URL || "https://10.0.0.165:8100";
const URL = `${BASE}/code/ready/steppe-rider-3d.html`;

test.describe("Steppe Rider 3D", () => {
  test("boots without JS errors and renders canvas", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(URL, { timeout: 30000 });
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(4000);
    const canvas = page.locator("canvas").first();
    await expect(canvas).toBeVisible({ timeout: 15000 });
    const realErrors = errors.filter(
      (e) => !e.includes("WebGL") && !e.includes("THREE.") && !e.includes("favicon")
    );
    expect(realErrors).toEqual([]);
  });

  test("start button enables after asset load and starts the game", async ({ page }) => {
    await page.goto(URL, { timeout: 30000 });
    // Wait up to 12s for ready (GLB load timeout is 6s, plus parse)
    await page.waitForFunction(() => (window as any).GAME && (window as any).GAME.ready, null, {
      timeout: 15000,
    });
    const startBtn = page.locator("#start-btn");
    await expect(startBtn).toBeEnabled();
    await startBtn.click();
    // splash hides
    await expect(page.locator("#splash")).toBeHidden();
    const running = await page.evaluate(() => (window as any).GAME.running);
    expect(running).toBe(true);
  });

  test("can fire arrows via test hooks", async ({ page }) => {
    await page.goto(URL, { timeout: 30000 });
    await page.waitForFunction(() => (window as any).GAME && (window as any).GAME.ready, null, {
      timeout: 15000,
    });
    await page.locator("#start-btn").click();
    await page.waitForTimeout(300);
    // Aim upward so arrow doesn't immediately ground-hit (gravity applies)
    await page.mouse.move(400, 100);
    await page.waitForTimeout(50);
    // Use test hook to fire an arrow
    await page.evaluate(() => (window as any).GAME.testHooks.fire());
    // Quiver decrement is the durable signal that fire happened
    const quiver = await page.evaluate(() => (window as any).GAME.quiver);
    expect(quiver).toBeLessThan(15);
    // Arrow may have grounded already; just confirm one was at minimum spawned
    // by checking the arrow pool grew (recycled arrows go to pool)
    const poolPlusFlight = await page.evaluate(
      () => (window as any).GAME.arrows.length + (window as any).GAME.arrowPool.length
    );
    expect(poolPlusFlight).toBeGreaterThan(0);
  });

  test("game is completable: spawn enemy then kill clears wave and advances", async ({ page }) => {
    await page.goto(URL, { timeout: 30000 });
    await page.waitForFunction(() => (window as any).GAME && (window as any).GAME.ready, null, {
      timeout: 15000,
    });
    await page.locator("#start-btn").click();
    // Force first wave to start immediately
    await page.evaluate(() => (window as any).GAME.testHooks.nextWave());
    await page.waitForTimeout(300);
    await page.waitForFunction(
      () => (window as any).GAME.enemies.length > 0 || (window as any).GAME.waveActive,
      null,
      { timeout: 5000 }
    );
    // Kill them all
    await page.evaluate(() => (window as any).GAME.testHooks.killAll());
    await page.waitForTimeout(200);
    const enemiesLeft = await page.evaluate(() => (window as any).GAME.enemies.length);
    // If shaman split, kill again
    if (enemiesLeft > 0) {
      await page.evaluate(() => (window as any).GAME.testHooks.killAll());
      await page.waitForTimeout(200);
    }
    const score = await page.evaluate(() => (window as any).GAME.score);
    expect(score).toBeGreaterThan(0);
    // After empty enemies, wave should advance
    await page.waitForFunction(() => (window as any).GAME.wave > 1, null, { timeout: 5000 });
    const wave = await page.evaluate(() => (window as any).GAME.wave);
    expect(wave).toBeGreaterThan(1);
  });

  test("ESC pauses and unpauses; arrow type cycling works", async ({ page }) => {
    await page.goto(URL, { timeout: 30000 });
    await page.waitForFunction(() => (window as any).GAME && (window as any).GAME.ready, null, {
      timeout: 15000,
    });
    await page.locator("#start-btn").click();
    await page.waitForTimeout(200);
    // Cycle to fire arrow type
    await page.keyboard.press("2");
    expect(await page.evaluate(() => (window as any).GAME.arrowType)).toBe("fire");
    await page.keyboard.press("q");
    expect(await page.evaluate(() => (window as any).GAME.arrowType)).toBe("ap");
    // Pause
    await page.keyboard.press("Escape");
    expect(await page.evaluate(() => (window as any).GAME.paused)).toBe(true);
    await page.keyboard.press("Escape");
    expect(await page.evaluate(() => (window as any).GAME.paused)).toBe(false);
  });

  test("accessibility: colorblind toggle cycles modes", async ({ page }) => {
    await page.goto(URL, { timeout: 30000 });
    await page.waitForFunction(() => (window as any).GAME && (window as any).GAME.ready, null, {
      timeout: 15000,
    });
    const cbBtn = page.locator("#cb-btn");
    await cbBtn.click();
    expect(await page.evaluate(() => document.body.classList.contains("cb-deuter"))).toBe(true);
    await cbBtn.click();
    expect(await page.evaluate(() => document.body.classList.contains("cb-protan"))).toBe(true);
    await cbBtn.click();
    expect(await page.evaluate(() => document.body.classList.contains("cb-tritan"))).toBe(true);
    await cbBtn.click();
    expect(await page.evaluate(() => (window as any).GAME.cbMode)).toBe(0);
  });
});
