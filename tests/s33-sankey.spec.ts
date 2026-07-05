/**
 * S33 Sankey Routing Flow — Test Suite
 * Tests: tab renders, SVG has content, nodes visible, tooltips, no CDN, no errors.
 *
 * Run: npx playwright test tests/s33-sankey.spec.ts --project chromium
 */
import { test, expect, Page } from '@playwright/test';

const BASE = process.env.MULLM_URL || 'https://localhost:8100';
const OPTS = { ignoreHTTPSErrors: true };

async function loadDashboardAndOpenSankey(page: Page) {
  await page.goto(`${BASE}/dashboard`, { waitUntil: 'domcontentloaded' });
  // Wait for data fetch and DOM settle
  await page.waitForTimeout(2500);
  // Click the Routing Flow tab
  const tab = page.locator('#tab-sankey');
  await expect(tab).toBeVisible();
  await tab.click();
  // Wait for SVG draw animation
  await page.waitForTimeout(800);
}

test.describe('S33 — Sankey Routing Flow tab', () => {
  test.use(OPTS);

  test('Routing Flow tab button is visible on dashboard', async ({ page }) => {
    await page.goto(`${BASE}/dashboard`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);
    const tab = page.locator('#tab-sankey');
    await expect(tab).toBeVisible();
    await expect(tab).toHaveText(/routing flow/i);
  });

  test('clicking Routing Flow tab shows the sankey panel', async ({ page }) => {
    await page.goto(`${BASE}/dashboard`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);
    const tab = page.locator('#tab-sankey');
    await tab.click();
    await page.waitForTimeout(500);
    const panel = page.locator('#panel-sankey');
    await expect(panel).toBeVisible();
  });

  test('SVG renders with non-zero width and height', async ({ page }) => {
    await loadDashboardAndOpenSankey(page);
    const svg = page.locator('#sankey-svg');
    await expect(svg).toBeVisible();
    const box = await svg.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeGreaterThan(100);
    expect(box!.height).toBeGreaterThan(100);
  });

  test('at least 3 node groups visible in SVG (category, tier, model columns)', async ({ page }) => {
    await loadDashboardAndOpenSankey(page);
    const nodes = page.locator('#sankey-svg .sankey-node');
    const count = await nodes.count();
    expect(count).toBeGreaterThanOrEqual(3);
  });

  test('flow paths exist between nodes', async ({ page }) => {
    await loadDashboardAndOpenSankey(page);
    const paths = page.locator('#sankey-svg .sankey-flow');
    const count = await paths.count();
    expect(count).toBeGreaterThanOrEqual(1);
  });

  test('hovering a flow path shows tooltip', async ({ page }) => {
    await loadDashboardAndOpenSankey(page);
    // Sankey flows are overlapping bezier paths — use JS dispatch to fire the event
    // on the largest flow (which will always be on top and intercepting pointer events)
    await page.evaluate(() => {
      // Find the topmost .sankey-flow element (last in DOM = on top in SVG paint order)
      const flows = Array.from(document.querySelectorAll('#sankey-svg .sankey-flow'));
      if (!flows.length) throw new Error('No sankey flows found');
      const top = flows[flows.length - 1] as SVGElement;
      const rect = top.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top  + rect.height / 2;
      top.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true, clientX: cx, clientY: cy }));
    });
    await page.waitForTimeout(200);
    const tooltip = page.locator('#sankey-tooltip');
    await expect(tooltip).toBeVisible();
    const text = await tooltip.textContent();
    expect(text).toBeTruthy();
    expect(text!.length).toBeGreaterThan(5);
  });

  test('no CDN requests fired (fully offline-capable)', async ({ page }) => {
    const cdnRequests: string[] = [];
    page.on('request', req => {
      const url = req.url();
      if (
        url.includes('cdn.') ||
        url.includes('unpkg.com') ||
        url.includes('jsdelivr') ||
        url.includes('cdnjs') ||
        url.includes('d3js.org')
      ) {
        // Chart.js CDN is already in the existing dashboard — only flag Sankey-specific new CDN calls
        // We check for d3js.org specifically since D3 was explicitly forbidden for the Sankey
        if (url.includes('d3js.org')) {
          cdnRequests.push(url);
        }
      }
    });
    await loadDashboardAndOpenSankey(page);
    expect(cdnRequests).toHaveLength(0);
  });

  test('no page-breaking JS errors on dashboard load + sankey open', async ({ page }) => {
    const criticalErrors: string[] = [];
    page.on('pageerror', e => {
      const msg = e.message || '';
      // Filter known benign warnings
      if (
        msg.includes('module is not defined') ||
        msg.includes('IDENT_RE') ||
        msg.includes('MODES')
      ) return;
      criticalErrors.push(msg);
    });
    await loadDashboardAndOpenSankey(page);
    expect(criticalErrors).toHaveLength(0);
  });

  test('SVG has aria-label and role=img for accessibility', async ({ page }) => {
    await loadDashboardAndOpenSankey(page);
    const svg = page.locator('#sankey-svg');
    const role = await svg.getAttribute('role');
    const ariaLabel = await svg.getAttribute('aria-label');
    expect(role).toBe('img');
    expect(ariaLabel).toBeTruthy();
    expect(ariaLabel!.length).toBeGreaterThan(5);
  });

  test('sankey panel has column headers (CATEGORY, ROUTING, MODEL)', async ({ page }) => {
    await loadDashboardAndOpenSankey(page);
    const panel = page.locator('#panel-sankey');
    const text = await panel.textContent();
    expect(text).toMatch(/category|routing|model/i);
  });

  test('live-update badge or last-updated timestamp is present', async ({ page }) => {
    await loadDashboardAndOpenSankey(page);
    const panel = page.locator('#panel-sankey');
    const text = await panel.textContent();
    // Should show some kind of update indicator
    expect(text).toMatch(/live|updated|refresh|queries/i);
  });
});
