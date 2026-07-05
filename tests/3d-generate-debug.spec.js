const { test, expect } = require("@playwright/test");
const BASE = process.env.MULLM_URL || "https://localhost:8100";

test.describe("3D Generate Debug", () => {
  test.use({ ignoreHTTPSErrors: true });

  test("clicking Generate 3D Model triggers generation", async ({ page }) => {
    const errors = [];
    page.on("pageerror", (e) => {
      errors.push(e.message);
      console.log("JS ERROR:", e.message);
    });
    page.on("console", (m) => {
      if (m.type() === "error") console.log("CONSOLE:", m.text().slice(0, 200));
    });

    await page.goto(`${BASE}/3d`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(3000);

    // Fill prompt
    await page.fill("#gen-prompt", "test sphere");
    await page.selectOption("#gen-style", "low-poly");
    await page.selectOption("#gen-source", "comfyui");
    await page.selectOption("#gen-workflow", "direct");

    // Check button exists and is clickable
    const btn = page.locator("#gen-btn");
    await expect(btn).toBeVisible();
    const btnText = await btn.textContent();
    console.log("Button text:", btnText);

    // Click it
    await btn.click();
    console.log("Clicked generate");

    // Wait and check for any response
    await page.waitForTimeout(3000);

    // Check if progress bar appeared
    const progress = page.locator("#progress-wrap");
    const progressVisible = await progress.evaluate((el) => el.classList.contains("visible")).catch(() => false);
    console.log("Progress visible:", progressVisible);

    // Check if generating card appeared
    const genCards = page.locator(".asset-card.generating");
    const genCount = await genCards.count();
    console.log("Generating cards:", genCount);

    // Check for toast messages
    const toast = page.locator("#toast");
    const toastText = await toast.textContent().catch(() => "no toast");
    console.log("Toast:", toastText);

    // Check button state changed
    const btnLabel = await page.locator("#gen-btn-label").textContent();
    console.log("Button label after click:", btnLabel);

    // Log errors
    console.log("JS errors:", errors.length);
    errors.forEach((e) => console.log("  ", e.slice(0, 150)));
  });
});
