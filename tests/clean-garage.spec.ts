/**
 * Clean The Garage — Playwright validation spec
 * TDD-first: written before the game is built.
 *
 * Must pass before the game is considered shippable.
 */

import { test, expect } from '@playwright/test';

const BASE = process.env.MULLM_URL || 'https://127.0.0.1:8100';
const GAME = `${BASE}/code/clean-the-garage.html`;

test.use({ ignoreHTTPSErrors: true });

test('game loads without JS errors', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(GAME, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);
  expect(errors.filter(e => !e.includes('favicon'))).toHaveLength(0);
});

test('has canvas or 3D viewport', async ({ page }) => {
  await page.goto(GAME, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);
  const canvas = page.locator('canvas');
  await expect(canvas.first()).toBeVisible();
  const box = await canvas.first().boundingBox();
  expect(box!.width).toBeGreaterThan(100);
  expect(box!.height).toBeGreaterThan(100);
});

test('shows level indicator', async ({ page }) => {
  await page.goto(GAME, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);
  // Level 1 should be visible somewhere in the UI
  const body = await page.content();
  expect(body.toLowerCase()).toMatch(/level\s*1|level:\s*1|stage\s*1/i);
});

test('has a help or instructions button', async ({ page }) => {
  await page.goto(GAME, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);
  const helpBtn = page.locator('button, [role="button"]').filter({ hasText: /help|\?|how|info/i }).first();
  // OR a ? button somewhere
  const qBtn = page.locator('button:has-text("?"), [aria-label*="help" i], [title*="help" i]').first();
  const hasHelp = await helpBtn.count() > 0 || await qBtn.count() > 0;
  expect(hasHelp).toBe(true);
});

test('mobile viewport: canvas visible and no horizontal scroll', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(GAME, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(scrollWidth).toBeLessThanOrEqual(395);
  const canvas = page.locator('canvas').first();
  await expect(canvas).toBeVisible();
});

test('has game title mentioning garage or clean', async ({ page }) => {
  await page.goto(GAME, { waitUntil: 'domcontentloaded' });
  const title = await page.title();
  expect(title.toLowerCase()).toMatch(/garage|clean/i);
});

test('clicking/tapping does not crash the game', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(GAME, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);
  // Click center of canvas
  const canvas = page.locator('canvas').first();
  const box = await canvas.boundingBox();
  if (box) {
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    await page.waitForTimeout(500);
  }
  expect(errors.filter(e => !e.includes('favicon'))).toHaveLength(0);
});
