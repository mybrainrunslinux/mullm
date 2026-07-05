const { test, expect } = require("@playwright/test");
const BASE = process.env.MULLM_URL || "https://localhost:8100";

test.describe("Swords Dojo Quick Check", () => {
  test.use({ ignoreHTTPSErrors: true });

  test("loads, shows sword bar, no JS crashes", async ({ page }) => {
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => {
      if (m.type() === "error") console.log("CONSOLE ERROR:", m.text());
    });

    await page.goto(`${BASE}/swords`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(6000);

    // Canvas visible
    const canvas = page.locator("canvas");
    await expect(canvas).toBeVisible();

    // Check sword selector
    const selector = page.locator("#sword-select");
    await expect(selector).toBeVisible();

    // Procedural katana should always be there
    const katana = page.locator('#sword-select option[value="procedural"]');
    await expect(katana).toHaveCount(1);
    const generate = page.locator('#sword-select option[value="__generate"]');
    await expect(generate).toHaveCount(1);

    const swordgunOptions = page.locator('#sword-select option', { hasText: /swordgun/i });
    await expect(swordgunOptions).toHaveCount(0);

    // Click Enter Dojo to dismiss overlay
    const startBtn = page.locator("#start-btn");
    await expect(startBtn).toBeVisible();
    await startBtn.click();
    await page.waitForTimeout(2000);

    // Overlay should be hidden now
    const overlay = page.locator("#start-overlay");
    await expect(overlay).not.toBeVisible();

    // Check for game-breaking errors (ignore Three.js warnings and position spam)
    const breaking = errors.filter(
      (e) =>
        !e.includes("module") &&
        !e.includes("IDENT") &&
        !e.includes("Object3D") &&
        !e.includes("position") &&
        !e.includes("THREE")
    );
    if (breaking.length > 0) console.log("Breaking errors:", breaking);
    expect(breaking).toHaveLength(0);
  });
});
