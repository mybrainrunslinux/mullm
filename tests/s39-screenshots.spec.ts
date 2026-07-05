import { test } from '@playwright/test';
const URL = process.env.MULLM_URL || 'https://127.0.0.1:8100';
test.use({ ignoreHTTPSErrors: true });

const games = ['help-me-move','jacks','hay-and-harness','clockwork-arena-tactics'];
for (const g of games) {
  test(`screenshot ${g}`, async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(`${URL}/code/ready/${g}.html`);
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `/tmp/s39gen/screenshot-${g}.png`, fullPage: false });
    console.log(`saved /tmp/s39gen/screenshot-${g}.png`);
  });
}
