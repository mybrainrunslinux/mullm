import { test, expect } from '@playwright/test';

const URL = process.env.MULLM_URL || 'https://127.0.0.1:8100';
test.use({ ignoreHTTPSErrors: true });

test('Sourdough dish (5) loads and exposes fold-gentle, knead, season step types', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });

  await page.goto(`${URL}/code/ready/culinary-divinity.html`);
  await page.waitForFunction(
    () => (window as any).__culinary && document.getElementById('loadingScreen')?.classList.contains('hidden'),
    null, { timeout: 10000 });

  // Verify the new dishes exist
  const dishNames = await page.evaluate(() => (window as any).__culinary.DISHES.map((d: any) => d.name));
  expect(dishNames).toContain('Sourdough Boule');
  expect(dishNames).toContain('Heirloom Tomato Galette');

  // Verify Sourdough has all three new step types
  const sourSteps = await page.evaluate(() =>
    (window as any).__culinary.DISHES.find((d: any) => d.name === 'Sourdough Boule').steps.map((s: any) => s.type)
  );
  expect(sourSteps).toContain('fold-gentle');
  expect(sourSteps).toContain('knead');
  expect(sourSteps).toContain('season');

  // Load Sourdough dish and verify it sets up cleanly
  await page.evaluate(() => (window as any).__culinary.loadDish(5));
  await page.waitForTimeout(300);
  const dishLabel = await page.textContent('#hud-dish');
  expect(dishLabel).toContain('Sourdough');

  // Walk forward through each step by mutating state.step + calling setup via loadDish trick:
  // Instead — we just ensure the first step (whisk) shows action button.
  const btnCount = await page.locator('#actionPanel .action-btn').count();
  expect(btnCount).toBeGreaterThan(0);

  // No errors during all that
  expect(errors.filter(e => !e.includes('favicon'))).toEqual([]);
});
