const { test, expect } = require("@playwright/test");
const BASE = process.env.MULLM_URL || "https://127.0.0.1:8100";

test("bench: extra panels hidden by default", async ({ page }) => {
  await page.goto(`${BASE}/bench`, { ignoreHTTPSErrors: true });
  await page.waitForLoadState("networkidle");

  // These panels must be hidden on load
  for (const id of ["panel-multiple", "panel-mmlu", "panel-gsm8k", "panel-radar"]) {
    const display = await page.locator(`#${id}`).evaluate((el) => getComputedStyle(el).display);
    expect(display, `${id} must be hidden on load`).toBe("none");
  }
});

test("bench: MultiPL-E panel shows when tab clicked", async ({ page }) => {
  await page.goto(`${BASE}/bench`, { ignoreHTTPSErrors: true });
  await page.waitForLoadState("networkidle");
  await page.click("#tab-multiple");
  await page.waitForTimeout(500);

  const display = await page.locator("#panel-multiple").evaluate((el) => getComputedStyle(el).display);
  expect(display, "panel-multiple should be visible after tab click").not.toBe("none");
});

test("bench: MultiPL-E rows visible (not opacity:0)", async ({ page }) => {
  await page.goto(`${BASE}/bench`, { ignoreHTTPSErrors: true });
  await page.waitForLoadState("networkidle");
  await page.click("#tab-multiple");
  await page.waitForTimeout(1000);

  const rows = await page.locator("#mpl-body tr.mpl-row").count();
  console.log("MPL rows:", rows);
  if (rows > 0) {
    const opacity = await page
      .locator("#mpl-body tr.mpl-row")
      .first()
      .evaluate((el) => getComputedStyle(el).opacity);
    expect(parseFloat(opacity), "rows must be visible").toBeGreaterThan(0.5);
  }
});
