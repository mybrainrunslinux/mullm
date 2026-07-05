// Playwright smoke test for clockwork-arena-classic.html
// Loads the file, clicks Start/New Game, plays for 3 seconds, checks no JS errors.
const { test, expect } = require('@playwright/test');
const path = require('path');
const { pathToFileURL } = require('url');

const FILE = path.resolve(__dirname, '..', 'code', 'ready', 'clockwork-arena-classic.html');

test('clockwork-arena-classic boots and runs for 3s without JS errors', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (err) => errors.push(String(err)));
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push('console.error: ' + msg.text());
  });

  await page.goto(pathToFileURL(FILE).toString());

  // Title overlay should be visible; press Start.
  const startSelectors = ['#btn-start', 'button:has-text("Start")', 'button:has-text("Start Game")', 'button:has-text("New Game")'];
  let clicked = false;
  for (const sel of startSelectors) {
    const el = page.locator(sel).first();
    if (await el.count() > 0) {
      try { await el.click({ timeout: 2000 }); clicked = true; break; } catch (_) {}
    }
  }
  if (!clicked) {
    // Fall back to pressing Enter (some games auto-start).
    await page.keyboard.press('Enter').catch(() => {});
  }

  // Let the game run for ~3 seconds.
  await page.waitForTimeout(3200);

  // Canvas should be in the DOM and have non-zero size.
  const canvasBox = await page.locator('#game').boundingBox();
  expect(canvasBox).not.toBeNull();
  expect(canvasBox.width).toBeGreaterThan(100);
  expect(canvasBox.height).toBeGreaterThan(100);

  if (errors.length) {
    console.log('JS errors captured:\n' + errors.join('\n'));
  }
  expect(errors, 'page should have zero JS errors').toEqual([]);
});
