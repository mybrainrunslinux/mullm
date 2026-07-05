// Dressage Royale smoke test
// Loads the file, clicks Start, plays for 3 seconds, checks no JS errors.

const { test, expect } = require('@playwright/test');
const path = require('path');
const url = 'file://' + path.resolve(__dirname, '..', 'code', 'ready', 'dressage-royale.html');

test('dressage-royale loads, starts, and plays 3s without errors', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });

  await page.goto(url);

  // Start screen should be active
  await expect(page.locator('#startScreen')).toHaveClass(/active/);
  const canvas = page.locator('#gameCanvas');
  await expect(canvas).toBeVisible();

  // Click Start
  await page.locator('.start-btn').first().click();

  // Wait through countdown + play time (countdown is ~3s)
  await page.waitForTimeout(6500);

  // Start screen should no longer be active
  await expect(page.locator('#startScreen')).not.toHaveClass(/active/);

  // No JS errors captured
  expect(errors, `Errors:\n${errors.join('\n')}`).toEqual([]);
});
