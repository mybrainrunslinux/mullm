import { test, expect } from '@playwright/test';

const URL = process.env.MULLM_URL || 'https://127.0.0.1:8100';
test.use({ ignoreHTTPSErrors: true });

test('classic culinary-divinity has new step types (fold-gentle, knead, season)', async ({ page }) => {
  await page.goto(`${URL}/code/ready/culinary-divinity.html`);
  await page.waitForFunction(
    () => document.getElementById('loadingScreen')?.classList.contains('hidden'),
    null, { timeout: 10000 });
  // Pull the DISHES array out of window via injected probe — easier: search HTML source for the strings
  const html = await page.content();
  expect(html).toContain('fold-gentle');
  expect(html).toContain("type: 'knead'");
  expect(html).toContain("type: 'season'");
  // makeBowl now uses LatheGeometry (full-bowl, not half)
  expect(html).toContain('LatheGeometry');
});

test('classic culinary-divinity bowl renders and screenshot is non-empty', async ({ page }) => {
  await page.goto(`${URL}/code/ready/culinary-divinity.html`);
  await page.waitForFunction(
    () => document.getElementById('loadingScreen')?.classList.contains('hidden'),
    null, { timeout: 10000 });
  // Wait for first frame
  await page.waitForTimeout(500);
  const buf = await page.screenshot({ fullPage: false });
  expect(buf.length).toBeGreaterThan(2000);
});
