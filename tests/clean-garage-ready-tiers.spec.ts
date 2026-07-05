/**
 * Verifies the tier system in code/ready/clean-the-garage.html.
 * Loads the file directly via file:// to bypass any stale /code/ mount.
 */
import { test, expect } from '@playwright/test';
import * as path from 'path';

const FILE_URL = 'file://' + path.resolve('/home/peter/mullm/code/ready/clean-the-garage.html');

test.use({ ignoreHTTPSErrors: true });

test('tier system: getGarageTier boundaries + applyTier mutates scene', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(FILE_URL, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);

  const probe = await page.evaluate(() => {
    const G = (window as any).GAME;
    const sc = (window as any).scene;
    if (!G || !G.getGarageTier) return { error: 'GAME.getGarageTier missing' };
    const samples: any[] = [];
    for (const idx of [0, 25, 50, 75, 99]) {
      G.loadLevel(idx);
      samples.push({
        levelNum: idx + 1,
        tier: G.currentGarageTier(),
        bg: sc.background.getHex(),
        fogColor: sc.fog.color.getHex()
      });
    }
    return {
      l1: G.getGarageTier(1), l25: G.getGarageTier(25),
      l26: G.getGarageTier(26), l50: G.getGarageTier(50),
      l51: G.getGarageTier(51), l75: G.getGarageTier(75),
      l76: G.getGarageTier(76), l100: G.getGarageTier(100),
      tierNames: G.TIER_NAMES,
      samples
    };
  });

  expect((probe as any).error).toBeUndefined();
  expect(probe.l1).toBe(1);
  expect(probe.l25).toBe(1);
  expect(probe.l26).toBe(2);
  expect(probe.l50).toBe(2);
  expect(probe.l51).toBe(3);
  expect(probe.l75).toBe(3);
  expect(probe.l76).toBe(4);
  expect(probe.l100).toBe(4);
  expect(probe.tierNames[4]).toMatch(/leno|mansion/i);

  // Each tier produces a distinct background color
  const bgs = new Set(probe.samples.map((s: any) => s.bg));
  expect(bgs.size).toBeGreaterThanOrEqual(4);

  // Verify L26, L51, L76 hit tiers 2, 3, 4
  const byNum = Object.fromEntries(probe.samples.map((s: any) => [s.levelNum, s.tier]));
  expect(byNum[26]).toBe(2);
  expect(byNum[51]).toBe(3);
  expect(byNum[76]).toBe(4);
  expect(byNum[100]).toBe(4);

  expect(errors.filter(e => !e.includes('favicon'))).toHaveLength(0);
});
