/**
 * Bollywood Hero — Playwright validation spec
 * TDD-first: written before the game is built.
 */

import { test, expect } from '@playwright/test';

const BASE = process.env.MULLM_URL || 'https://127.0.0.1:8100';
const GAME = `${BASE}/code/bollywood-hero.html`;

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
  const canvas = page.locator('canvas').first();
  await expect(canvas).toBeVisible();
  const box = await canvas.boundingBox();
  expect(box!.width).toBeGreaterThan(100);
});

test('title contains Bollywood or Hero', async ({ page }) => {
  await page.goto(GAME, { waitUntil: 'domcontentloaded' });
  const title = await page.title();
  expect(title.toLowerCase()).toMatch(/bollywood|hero/i);
});

test('has level or stage indicator', async ({ page }) => {
  await page.goto(GAME, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);
  const body = await page.content();
  expect(body.toLowerCase()).toMatch(/level|stage|scene|act/i);
});

test('has help button', async ({ page }) => {
  await page.goto(GAME, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);
  const btn = page.locator('button, [role="button"]').filter({ hasText: /\?|help|how/i }).first();
  const hasBtn = await btn.count() > 0;
  expect(hasBtn).toBe(true);
});

test('mobile viewport: no horizontal scroll, canvas visible', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(GAME, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(scrollWidth).toBeLessThanOrEqual(395);
  const canvas = page.locator('canvas').first();
  await expect(canvas).toBeVisible();
});

test('click does not crash game', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(GAME, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);
  const canvas = page.locator('canvas').first();
  const box = await canvas.boundingBox();
  if (box) {
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    await page.waitForTimeout(500);
  }
  expect(errors.filter(e => !e.includes('favicon'))).toHaveLength(0);
});
