// Playwright smoke test for clockwork-arena-tactics.html
const { test, expect } = require('@playwright/test');
const path = require('path');
const { pathToFileURL } = require('url');

const FILE = path.resolve(__dirname, '..', 'code', 'ready', 'clockwork-arena-tactics.html');

test('clockwork-arena-tactics boots and runs for 3s without JS errors', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (err) => errors.push(String(err)));
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push('console.error: ' + msg.text());
  });

  await page.goto(pathToFileURL(FILE).toString());

  const startSelectors = ['#btn-start', 'button:has-text("Start")', 'button:has-text("New Game")', 'button:has-text("Start Match")'];
  let clicked = false;
  for (const sel of startSelectors) {
    const el = page.locator(sel).first();
    if (await el.count() > 0) {
      try { await el.click({ timeout: 2000 }); clicked = true; break; } catch (_) {}
    }
  }
  if (!clicked) await page.keyboard.press('Enter').catch(() => {});

  await page.waitForTimeout(3200);

  const canvasBox = await page.locator('#game').boundingBox();
  expect(canvasBox).not.toBeNull();
  expect(canvasBox.width).toBeGreaterThan(100);
  expect(canvasBox.height).toBeGreaterThan(100);

  if (errors.length) console.log('JS errors captured:\n' + errors.join('\n'));
  expect(errors, 'page should have zero JS errors').toEqual([]);
});
