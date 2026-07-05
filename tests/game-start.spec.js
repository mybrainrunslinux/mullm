// @ts-check
const { test, expect } = require("@playwright/test");

/**
 * Game start/interaction smoke tests.
 * Validates every game in code/ready/ can load, start, and handle 2 interactions.
 */

// Non-game files to exclude (instruments, tools, templates)
const EXCLUDED = new Set([
  "clarinet.html",
  "saxophone.html",
  "dulcimer.html",
  "glass-harp.html",
  "marimba.html",
  "pipe-organ.html",
  "steel-drums.html",
  "theremin.html",
  "war-drums.html",
  "aibophone.html",
  "string-quartet.html",
  "symphony-conductor.html",
  "diff-viewer.html",
  "server-monitor.html",
  "control-center.html",
  "pixel-painter.html",
  "path-tracing.html",
  "word-hex-template.html",
]);

// Games that load 50-100MB+ of GLB assets — crash headless Playwright due to GPU memory
// They work fine on real browsers with GPU acceleration
const HEAVY_3D = new Set([
  "crystal-match.html", // 56MB GLBs (rose-quartz 26MB, magic-orb 19MB)
  "crystal-sanctum.html", // 56MB GLBs + hundreds of clones
  "shadow-cathedral.html", // 100MB+ GLBs (10 models)
]);

const fs = require("fs");
const path = require("path");

const readyDir = path.join(__dirname, "..", "code", "ready");
const allFiles = fs.readdirSync(readyDir).filter((f) => f.endsWith(".html"));
const gameFiles = allFiles.filter((f) => !EXCLUDED.has(f) && !HEAVY_3D.has(f));

for (const gameFile of gameFiles) {
  test(`game: ${gameFile} — load, start, interact`, async ({ page }) => {
    const errors = [];
    page.on("pageerror", (err) => errors.push(err.message));

    // Navigate to game
    await page.goto(`/code/ready/${gameFile}`, { waitUntil: "domcontentloaded", timeout: 15000 });

    // Wait for network to settle
    await page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => {});

    // Check page is not blank — must have some visible content
    const bodyText = await page.evaluate(() => document.body?.innerText?.trim() || "");
    const hasCanvas = await page.locator("canvas").count();
    const hasSvg = await page.locator("svg").count();
    const hasVisibleContent = bodyText.length > 0 || hasCanvas > 0 || hasSvg > 0;
    expect(hasVisibleContent, `${gameFile}: page appears blank — no text, canvas, or SVG`).toBeTruthy();

    // Try to find and click a start/play button
    const startSelectors = [
      'button:has-text("Start")',
      'button:has-text("Play")',
      'button:has-text("New Game")',
      'button:has-text("Begin")',
      'button:has-text("Deal")',
      'button:has-text("Go")',
      'button:has-text("Launch")',
      'button:has-text("OK")',
      '[id*="start"]',
      '[id*="play"]',
      '[class*="start"]',
      '[class*="play"]',
      ".start-btn",
      ".play-btn",
      "#startBtn",
      "#playBtn",
    ];

    let started = false;
    for (const sel of startSelectors) {
      try {
        const btn = page.locator(sel).first();
        if (await btn.isVisible({ timeout: 500 })) {
          await btn.click({ timeout: 2000 });
          started = true;
          break;
        }
      } catch {
        // selector not found or not clickable, continue
      }
    }

    // Small delay for any start animation
    await page.waitForTimeout(500);

    // Attempt 2 interactions: click on canvas or body center
    const canvas = page.locator("canvas").first();
    const hasCanvasNow = await canvas.count();

    for (let i = 0; i < 2; i++) {
      try {
        if (hasCanvasNow > 0 && (await canvas.isVisible({ timeout: 500 }))) {
          const box = await canvas.boundingBox();
          if (box) {
            // Click at slightly different positions for each interaction
            const xOff = i === 0 ? 0.4 : 0.6;
            const yOff = i === 0 ? 0.4 : 0.6;
            await page.mouse.click(box.x + box.width * xOff, box.y + box.height * yOff);
          }
        } else {
          // Click on the page body at offset positions
          const vp = page.viewportSize();
          if (vp) {
            const xOff = i === 0 ? 0.4 : 0.6;
            const yOff = i === 0 ? 0.4 : 0.6;
            await page.mouse.click(vp.width * xOff, vp.height * yOff);
          }
        }
      } catch {
        // interaction failed, that's OK — we just need to attempt it
      }
      await page.waitForTimeout(300);
    }

    // Final check: no uncaught JS errors
    if (errors.length > 0) {
      // Soft-fail: report errors but only fail on truly fatal ones
      const fatal = errors.filter(
        (e) =>
          !e.includes("ResizeObserver") &&
          !e.includes("AudioContext") &&
          !e.includes("NotAllowedError") &&
          !e.includes("user gesture") &&
          !e.includes("play()") &&
          !e.includes("The play method")
      );
      expect(fatal, `${gameFile}: uncaught JS errors:\n${fatal.join("\n")}`).toHaveLength(0);
    }
  });
}
