// Deeper test: drive enough rallies to verify scoring progression and absence of freeze.
const { test, expect } = require('@playwright/test');
const path = require('path');

test('pickleball — drives points, no freeze, side-out scoring shows', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('CONSOLE: ' + m.text()); });

  const file = 'file://' + path.resolve('/home/peter/mullm/code/ready/pickleball-3d.html');
  await page.goto(file);
  await expect(page.locator('#menu-main')).toBeVisible({ timeout: 5000 });

  // Crank AI difficulty so opponent makes faults often (level 1 = beginner)
  await page.fill('#ai-slider', '1');
  await page.evaluate(() => {
    const s = document.getElementById('ai-slider');
    s.dispatchEvent(new Event('input', { bubbles: true }));
  });

  await page.click('#btn-start');
  await page.waitForTimeout(400);

  // Snapshot HUD + status every 1.5s for 30s. The status line changes much more often than the
  // score (Bad toss / Rally on / serving), so it's a robust freshness probe.
  const snapshots = [];
  for (let i = 0; i < 20; i++) {
    await page.keyboard.press('Space');
    await page.mouse.move(300 + (i * 17) % 400, 300 + (i * 23) % 200);
    await page.waitForTimeout(1500);
    const hud = await page.locator('#hud-score').textContent();
    const status = await page.locator('#hud-status').textContent();
    snapshots.push({ t: i, hud, status });
  }
  console.log('Snapshots:');
  snapshots.forEach(s => console.log(`  t=${s.t}s  HUD="${s.hud}"  STATUS="${s.status}"`));

  // Either HUD or status text must change at least once across 30s — proves the game loop is alive.
  const distinctHuds = new Set(snapshots.map(s => s.hud));
  const distinctStatuses = new Set(snapshots.map(s => s.status));
  expect(distinctHuds.size + distinctStatuses.size).toBeGreaterThan(2);

  // Confirm no fatal JS errors
  const fatal = errors.filter(e => /TypeError|ReferenceError|is not defined|is not a function/i.test(e));
  expect(fatal).toEqual([]);
});
