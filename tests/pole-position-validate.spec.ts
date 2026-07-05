import { test, expect } from '@playwright/test';
import path from 'path';

test('pole-position 3D loads, has scene/tracks/opponents, race starts', async ({ page }) => {
  const errors: string[] = [];
  const consoleErrs: string[] = [];
  page.on('pageerror', e => errors.push(e.message + '\n' + (e.stack || '').split('\n').slice(0, 4).join('\n')));
  page.on('console', m => { if (m.type() === 'error') consoleErrs.push(m.text()); });

  const url = 'file://' + path.resolve('/home/peter/mullm/code/ready/pole-position.html');
  await page.goto(url, { waitUntil: 'load', timeout: 15000 });
  await page.waitForTimeout(1500);

  const probe = await page.evaluate(() => ({
    hasScene: !!(window as any).scene,
    hasCamera: !!(window as any).camera,
    hasRenderer: !!(window as any).renderer,
    hasPlayerCar: !!(window as any).playerCar,
    opponentCount: ((window as any).opponents || []).length,
    trackKeys: Object.keys((window as any).TRACKS || {}),
    desertSegments: (window as any).TRACKS?.desert?.segments?.length || 0,
    citySegments: (window as any).TRACKS?.city?.segments?.length || 0,
    mountainSegments: (window as any).TRACKS?.mountain?.segments?.length || 0,
    sceneChildren: (window as any).scene ? (window as any).scene.children.length : 0,
    gamePhase: (window as any).GAME?.phase,
    gameReady: (window as any).GAME?.ready,
    roadSegmentsLen: ((window as any).roadSegments || []).length,
  }));

  console.log('POLE PROBE:', JSON.stringify(probe, null, 2));
  console.log('PAGE_ERRORS:', errors.join('\n  '));
  console.log('CONSOLE_ERRORS:', consoleErrs.join('\n  '));

  expect(errors).toEqual([]);
  expect(probe.hasScene).toBe(true);
  expect(probe.hasCamera).toBe(true);
  expect(probe.hasRenderer).toBe(true);
  expect(probe.hasPlayerCar).toBe(true);
  expect(probe.opponentCount).toBe(20);
  expect(probe.trackKeys).toContain('desert');
  expect(probe.trackKeys).toContain('city');
  expect(probe.trackKeys).toContain('mountain');
  expect(probe.gamePhase).toBe('menu');

  // Click START RACE
  await page.click('#start-btn');
  await page.waitForTimeout(800);
  const afterStart = await page.evaluate(() => ({
    phase: (window as any).GAME.phase,
    track: (window as any).GAME.track,
    raceTime: (window as any).GAME.raceTime,
    speed: (window as any).playerState.speed,
  }));
  console.log('AFTER_START:', JSON.stringify(afterStart));
  expect(afterStart.phase).toBe('play');

  // Press gas
  await page.keyboard.down('ArrowUp');
  await page.waitForTimeout(800);
  await page.keyboard.up('ArrowUp');
  const afterGas = await page.evaluate(() => ({
    speed: (window as any).playerState.speed,
    z: (window as any).playerState.z,
  }));
  console.log('AFTER_GAS:', JSON.stringify(afterGas));
  expect(afterGas.speed).toBeGreaterThan(20);
  expect(afterGas.z).toBeGreaterThan(5);
});
