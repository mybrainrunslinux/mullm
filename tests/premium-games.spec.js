// @ts-check
const { test, expect } = require("@playwright/test");

const BASE = process.env.MULLM_URL || "https://10.0.0.165:8100";

const GAMES = [
  { name: "Corsair's Edge", file: "corsairs-edge" },
  { name: "Crystal Sanctum", file: "crystal-sanctum" },
  { name: "Archer's Crossing", file: "archers-crossing" },
  { name: "Crystal Match", file: "crystal-match" },
];

for (const game of GAMES) {
  test.describe(`${game.name}`, () => {
    test(`${game.file} loads without JS errors`, async ({ page }) => {
      const errors = [];
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto(`${BASE}/code/ready/${game.file}.html`, { timeout: 30000 });
      await page.waitForLoadState("domcontentloaded");
      await page.waitForTimeout(3000);
      const realErrors = errors.filter((e) => !e.includes("WebGL") && !e.includes("THREE.") && !e.includes("404"));
      expect(realErrors).toEqual([]);
    });

    test(`${game.file} has visible canvas`, async ({ page }) => {
      await page.goto(`${BASE}/code/ready/${game.file}.html`, { timeout: 30000 });
      await page.waitForTimeout(5000);
      const canvas = page.locator("canvas").first();
      await expect(canvas).toBeVisible({ timeout: 15000 });
    });

    test(`${game.file} title is real`, async ({ page }) => {
      await page.goto(`${BASE}/code/ready/${game.file}.html`, { timeout: 30000 });
      const title = await page.title();
      expect(title).not.toContain("Part 1");
      expect(title.length).toBeGreaterThan(3);
    });

    test(`${game.file} uses Three.js`, async ({ page }) => {
      await page.goto(`${BASE}/code/ready/${game.file}.html`, { timeout: 30000 });
      const body = await page.content();
      expect(body).toContain("THREE");
      expect(body).not.toContain("class EventBus");
    });
  });
}
