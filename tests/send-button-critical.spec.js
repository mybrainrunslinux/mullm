// CRITICAL: Send button must ALWAYS be visible and clickable.
// This test BLOCKS every commit if the send button is broken.
// NEVER modify this test to be more lenient.
// History: send button was broken by adding overflow:hidden to .app + removing model-group display:none from 1100px media query.
const { test, expect } = require("@playwright/test");

const BASE = process.env.MULLM_URL || "https://localhost:8100";

test.describe("Send Button — ZERO TOLERANCE", () => {
  test.use({ ignoreHTTPSErrors: true });

  for (const { name, path } of [
    { name: "chat", path: "/chat" },
    { name: "goo", path: "/goo" },
    { name: "oai", path: "/oai" },
  ]) {
    test(`[${name}] send button is visible and in viewport`, async ({ page }) => {
      await page.goto(`${BASE}${path}`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(1500);

      const sendBtn = page.locator('#sendBtn');
      await expect(sendBtn).toBeVisible({ timeout: 5000 });

      // Must be in viewport — not clipped, not off-screen
      const box = await sendBtn.boundingBox();
      expect(box).not.toBeNull();

      const viewport = page.viewportSize();
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.y).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(viewport.width + 1);
      expect(box.y + box.height).toBeLessThanOrEqual(viewport.height + 1);
    });

    test(`[${name}] send button is clickable after typing`, async ({ page }) => {
      await page.goto(`${BASE}${path}`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(1500);

      const input = page.locator('#queryInput');
      await input.fill("test query for send button validation");

      const sendBtn = page.locator('#sendBtn');
      await expect(sendBtn).toBeVisible();
      await expect(sendBtn).toBeEnabled();

      // Verify it's actually clickable (not covered by another element)
      const box = await sendBtn.boundingBox();
      const centerX = box.x + box.width / 2;
      const centerY = box.y + box.height / 2;
      const el = await page.evaluateHandle(`document.elementFromPoint(${centerX}, ${centerY})`);
      const tag = await el.evaluate(e => e.closest('#sendBtn') ? 'sendBtn' : e.tagName);
      expect(tag).toBe('sendBtn');
    });
  }

  test("[chat] send button visible at 900px viewport width", async ({ page }) => {
    await page.setViewportSize({ width: 900, height: 700 });
    await page.goto(`${BASE}/chat`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1500);

    const sendBtn = page.locator('#sendBtn');
    await expect(sendBtn).toBeVisible({ timeout: 5000 });

    const box = await sendBtn.boundingBox();
    expect(box).not.toBeNull();
    expect(box.x + box.width).toBeLessThanOrEqual(901);
  });

  test("[chat] send button visible at 1100px viewport width", async ({ page }) => {
    await page.setViewportSize({ width: 1100, height: 800 });
    await page.goto(`${BASE}/chat`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1500);

    const sendBtn = page.locator('#sendBtn');
    await expect(sendBtn).toBeVisible({ timeout: 5000 });

    const box = await sendBtn.boundingBox();
    expect(box).not.toBeNull();
    expect(box.x + box.width).toBeLessThanOrEqual(1101);
  });
});
