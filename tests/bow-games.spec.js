// @ts-check
const { test, expect } = require("@playwright/test");

const BASE = process.env.MULLM_URL || "https://10.0.0.165:8100";

// ─── Bow Game Tests ─────────────────────────────────────

const BOW_GAMES = [
  { name: "Ballista Bastion", file: "ballista-bastion" },
  { name: "Wind Runner", file: "wind-runner" },
  { name: "Chrono Archer", file: "chrono-archer" },
];

for (const game of BOW_GAMES) {
  test.describe(`${game.name}`, () => {
    test(`${game.file} loads without JS errors`, async ({ page }) => {
      const errors = [];
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto(`${BASE}/code/ready/${game.file}.html`, { timeout: 30000 });
      await page.waitForLoadState("domcontentloaded");
      await page.waitForTimeout(3000);
      const realErrors = errors.filter((e) => !e.includes("WebGL") && !e.includes("THREE."));
      expect(realErrors).toEqual([]);
    });

    test(`${game.file} has visible canvas`, async ({ page }) => {
      await page.goto(`${BASE}/code/ready/${game.file}.html`, { timeout: 30000 });
      await page.waitForTimeout(5000);
      const canvas = page.locator("canvas").first();
      await expect(canvas).toBeVisible({ timeout: 15000 });
    });

    test(`${game.file} title is not generic template`, async ({ page }) => {
      await page.goto(`${BASE}/code/ready/${game.file}.html`, { timeout: 30000 });
      const title = await page.title();
      expect(title).not.toContain("Part 1");
      expect(title).not.toContain("Template");
      expect(title.length).toBeGreaterThan(3);
    });

    test(`${game.file} has no template boilerplate`, async ({ page }) => {
      await page.goto(`${BASE}/code/ready/${game.file}.html`, { timeout: 30000 });
      const body = await page.content();
      expect(body).not.toContain("class EventBus");
      expect(body).not.toContain("class StorageManager");
      expect(body).toContain("THREE");
    });
  });
}

// ─── Bows Dojo Page Test ─────────────────────────────────
test.describe("Bows Dojo", () => {
  test("bows page loads", async ({ page }) => {
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(`${BASE}/bows`, { timeout: 30000 });
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(3000);
    const title = await page.title();
    expect(title).toContain("Archery");
  });
});
