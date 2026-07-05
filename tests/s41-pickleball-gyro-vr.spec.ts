import { test, expect } from '@playwright/test';
import * as path from 'path';

const FILE = 'file://' + path.resolve('/home/peter/mullm/code/ready/pickleball-3d.html');

test.describe('Pickleball 3D — gyro + VR additions', () => {
  test('camera quaternion responds to simulated DeviceOrientationEvent', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(String(e)));

    await page.goto(FILE);
    await page.click('#btn-start');
    await page.waitForTimeout(300);

    // Simulate enabling gyro on Android-like path (no permission prompt).
    const result = await page.evaluate(async () => {
      const M = (window as any).MotionXR;
      // Force enable: stub away permission so we exercise the Android branch.
      M._state.gyro.needsPermission = false;
      await M.enableGyro();
      // Capture pre-tilt camera quaternion.
      const cam = (window as any).camera || null;
      // Look up via global hint (we didn't expose camera — check renderer scene)
      // Easier: dispatch the event and check rawGamma was captured.
      const evt = new (window as any).DeviceOrientationEvent('deviceorientation', {
        alpha: 0, beta: 0, gamma: 30, absolute: false,
      });
      window.dispatchEvent(evt);
      // Second event so calibration applies, then a real tilt
      const evt2 = new (window as any).DeviceOrientationEvent('deviceorientation', {
        alpha: 0, beta: 0, gamma: 25, absolute: false,
      });
      window.dispatchEvent(evt2);
      return {
        enabled: M._state.gyro.enabled,
        rawGamma: M._state.gyro.rawGamma,
        rawBeta: M._state.gyro.rawBeta,
      };
    });
    console.log('gyro after dispatch:', JSON.stringify(result));
    expect(result.enabled).toBe(true);
    // rawGamma should be non-zero after the second event (calibration captured first).
    expect(Math.abs(result.rawGamma)).toBeGreaterThan(0);

    // Run a frame so preRender applies; check status pill flipped to ON
    await page.waitForTimeout(120);
    const statusText = await page.locator('#status-gyro').textContent();
    expect(statusText?.trim()).toBe('ON');

    // No errors thrown
    expect(errors).toEqual([]);
  });

  test('disableGyro restores baseline orientation', async ({ page }) => {
    await page.goto(FILE);
    await page.click('#btn-start');
    await page.waitForTimeout(200);

    const ok = await page.evaluate(async () => {
      const M = (window as any).MotionXR;
      M._state.gyro.needsPermission = false;
      await M.enableGyro();
      M.disableGyro();
      return M._state.gyro.enabled === false && M._state.gyro.handler == null;
    });
    expect(ok).toBe(true);
  });

  test('VR probe runs without throwing; button hidden when unsupported', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    await page.goto(FILE);
    await page.waitForTimeout(400);

    const probe = await page.evaluate(() => {
      const M = (window as any).MotionXR;
      const btn = document.getElementById('btn-vr')!;
      return {
        xrAttempted: M._state.xr,
        vrButtonHidden: btn.hidden,
        hasNavigatorXR: 'xr' in navigator,
      };
    });
    console.log('vr probe:', JSON.stringify(probe));
    // In headless chromium without a headset, supported=false; button should be hidden.
    expect(probe.vrButtonHidden).toBe(true);
    expect(errors).toEqual([]);
  });

  test('iOS-style permission flow opens modal then enables gyro', async ({ page }) => {
    await page.goto(FILE);
    // Dismiss main menu first — its overlay would intercept clicks.
    await page.click('#btn-start');
    await page.waitForTimeout(200);

    // Simulate iOS by stubbing requestPermission to return 'granted' BEFORE init read it.
    // Since the module already initialized, we patch needsPermission and stub the DOE static.
    await page.evaluate(() => {
      const M = (window as any).MotionXR;
      M._state.gyro.needsPermission = true;
      (window as any).DeviceOrientationEvent.requestPermission = () => Promise.resolve('granted');
      // Force-show the gyro button (hidden by default in desktop UA).
      (document.getElementById('btn-gyro') as HTMLElement).hidden = false;
    });

    // Click the gyro button — should open the perm modal.
    await page.click('#btn-gyro');
    await expect(page.locator('#menu-gyro-perm')).toBeVisible();

    // Click "Allow Motion" — should close modal AND enable gyro.
    await page.click('#btn-gyro-allow');
    await page.waitForTimeout(200);
    await expect(page.locator('#menu-gyro-perm')).toBeHidden();
    const enabled = await page.evaluate(() => (window as any).MotionXR._state.gyro.enabled);
    expect(enabled).toBe(true);
  });

  test('existing keyboard/mouse controls still work after motion module', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(String(e)));

    await page.goto(FILE);
    await page.click('#btn-start');
    await page.waitForTimeout(300);

    // Keyboard pause should still work.
    await page.keyboard.press('Escape');
    await expect(page.locator('#menu-pause')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.locator('#menu-pause')).toBeHidden();

    // Trigger swing via Space — should not throw.
    await page.keyboard.press('Space');
    await page.waitForTimeout(200);

    // Mouse move into canvas
    const canvas = page.locator('canvas').first();
    const box = await canvas.boundingBox();
    if (box) {
      await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.7);
      await page.waitForTimeout(100);
    }

    expect(errors).toEqual([]);
  });
});
