// @ts-check
const { test, expect } = require("@playwright/test");

const BASE = process.env.MULLM_URL || "https://10.0.0.165:8100";

// ─── Sword Game Tests ─────────────────────────────────────

const SWORD_GAMES = [
  { name: "Eternal Sands", file: "eternal-sands" },
  { name: "Blade Ascendant", file: "blade-ascendant" },
  { name: "Rune Blade Chronicles", file: "rune-blade-chronicles" },
];

for (const game of SWORD_GAMES) {
  test.describe(`${game.name}`, () => {
    test(`${game.file} loads without JS errors`, async ({ page }) => {
      const errors = [];
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto(`${BASE}/code/ready/${game.file}.html`, { timeout: 30000 });
      await page.waitForLoadState("domcontentloaded");
      await page.waitForTimeout(3000); // Three.js init time
      // Filter out known Three.js warnings that aren't errors
      const realErrors = errors.filter((e) => !e.includes("WebGL") && !e.includes("THREE."));
      expect(realErrors).toEqual([]);
    });

    test(`${game.file} has visible canvas`, async ({ page }) => {
      await page.goto(`${BASE}/code/ready/${game.file}.html`, { timeout: 30000 });
      // Three.js creates canvas dynamically via renderer.domElement
      await page.waitForTimeout(5000);
      const canvas = page.locator("canvas").first();
      await expect(canvas).toBeVisible({ timeout: 15000 });
    });

    test(`${game.file} has HUD elements`, async ({ page }) => {
      await page.goto(`${BASE}/code/ready/${game.file}.html`, { timeout: 30000 });
      await page.waitForTimeout(3000);
      // At least one of these HUD selectors should exist
      const hudSelectors = [
        "#hud",
        ".hud",
        "[class*='hud']",
        "[id*='hud']",
        "[class*='health']",
        "[id*='health']",
        "[class*='score']",
        "[id*='score']",
      ];
      let foundHud = false;
      for (const sel of hudSelectors) {
        const count = await page.locator(sel).count();
        if (count > 0) {
          foundHud = true;
          break;
        }
      }
      expect(foundHud).toBe(true);
    });

    test(`${game.file} title is not generic template`, async ({ page }) => {
      await page.goto(`${BASE}/code/ready/${game.file}.html`, { timeout: 30000 });
      const title = await page.title();
      // Reject boilerplate titles
      expect(title).not.toContain("Part 1");
      expect(title).not.toContain("Template");
      expect(title.length).toBeGreaterThan(3);
    });

    test(`${game.file} has no template boilerplate`, async ({ page }) => {
      await page.goto(`${BASE}/code/ready/${game.file}.html`, { timeout: 30000 });
      // Check page doesn't have generic SPA boilerplate
      const body = await page.content();
      expect(body).not.toContain("class EventBus");
      expect(body).not.toContain("class Component");
      expect(body).not.toContain("class StorageManager");
      // Must have Three.js
      expect(body).toContain("THREE");
    });
  });
}
