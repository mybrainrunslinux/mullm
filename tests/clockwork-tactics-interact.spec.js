// Verify selection and command issue work end-to-end.
const { test, expect } = require('@playwright/test');
const path = require('path');
const { pathToFileURL } = require('url');

const FILE = path.resolve(__dirname, '..', 'code', 'ready', 'clockwork-arena-tactics.html');

test('clockwork-arena-tactics: select player worker and command move', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (err) => errors.push('pageerror: ' + String(err)));
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push('console.error: ' + msg.text());
  });

  await page.goto(pathToFileURL(FILE).toString());
  await page.locator('.mission-btn[data-mission="0"]').click();

  // Wait past intro dialogs
  await page.waitForTimeout(11000);

  // Helper: convert worldXY to screenXY based on Part C transform
  const wToS = await page.evaluate(() => {
    const c = document.getElementById('canvas');
    return { cw: c.width, ch: c.height };
  });

  // World (3,16) is a player worker; world coordinate transform:
  // sx = (gx-gy)*32 + 0 + cw/2 ; sy = (gx+gy)*16 + (-320) + ch/2
  const sx = (3 - 16) * 32 + wToS.cw / 2;
  const sy = (3 + 16) * 16 - 320 + wToS.ch / 2;

  // Click (select) the worker
  await page.mouse.click(sx, sy);
  await page.waitForTimeout(200);

  const selCount = await page.evaluate(() => {
    if (!window.GAME) return -1;
    return window.GAME.units.filter(u => u.selected).length;
  });
  console.log('Selected after click:', selCount);
  expect(selCount).toBeGreaterThanOrEqual(1);

  // Right-click to command move to world (8,15)
  const dx = (8 - 15) * 32 + wToS.cw / 2;
  const dy = (8 + 15) * 16 - 320 + wToS.ch / 2;
  await page.mouse.click(dx, dy, { button: 'right' });
  await page.waitForTimeout(200);

  const cmdState = await page.evaluate(() => {
    const sel = window.GAME.units.filter(u => u.selected);
    return sel.map(u => ({
      type: u.type,
      hasCmd: (u.commands || []).length > 0,
      hasPathOrTarget: (u.path && u.path.length > 0) || !!u.target,
    }));
  });
  console.log('After right-click:', JSON.stringify(cmdState));
  expect(cmdState.length).toBeGreaterThanOrEqual(1);
  // Either the command sits in queue or pathfinder already converted it to a path/target
  expect(cmdState.some(c => c.hasCmd || c.hasPathOrTarget)).toBe(true);

  expect(errors, 'no JS errors').toEqual([]);
});
