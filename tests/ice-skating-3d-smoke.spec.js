// Playwright smoke test for ice-skating-3d
const { test, expect } = require('@playwright/test');
const path = require('path');

test.use({ ignoreHTTPSErrors: true });

const URL = 'file://' + path.resolve('/home/peter/mullm/code/ready/ice-skating-3d.html');

test('ice-skating-3d boots, validator passes, mechanics work', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  await page.goto(URL, { waitUntil: 'domcontentloaded' });
  // wait for boot validator to flip to pass
  await page.waitForFunction(() => {
    const v = document.getElementById('validator');
    return v && (v.classList.contains('pass') || v.classList.contains('fail'));
  }, { timeout: 15000 });

  const valStatus = await page.evaluate(() => {
    const v = document.getElementById('validator');
    return { cls: v.className, text: v.textContent };
  });
  console.log('validator:', JSON.stringify(valStatus));
  expect(valStatus.cls).toContain('pass');

  // Splash should be visible
  const splashVis = await page.locator('#splash-overlay').isVisible();
  expect(splashVis).toBe(true);

  // Click Time Trial start
  await page.locator('#btn-time').click();
  await page.waitForTimeout(300);

  // Splash hidden, HUD visible
  const splashAfter = await page.locator('#splash-overlay').isVisible();
  expect(splashAfter).toBe(false);

  const hudScore = await page.locator('#score').isVisible();
  expect(hudScore).toBe(true);

  // Run self-test exposed on window
  const results = await page.evaluate(() => window.__iceskating_test());
  console.log('self-test results:');
  results.forEach(r => console.log(' -', r.ok?'PASS':'FAIL', r.name, r.info));
  const fails = results.filter(r => !r.ok);
  expect(fails.length).toBe(0);

  // No console errors
  if (errors.length){
    console.log('ERRORS:');
    errors.forEach(e => console.log(' -', e));
  }
  expect(errors.length).toBe(0);
});
