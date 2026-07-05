import { test, expect } from '@playwright/test';
const URL = process.env.MULLM_URL || 'https://127.0.0.1:8100';
test.use({ ignoreHTTPSErrors: true });

const games = [
  { name: 'help-me-move',           three: true,  selector: '#char-dock' },
  { name: 'jacks',                  three: true,  selector: 'canvas, #canvas' },
  { name: 'hay-and-harness',        three: true,  selector: 'canvas, #canvas' },
  { name: 'clockwork-arena-tactics',three: false, selector: 'canvas, #canvas' },
];

for (const g of games) {
  test(`${g.name} loads with no nuclear errors`, async ({ page }) => {
    const errs: string[] = [];
    page.on('pageerror', (e) => errs.push(e.message));
    page.on('console', (m) => { if (m.type()==='error') errs.push(m.text()); });
    await page.goto(`${URL}/code/ready/${g.name}.html`);
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(1500);
    // expected key element should render
    const sel = g.selector.split(',')[0].trim();
    await expect(page.locator(sel).first()).toBeVisible({ timeout: 4000 });
    // partB / partC errors (set by stitcher)
    const partB_err = await page.evaluate(() => (window as any).__partB_error);
    const partC_err = await page.evaluate(() => (window as any).__partC_error);
    console.log(`[${g.name}] partB_err=${partB_err}`);
    console.log(`[${g.name}] partC_err=${partC_err}`);
    if (errs.length) console.log(`[${g.name}] errors=`, errs.slice(0,3));
    // Soft assertion: no SyntaxError or unhandled ReferenceError chains that prevent boot
    const nuclear = errs.some(e => /SyntaxError|Cannot use import statement|Unexpected token/.test(e));
    expect(nuclear, `[${g.name}] nuclear: ${errs.join('|')}`).toBe(false);
  });
}
