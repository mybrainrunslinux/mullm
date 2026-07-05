// Smoke test for pickleball-3d.html — verifies no freeze and basic flow.
const { test, expect } = require('@playwright/test');
const path = require('path');

test('pickleball loads, starts match, plays without freeze', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('CONSOLE: ' + m.text()); });

  const file = 'file://' + path.resolve('/home/peter/mullm/code/ready/pickleball-3d.html');
  await page.goto(file);

  // Wait for menu
  await expect(page.locator('#menu-main')).toBeVisible({ timeout: 5000 });
  // Verify HUD shows pickleball terse score format (e.g. "0-0-2") plus team labels
  const initialHud = await page.locator('#hud-score').textContent();
  console.log('Initial HUD:', initialHud);
  expect(initialHud).toMatch(/\d+-\d+-[12]/);
  expect(initialHud).toContain('YOU & RALLY');
  expect(initialHud).toContain('TEAM B');

  // Start match
  await page.click('#btn-start');
  await page.waitForTimeout(500);

  // Menu should be hidden
  await expect(page.locator('#menu-main')).toBeHidden();

  // Press space to toss + serve a few times. We'll spam space and pointer move every 200ms for 12s.
  const start = Date.now();
  let i = 0;
  while (Date.now() - start < 12000) {
    await page.keyboard.press('Space');
    // Wiggle pointer
    await page.mouse.move(400 + (i % 100), 300 + (i % 50));
    await page.waitForTimeout(180);
    i++;
  }

  // Read HUD — should show some progress (server# or score change) and game still responsive
  const hudAfter = await page.locator('#hud-score').textContent();
  console.log('HUD after 12s:', hudAfter);
  const statusAfter = await page.locator('#hud-status').textContent();
  console.log('Status after 12s:', statusAfter);

  // Verify the page is still alive — pause toggles overlay
  await page.click('#btn-pause');
  await expect(page.locator('#menu-pause')).toBeVisible({ timeout: 2000 });
  await page.click('#btn-resume');
  await expect(page.locator('#menu-pause')).toBeHidden({ timeout: 2000 });

  // No fatal errors thrown that took down the loop
  console.log('Errors collected:', errors);
  // We tolerate non-fatal warnings, but any TypeError or ReferenceError is bad
  const fatal = errors.filter(e => /TypeError|ReferenceError|is not defined|is not a function/i.test(e));
  expect(fatal).toEqual([]);
});
