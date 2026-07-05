// Verify the rally timeout / watchdog actually progresses scoring after a stuck rally.
const { test, expect } = require('@playwright/test');
const path = require('path');

test('pickleball — rally timeout + watchdog progress score over 40s', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('CONSOLE: ' + m.text()); });

  const file = 'file://' + path.resolve('/home/peter/mullm/code/ready/pickleball-3d.html');
  await page.goto(file);
  await expect(page.locator('#menu-main')).toBeVisible({ timeout: 5000 });

  await page.click('#btn-start');
  await page.waitForTimeout(400);

  // Drive serves but do NOT hit the ball — let timers progress
  const huds = [];
  for (let i = 0; i < 16; i++) {
    await page.keyboard.press('Space');
    await page.waitForTimeout(2500);
    const hud = await page.locator('#hud-score').textContent();
    huds.push(hud);
  }
  console.log('HUD timeline:');
  huds.forEach((h, i) => console.log(`  +${i*2.5}s  ${h}`));

  // We expect at least one score increase or server# change across 40 seconds
  const distinct = new Set(huds);
  expect(distinct.size).toBeGreaterThan(1);

  const fatal = errors.filter(e => /TypeError|ReferenceError|is not defined|is not a function/i.test(e));
  expect(fatal).toEqual([]);
});
