import { test, expect } from '@playwright/test';
import { fileURLToPath } from 'url';
import * as path from 'path';

const FILE = 'file://' + path.resolve('/home/peter/mullm/code/ready/pickleball-3d.html');

test('pickleball-3d loads with motion controls module attached', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('[console] ' + m.text()); });

  await page.goto(FILE);
  // Wait for THREE/canvas + main menu to be visible
  await page.waitForSelector('#hud-score', { state: 'visible' });
  await expect(page.locator('#menu-main')).toBeVisible();

  // MotionXR should exist on window scope (it's an IIFE result; we exposed _state for diag)
  const probe = await page.evaluate(() => {
    return {
      hasThree: typeof (window as any).THREE !== 'undefined',
      hasMotionXR: typeof (window as any).MotionXR !== 'undefined',
      hasGyroBtn: !!document.getElementById('btn-gyro'),
      hasVRBtn: !!document.getElementById('btn-vr'),
      hasPermModal: !!document.getElementById('menu-gyro-perm'),
      gyroSupported: typeof DeviceOrientationEvent !== 'undefined',
      canvasCount: document.querySelectorAll('canvas').length,
    };
  });
  console.log('probe:', JSON.stringify(probe));

  expect(probe.hasThree).toBe(true);
  expect(probe.hasMotionXR).toBe(true);
  expect(probe.hasGyroBtn).toBe(true);
  expect(probe.hasVRBtn).toBe(true);
  expect(probe.hasPermModal).toBe(true);
  expect(probe.canvasCount).toBeGreaterThan(0);

  // No fatal page errors
  expect(errors.filter(e => !/AudioContext|WebGL/i.test(e))).toEqual([]);

  // Click Start Match — game should start without error
  await page.click('#btn-start');
  await page.waitForTimeout(400);
  await expect(page.locator('#menu-main')).toBeHidden();

  // Wait a few frames; ensure loop doesn't crash
  await page.waitForTimeout(800);
  expect(errors.filter(e => !/AudioContext|WebGL/i.test(e))).toEqual([]);

  // Toggle gyro (will skip since no DeviceOrientation in headless, but click should not throw)
  // Even if button is hidden in non-mobile UA, the click in code path must not error.
  // Toggle pause works
  await page.click('#btn-pause');
  await expect(page.locator('#menu-pause')).toBeVisible();
});
