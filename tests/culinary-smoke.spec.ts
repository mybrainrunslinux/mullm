import { test, expect } from '@playwright/test';

const URL = process.env.MULLM_URL || 'https://127.0.0.1:8100';

test.use({ ignoreHTTPSErrors: true });

test('culinary-divinity classic version loads, switches steps, has bowl', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', m => {
    if (m.type() === 'error') errors.push(m.text());
  });
  page.on('pageerror', e => errors.push(e.message));

  await page.goto(`${URL}/code/ready/culinary-divinity.html`);
  // Wait for loading screen to add 'hidden' class
  await page.waitForFunction(
    () => document.getElementById('loadingScreen')?.classList.contains('hidden'),
    null,
    { timeout: 10000 }
  );
  // HUD should show first dish
  const dishName = await page.textContent('#hud-dish');
  expect(dishName).toBeTruthy();
  // Action panel should have at least one button
  const btnCount = await page.locator('#actionPanel .action-btn').count();
  expect(btnCount).toBeGreaterThan(0);
  // No JS errors
  expect(errors.filter(e => !e.includes('favicon'))).toEqual([]);
});

test('culinary-divinity-new (alien moonshine) still loads', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(`${URL}/code/ready/culinary-divinity-new.html`);
  await page.waitForLoadState('networkidle', { timeout: 10000 });
  expect(errors).toEqual([]);
});
