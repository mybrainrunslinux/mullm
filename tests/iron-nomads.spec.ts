import { test, expect } from '@playwright/test';

const URL = (process.env.MULLM_URL || 'https://127.0.0.1:8100') + '/code/ready/iron-nomads.html';

test.describe('Iron Nomads', () => {
  test('loads without JS errors', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    await page.goto(URL, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3500);

    // Filter benign GLB 404s if assets unreachable in test env (the game must still boot)
    const fatal = errors.filter(e =>
      !/\.glb/i.test(e) &&
      !/favicon/i.test(e) &&
      !/SSL|HTTPS|self.signed|TLS/i.test(e)
    );
    expect(fatal, `unexpected JS errors: ${fatal.join('\n')}`).toEqual([]);
  });

  test('canvas is visible and large', async ({ page }) => {
    await page.goto(URL, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);
    const canvas = page.locator('canvas').first();
    await expect(canvas).toBeVisible();
    const box = await canvas.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeGreaterThan(400);
    expect(box!.height).toBeGreaterThan(400);
  });

  test('window.GAME exists after boot', async ({ page }) => {
    await page.goto(URL, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);
    const hasGame = await page.evaluate(() => !!(window as any).GAME);
    expect(hasGame).toBe(true);
    const hasState = await page.evaluate(() => !!(window as any).GAME?.state);
    expect(hasState).toBe(true);
    const hasDispatch = await page.evaluate(() => typeof (window as any).GAME?.dispatch === 'function');
    expect(hasDispatch).toBe(true);
  });

  test('mode select screen visible', async ({ page }) => {
    await page.goto(URL, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);
    await expect(page.locator('#mode-select')).toBeVisible();
    await expect(page.locator('#btn-quick')).toBeVisible();
    await expect(page.locator('#btn-career')).toBeVisible();
  });

  test('clicking QUICK DRAFT enters draft phase', async ({ page }) => {
    await page.goto(URL, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2500);
    await page.click('#btn-quick');
    await page.waitForTimeout(1000);
    // Either the draft panel or in-game HUD must be visible
    const draftVisible = await page.locator('#draft-panel').isVisible().catch(() => false);
    const hudVisible = await page.locator('#hud').isVisible().catch(() => false);
    expect(draftVisible || hudVisible).toBe(true);
    // GAME state should record the mode
    const mode = await page.evaluate(() => (window as any).GAME?.state?.mode);
    expect(['quick', 'draft', 'run']).toContain(mode);
  });
});
