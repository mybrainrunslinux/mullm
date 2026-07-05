// Playwright smoke test for hay-and-harness enhancements
const { test, expect } = require('@playwright/test');
const path = require('path');

test.use({ ignoreHTTPSErrors: true });

const URL = 'file://' + path.resolve('/home/peter/mullm/code/ready/hay-and-harness.html');

test('hay-and-harness boots and exposes enhancements', async ({ page }) => {
    const errors = [];
    page.on('pageerror', e => errors.push('pageerror: ' + e.message));
    page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

    await page.goto(URL, { waitUntil: 'networkidle' });
    await page.waitForFunction(() => window.__hay && window.__hay.STATE, { timeout: 15000 });

    // 1. Window API exposes new fields
    const api = await page.evaluate(() => Object.keys(window.__hay));
    console.log('window.__hay keys:', api.join(','));
    expect(api).toContain('CHAR_TYPES');
    expect(api).toContain('WORLD_NAMES');
    expect(api).toContain('setWorld');
    expect(api).toContain('setHardMode');
    expect(api).toContain('addCarrots');
    expect(api).toContain('pickets');
    expect(api).toContain('buses');

    // 2. CHAR_TYPES has 12 types
    const charCount = await page.evaluate(() => window.__hay.CHAR_TYPES.length);
    expect(charCount).toBe(12);

    // 3. Pickets array populated by buildWorld
    const pickCount = await page.evaluate(() => window.__hay.pickets.length);
    console.log('initial pickets:', pickCount);
    expect(pickCount).toBeGreaterThan(0);

    // 4. Hud shows carrot
    const moneyText = await page.locator('#money').innerText();
    console.log('money element:', moneyText);
    expect(moneyText).toContain('0');
    // The carrot codepoint should be present
    expect(moneyText.codePointAt(0)).toBe(0x1F955);

    // 5. World label shows World 1
    const wLabel = await page.locator('#worldLabel').innerText();
    console.log('worldLabel:', wLabel);
    expect(wLabel).toContain('Farm Town');

    // 6. Start the game and run a tick or two
    await page.evaluate(() => window.__hay.forceStart());
    await page.waitForTimeout(200);
    const running = await page.evaluate(() => window.__hay.STATE.running);
    expect(running).toBe(true);

    // 7. Force-unlock world 2 via API and confirm it switches
    await page.evaluate(() => window.__hay.setWorld(2));
    await page.waitForTimeout(100);
    const w2 = await page.evaluate(() => ({
        world: window.__hay.STATE.world,
        label: document.getElementById('worldLabel').textContent
    }));
    console.log('after setWorld(2):', JSON.stringify(w2));
    expect(w2.world).toBe(2);
    expect(w2.label).toContain('Country');

    // 8. Force world 3 and confirm buses spawn
    await page.evaluate(() => window.__hay.setWorld(3));
    await page.waitForTimeout(150);
    const w3 = await page.evaluate(() => ({
        world: window.__hay.STATE.world,
        buses: window.__hay.buses.length,
        label: document.getElementById('worldLabel').textContent
    }));
    console.log('after setWorld(3):', JSON.stringify(w3));
    expect(w3.world).toBe(3);
    expect(w3.buses).toBeGreaterThan(0);
    expect(w3.label).toContain('London');

    // 9. Carrot threshold triggers banner
    await page.evaluate(() => { window.__hay.STATE.unlockedWorld = 1; window.__hay.setWorld(1); });
    await page.waitForTimeout(50);
    await page.evaluate(() => window.__hay.addCarrots(600));
    await page.waitForTimeout(100);
    const unlocked = await page.evaluate(() => ({
        unlockedWorld: window.__hay.STATE.unlockedWorld,
        bannerVisible: document.getElementById('worldBanner').classList.contains('show'),
        bannerText: document.getElementById('worldBanner').textContent,
    }));
    console.log('after +600 carrots:', JSON.stringify(unlocked));
    expect(unlocked.unlockedWorld).toBeGreaterThanOrEqual(2);
    expect(unlocked.bannerVisible).toBe(true);

    // 10. Hard mode toggles hunger bar visibility
    await page.evaluate(() => window.__hay.setHardMode(true));
    await page.waitForTimeout(50);
    const hudWrapDisplay = await page.evaluate(() => {
        return getComputedStyle(document.getElementById('hungerWrap')).display;
    });
    console.log('hard mode hungerWrap display:', hudWrapDisplay);
    expect(hudWrapDisplay).not.toBe('none');

    // 11. Verify pickup spawns a character mesh
    await page.evaluate(() => window.__hay.setPickup());
    await page.waitForTimeout(50);
    const pending = await page.evaluate(() => {
        const c = window.__hay.STATE.pendingChar;
        return c ? { type: c.userData.charType, label: c.userData.label, children: c.children.length } : null;
    });
    console.log('pendingChar after setPickup:', JSON.stringify(pending));
    expect(pending).not.toBeNull();
    expect(pending.children).toBeGreaterThan(2);
    expect(pending.label).toBeTruthy();

    // 12. No console errors
    if (errors.length > 0){
        console.log('ERRORS captured:');
        errors.forEach(e => console.log(' -', e));
    }
    expect(errors.length).toBe(0);
});
