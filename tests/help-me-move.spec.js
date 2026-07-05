// Smoke test: help-me-move.html loads, Three.js scene renders, and basic
// input (keyboard move + rotate) changes AP counter.
const { test, expect } = require('@playwright/test');
const path = require('path');
const fs = require('fs');

const PAGE = 'file://' + path.resolve(__dirname, '..', 'code', 'ready', 'help-me-move.html');

test('help-me-move: boots, renders, accepts input, solves level 1', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => {
    if (m.type() === 'error') errors.push('console: ' + m.text());
  });

  await page.goto(PAGE);
  // wait for Three.js and boot
  await page.waitForFunction(() => !!(window.__HMM_EARLY || window.__HMM), null, { timeout: 6000 });

  // Confirm level 1 loaded
  await expect(page.locator('#level-name')).toContainText('Level 1');
  const initialAP = await page.locator('#ap-num').innerText();
  expect(parseInt(initialAP, 10)).toBeGreaterThan(0);

  // Slide right five times (W maps to -z, D maps to +x) — plank at (1,0,2) to (6,0,2)
  await page.locator('canvas').first().click(); // focus the document
  for (let i = 0; i < 5; i++) {
    await page.keyboard.press('ArrowRight');
    await page.waitForTimeout(320);
  }

  // Expect win overlay to be visible
  await expect(page.locator('#overlay-win')).toBeVisible({ timeout: 4000 });

  expect(errors, 'no page errors').toEqual([]);
});

test('help-me-move: all levels solvable by BFS', async ({ page }) => {
  await page.goto(PAGE);
  await page.waitForFunction(() => !!(window.__HMM_EARLY || window.__HMM));
  const results = await page.evaluate(() => {
    const hmm = window.__HMM_EARLY || window.__HMM;
    return hmm.LEVELS.map((L, i) => {
      const par = hmm.solvePar(L);
      return { i: i + 1, name: L.name, par, budget: L.ap };
    });
  });
  const unsolvable = results.filter(r => r.par == null);
  console.log('Level solver results:', results);
  expect(unsolvable, 'every level must be solvable').toEqual([]);
  for (const r of results) {
    expect(r.budget, `level ${r.i} budget >= par`).toBeGreaterThanOrEqual(r.par);
  }
});

test('help-me-move: moving spends AP and can be undone', async ({ page }) => {
  await page.goto(PAGE);
  await page.waitForFunction(() => !!(window.__HMM_EARLY || window.__HMM));
  const apBefore = parseInt(await page.locator('#ap-num').innerText(), 10);
  // On level 1 (plank in an open hallway) we know ArrowRight slides legally.
  await page.keyboard.press('ArrowRight');
  await page.waitForTimeout(320);
  const apAfter = parseInt(await page.locator('#ap-num').innerText(), 10);
  expect(apAfter).toBe(apBefore - 1);
  await page.keyboard.press('u');
  await page.waitForTimeout(250);
  const apUndo = parseInt(await page.locator('#ap-num').innerText(), 10);
  expect(apUndo).toBe(apBefore);
});
