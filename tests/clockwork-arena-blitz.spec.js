// Playwright smoke test for clockwork-arena-blitz.html
const { test, expect } = require('@playwright/test');
const path = require('path');
const { pathToFileURL } = require('url');

const FILE = path.resolve(__dirname, '..', 'code', 'ready', 'clockwork-arena-blitz.html');

test('clockwork-arena-blitz boots and runs for 3s without JS errors', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (err) => errors.push(String(err)));
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push('console.error: ' + msg.text());
  });

  await page.goto(pathToFileURL(FILE).toString());

  // Blitz may have a mode-select then char-select. Click through best-effort.
  const startChain = [
    ['#btn-vsAI', 'button:has-text("1P"), button:has-text("vs AI"), button:has-text("vsAI")'],
    ['#btn-start', 'button:has-text("Start")'],
  ];
  for (const group of startChain) {
    for (const sel of group) {
      const el = page.locator(sel).first();
      if (await el.count() > 0) {
        try { await el.click({ timeout: 1000 }); break; } catch (_) {}
      }
    }
  }
  // Select default characters via Space/Enter in case char select is up.
  await page.keyboard.press('Space').catch(() => {});
  await page.keyboard.press('Enter').catch(() => {});

  await page.waitForTimeout(3200);

  const canvasBox = await page.locator('#game').boundingBox();
  expect(canvasBox).not.toBeNull();
  expect(canvasBox.width).toBeGreaterThan(100);
  expect(canvasBox.height).toBeGreaterThan(100);

  if (errors.length) console.log('JS errors captured:\n' + errors.join('\n'));
  expect(errors, 'page should have zero JS errors').toEqual([]);
});
