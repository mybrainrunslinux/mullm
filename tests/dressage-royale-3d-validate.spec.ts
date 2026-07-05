import { test, expect } from '@playwright/test';
import path from 'path';

test('dressage-royale-3d boots, arena+horse+judges build, test starts', async ({ page }) => {
  const errors: string[] = [];
  const consoleErrs: string[] = [];
  page.on('pageerror', e => errors.push(e.message + '\n' + (e.stack || '').split('\n').slice(0, 4).join('\n')));
  page.on('console', m => { if (m.type() === 'error') consoleErrs.push(m.text()); });

  const url = 'file://' + path.resolve('/home/peter/mullm/code/ready/dressage-royale-3d.html');
  await page.goto(url, { waitUntil: 'load', timeout: 15000 });
  await page.waitForTimeout(1500);

  const probe = await page.evaluate(() => ({
    hasScene: !!(window as any).scene,
    hasCamera: !!(window as any).camera,
    hasRenderer: !!(window as any).renderer,
    hasHorse: !!(window as any).horseGroup,
    legsCount: ((window as any).horseLegs || []).length,
    spectatorCount: ((window as any).spectators || []).length,
    judgeCount: ((window as any).judges || []).length,
    arenaLetterCount: ((window as any).arenaLetters || []).length,
    testKeys: Object.keys((window as any).TESTS || {}),
    introMovements: (window as any).TESTS?.intro?.movements?.length || 0,
    grandprixMovements: (window as any).TESTS?.grandprix?.movements?.length || 0,
    sceneChildren: (window as any).scene ? (window as any).scene.children.length : 0,
    gamePhase: (window as any).GAME?.phase,
    gameReady: (window as any).GAME?.ready,
  }));

  console.log('DRESSAGE PROBE:', JSON.stringify(probe, null, 2));
  console.log('PAGE_ERRORS:', errors.join('\n  '));
  console.log('CONSOLE_ERRORS:', consoleErrs.join('\n  '));

  expect(errors).toEqual([]);
  expect(probe.hasScene).toBe(true);
  expect(probe.hasCamera).toBe(true);
  expect(probe.hasHorse).toBe(true);
  expect(probe.legsCount).toBe(4);
  expect(probe.spectatorCount).toBeGreaterThanOrEqual(40);
  expect(probe.judgeCount).toBe(5);
  expect(probe.arenaLetterCount).toBe(8);
  expect(probe.testKeys).toContain('intro');
  expect(probe.testKeys).toContain('grandprix');
  expect(probe.introMovements).toBeGreaterThanOrEqual(5);
  expect(probe.grandprixMovements).toBeGreaterThanOrEqual(10);

  // Start intro test directly
  await page.evaluate(() => (window as any).startTest('intro'));
  await page.waitForTimeout(500);
  const afterStart = await page.evaluate(() => ({
    phase: (window as any).GAME.phase,
    test: (window as any).GAME.test,
    horsePos: {
      x: (window as any).horseGroup.position.x,
      z: (window as any).horseGroup.position.z,
    },
  }));
  console.log('AFTER_TEST_START:', JSON.stringify(afterStart));
  expect(afterStart.phase).toBe('play');
  expect(afterStart.test).toBe('intro');

  // Press W (forward) and 2 (trot)
  await page.keyboard.press('Digit2');
  await page.keyboard.down('KeyW');
  await page.waitForTimeout(800);
  await page.keyboard.up('KeyW');
  const afterMove = await page.evaluate(() => ({
    horsePos: {
      x: (window as any).horseGroup.position.x,
      z: (window as any).horseGroup.position.z,
    },
    gait: (window as any).input.gait,
    time: (window as any).GAME.time,
  }));
  console.log('AFTER_MOVE:', JSON.stringify(afterMove));
  expect(afterMove.time).toBeGreaterThan(0.3);

  // COMPLETABILITY: every test movement that references a letter must point to a letter that exists.
  const letterCoverage = await page.evaluate(() => {
    const W = window as any;
    const known = new Set(Object.keys(W.LETTER_POSITIONS));
    const missing: string[] = [];
    for (const [tk, t] of Object.entries(W.TESTS) as any) {
      for (const [i, m] of (t.movements as any[]).entries()) {
        for (const k of ['from','to','at']) {
          if (m[k] && !known.has(m[k])) {
            missing.push(`${tk}#${i}.${k}=${m[k]}`);
          }
        }
      }
    }
    return { knownLetters: Array.from(known).sort(), missing };
  });
  console.log('LETTER_COVERAGE:', JSON.stringify(letterCoverage));
  expect(letterCoverage.missing).toEqual([]);
});
