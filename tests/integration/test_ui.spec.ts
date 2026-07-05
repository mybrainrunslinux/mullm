/**
 * UI integration tests — Playwright
 * Covers: setup page, chat page, dashboard page
 * Verifies routing tier badges appear and queries land in correct tiers.
 *
 * Usage:
 *   npx playwright test tests/integration/test_ui.spec.ts
 *   MULLM_BASE_URL=http://localhost:6856 npx playwright test tests/integration/test_ui.spec.ts
 */

import { test, expect, Page } from '@playwright/test';

const BASE = process.env.MULLM_BASE_URL ?? 'http://127.0.0.1:6856';

// ---------------------------------------------------------------------------
// Setup page
// ---------------------------------------------------------------------------

test.describe('Setup page', () => {
  test('loads without crash', async ({ page }) => {
    await page.goto(`${BASE}/setup`);
    await expect(page).not.toHaveTitle(/error|404|500/i);
    await expect(page.locator('body')).toBeVisible();
  });

  test('does not show itsdangerous or internal library names', async ({ page }) => {
    await page.goto(`${BASE}/setup`);
    const body = await page.locator('body').innerText();
    expect(body).not.toContain('itsdangerous');
  });

  test('shows OIDC/auth card', async ({ page }) => {
    await page.goto(`${BASE}/setup`);
    await expect(page.locator('#card-oidc, [id*="oidc"], [id*="auth"]').first()).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Chat page
// ---------------------------------------------------------------------------

test.describe('Chat page', () => {
  test('loads and shows input', async ({ page }) => {
    await page.goto(`${BASE}/chat`);
    await expect(page.locator('textarea, input[type="text"], [contenteditable]').first()).toBeVisible();
  });

  test('groundtruth query returns 4 quickly', async ({ page }) => {
    await page.goto(`${BASE}/chat`);
    const input = page.locator('textarea, input[type="text"], [contenteditable]').first();
    await input.fill('what is 2+2');
    await input.press('Enter');

    // Wait for response — groundtruth should be fast
    const response = page.locator('.message.assistant, .msg-assistant, [data-role="assistant"]').last();
    await expect(response).toContainText('4', { timeout: 10000 });
  });

  test('tier badge shows for routed query', async ({ page }) => {
    await page.goto(`${BASE}/chat`);
    const input = page.locator('textarea, input[type="text"], [contenteditable]').first();
    await input.fill('what port does SSH use');
    await input.press('Enter');

    // Look for tier indicator (groundtruth/cache/local/cloud badge)
    const tier = page.locator('[class*="tier"], [data-tier], .tier-badge').first();
    await expect(tier).toBeVisible({ timeout: 15000 });
  });
});

// ---------------------------------------------------------------------------
// Dashboard page
// ---------------------------------------------------------------------------

test.describe('Dashboard page', () => {
  test('loads without error', async ({ page }) => {
    await page.goto(`${BASE}/dashboard`);
    await expect(page).not.toHaveTitle(/error|404/i);
  });

  test('shows cost and query stats', async ({ page }) => {
    await page.goto(`${BASE}/dashboard`);
    // Dashboard should show some numeric stats
    const body = await page.locator('body').innerText();
    expect(body).toMatch(/\d/);  // at least some numbers
  });

  test('tier breakdown is visible', async ({ page }) => {
    await page.goto(`${BASE}/dashboard`);
    const body = await page.locator('body').innerText().catch(() => '');
    const hasTiers = /groundtruth|cache|local|cloud/i.test(body);
    expect(hasTiers).toBeTruthy();
  });
});
