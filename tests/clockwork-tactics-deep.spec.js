// Deep playwright test: verifies clockwork-arena-tactics actually reaches gameplay.
const { test, expect } = require('@playwright/test');
const path = require('path');
const { pathToFileURL } = require('url');

const FILE = path.resolve(__dirname, '..', 'code', 'ready', 'clockwork-arena-tactics.html');

test('clockwork-arena-tactics reaches gameplay after mission select', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (err) => errors.push('pageerror: ' + String(err)));
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push('console.error: ' + msg.text());
  });

  await page.goto(pathToFileURL(FILE).toString());

  // Wait for DOM
  await page.waitForSelector('#title-screen');

  // Click Mission 1
  await page.locator('.mission-btn[data-mission="0"]').first().click();

  // Title should hide
  await expect(page.locator('#title-screen')).toHaveCSS('display', 'none', { timeout: 2000 });

  // Wait for intro dialogs to play out (3 dialogs * 3000ms = ~9s in MISSION 0 of Part C)
  await page.waitForTimeout(11000);

  // Verify game state populated
  const state = await page.evaluate(() => {
    const G = window.GAME;
    if (!G) return { ok: false, why: 'no GAME' };
    return {
      ok: true,
      missionSet: !!G.mission,
      unitsCount: (G.units || []).length,
      buildingsCount: (G.buildings || []).length,
      playerBase: !!(G.buildings || []).find(b => b.type === 'Base' && b.owner === 'PLAYER'),
      aiBase: !!(G.buildings || []).find(b => b.type === 'Base' && b.owner === 'AI'),
      grandClock: !!(G.buildings || []).find(b => b.type === 'GrandClock'),
      playerWorkers: (G.units || []).filter(u => u.owner === 'PLAYER' && u.type === 'Worker').length,
      gameTime: G.gameTime || 0,
      playerGears: (G.resources && G.resources.PLAYER && G.resources.PLAYER.G) || 0,
      partBErr: window.__partB_error || null,
      partCErr: window.__partC_error || null,
    };
  });

  console.log('GAME state after intro:', JSON.stringify(state, null, 2));

  expect(state.ok).toBe(true);
  expect(state.partBErr).toBeNull();
  expect(state.partCErr).toBeNull();
  expect(state.missionSet).toBe(true);
  expect(state.playerBase).toBe(true);
  expect(state.aiBase).toBe(true);
  expect(state.grandClock).toBe(true);
  expect(state.playerWorkers).toBeGreaterThanOrEqual(2);
  expect(state.gameTime).toBeGreaterThan(0); // Game loop is actually ticking

  // Verify canvas is non-blank: sample center pixel after render
  const canvasInfo = await page.evaluate(() => {
    const c = document.getElementById('canvas');
    if (!c) return null;
    const cw = c.width, ch = c.height;
    const ctx = c.getContext('2d');
    // Sample several points for any non-bg color
    const pts = [
      [cw / 2, ch / 2],
      [cw / 2 - 200, ch / 2],
      [cw / 2 + 200, ch / 2],
      [cw / 2, ch / 2 - 100],
      [cw / 2, ch / 2 + 100],
    ];
    const samples = pts.map(([x, y]) => {
      const d = ctx.getImageData(Math.floor(x), Math.floor(y), 1, 1).data;
      return [d[0], d[1], d[2]];
    });
    return { cw, ch, samples };
  });

  console.log('Canvas samples:', JSON.stringify(canvasInfo));
  expect(canvasInfo.cw).toBeGreaterThan(100);
  expect(canvasInfo.ch).toBeGreaterThan(100);

  // At least one sample should NOT be the pure-black background #1a1208 = (26,18,8).
  // Tile colors (~42,29,12 and ~58,41,22) and Grand Clock gold (255,215,0) all count as content.
  const nonBg = canvasInfo.samples.some(([r, g, b]) => {
    const isBg = (r <= 30 && g <= 22 && b <= 12);
    return !isBg;
  });
  expect(nonBg, 'canvas must show iso tiles or units, not just bg').toBe(true);

  // Now check that updateGame is actually advancing time (run another tick)
  const t1 = await page.evaluate(() => window.GAME.gameTime);
  await page.waitForTimeout(500);
  const t2 = await page.evaluate(() => window.GAME.gameTime);
  expect(t2).toBeGreaterThan(t1);

  if (errors.length) {
    console.log('JS errors captured:\n' + errors.join('\n'));
  }
  expect(errors, 'page should have zero JS errors').toEqual([]);
});
