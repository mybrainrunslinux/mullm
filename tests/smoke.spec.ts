/**
 * Smoke test — validates server is actually reachable IN THE BROWSER.
 * Run after every restart: bash scripts/s32-validate-browser.sh
 */
import { test, expect } from '@playwright/test';

const BASE = process.env.MULLM_URL || 'https://10.0.0.165:8100';

test('bench page loads in browser', async ({ page }) => {
  await page.goto(`${BASE}/bench`, { waitUntil: 'domcontentloaded' });
  // Tab bar is always visible; confirms bench page rendered correctly
  await expect(page.getByRole('tab', { name: 'Coding' })).toBeVisible({ timeout: 10000 });
});

test('chat page loads in browser', async ({ page }) => {
  await page.goto(`${BASE}/chat`, { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#chat-input, textarea, .chat-input')).toBeVisible({ timeout: 10000 });
});

test('health endpoint returns ok', async ({ request }) => {
  const resp = await request.get(`${BASE}/health`);
  expect(resp.ok()).toBeTruthy();
  const body = await resp.json();
  expect(body.status).toBe('ok');
});
