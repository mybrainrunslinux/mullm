import { test, expect } from '@playwright/test';
import * as path from 'path';
import * as fs from 'fs';

// Resolve the game locally so specs work on any checkout; skip when the
// game HTML is not shipped in this tree.
function gameUrl(name: string): string | null {
  const p = path.resolve(__dirname, '..', 'code', 'ready', name);
  return fs.existsSync(p) ? 'file://' + p : null;
}


test('arena full flow — start match, fight, no errors', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(msg.text());
  });
  page.on('pageerror', (err) => errors.push('PAGEERROR: ' + err.message + '\n' + (err.stack||'').split('\n').slice(0,3).join(' | ')));

  const __url = gameUrl('clockwork-arena-blitz.html');
  test.skip(!__url, 'clockwork-arena-blitz.html not shipped in this tree');
  await page.goto(__url!);
  await page.waitForTimeout(800);

  const titleInfo = await page.evaluate(() => {
    const t = document.getElementById('title-overlay');
    if (!t) return null;
    const rect = t.getBoundingClientRect();
    const cs = window.getComputedStyle(t);
    return {
      classes: t.className,
      display: cs.display,
      visibility: cs.visibility,
      opacity: cs.opacity,
      zIndex: cs.zIndex,
      position: cs.position,
      rect: { x: rect.x, y: rect.y, w: rect.width, h: rect.height },
    };
  });
  console.log('Title info:', JSON.stringify(titleInfo));

  await page.screenshot({ path: '/tmp/arena-start-screen.png' });

  // Click 1P, select character
  await page.click('#btn-1p');
  await page.waitForTimeout(300);
  await page.locator('[data-character="ticker"]').click();
  await page.waitForTimeout(800);

  // Verify the match started — check title gone and canvas drawing
  const titleHidden = !(await page.locator('#title-overlay').isVisible());
  const selectHidden = !(await page.locator('#select-overlay').isVisible());
  console.log('Title hidden:', titleHidden, 'Select hidden:', selectHidden);

  // Wait some time for game loop to run
  await page.waitForTimeout(2500);

  const stateProbe = await page.evaluate(() => {
    const cwa = (window as any).CWA3;
    if (!cwa) return null;
    return {
      mode: cwa.state.mode,
      phase: cwa.state.phase,
      timer: cwa.state.timer,
      p1Hp: cwa.state.p1?.hp,
      p2Hp: cwa.state.p2?.hp,
    };
  });
  console.log('State after 2.5s:', JSON.stringify(stateProbe));

  // Press attack keys to register hits
  await page.keyboard.down('d'); await page.waitForTimeout(800); await page.keyboard.up('d');
  await page.keyboard.press('z');
  await page.waitForTimeout(500);

  // Check HUD timer is updating
  const timerText = await page.locator('#round-timer').textContent();
  console.log('Timer text:', timerText);

  await page.screenshot({ path: '/tmp/arena-final.png' });
  console.log('Errors:', errors.join('\n'));
  expect(errors.length).toBe(0);
});
