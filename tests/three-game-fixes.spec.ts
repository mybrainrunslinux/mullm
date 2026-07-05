/**
 * Smoke tests for three repaired games:
 *   - nunchuk-chain.html
 *   - throwing-stars.html
 *   - zipper-merge.html
 *
 * Each must:
 *   - Load without uncaught JS errors
 *   - Show a visible canvas with a non-trivial bounding box
 *   - Survive a click in the canvas centre without crashing
 *   - NOT contain leaked LLM commentary (triple backticks, etc.)
 */

import { test, expect } from '@playwright/test';

const BASE = process.env.MULLM_URL || 'https://127.0.0.1:8100';
const GAMES = [
  'nunchuk-chain',
  'throwing-stars',
  'zipper-merge',
];

test.use({ ignoreHTTPSErrors: true });

for (const slug of GAMES) {
  const url = `${BASE}/code/ready/${slug}.html`;

  test(`${slug}: game loads without JS errors`, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1500);
    expect(errors.filter(e => !e.includes('favicon'))).toEqual([]);
  });

  test(`${slug}: canvas visible with reasonable size`, async ({ page }) => {
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(800);
    const canvas = page.locator('canvas').first();
    await expect(canvas).toBeVisible();
    const box = await canvas.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeGreaterThan(200);
    expect(box!.height).toBeGreaterThan(200);
  });

  test(`${slug}: clicking canvas does not crash`, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(800);
    const canvas = page.locator('canvas').first();
    const box = await canvas.boundingBox();
    if (box) {
      await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
      await page.waitForTimeout(300);
    }
    expect(errors.filter(e => !e.includes('favicon'))).toEqual([]);
  });

  test(`${slug}: page contains no leaked LLM markdown fences`, async ({ page }) => {
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    const text = await page.evaluate(() => document.body.innerText);
    expect(text).not.toContain('```');
    expect(text.toLowerCase()).not.toContain('here is what it includes');
    expect(text.toLowerCase()).not.toContain('this is a complete, self-contained');
  });
}
