/**
 * ELO Composite Score Badge — Playwright tests
 *
 * Verifies:
 *   1. Badge element is present in the DOM on page load
 *   2. When localStorage has bench_suite_last, the badge shows XX/100
 *   3. When no localStorage data, shows the fallback "Run benchmarks" text
 *   4. Tooltip is accessible (contains weight breakdown text)
 *
 * Run: npx playwright test tests/elo-badge.spec.ts --project chromium
 */
import { test, expect } from '@playwright/test';

const BASE = process.env.MULLM_URL || 'https://127.0.0.1:8100';
const OPTS = { ignoreHTTPSErrors: true };

// Minimal synthetic suite result matching run_all() shape
const MOCK_SUITE_DATA = {
  mullm_score: 72.5,
  elapsed_s: 45.3,
  humaneval: { pass_at_1: 0.85, passed: 17, total: 20, results: [] },
  mbpp:      { pass_at_1: 0.90, passed: 9,  total: 10, results: [] },
  multipl_e: { pass_at_1: 0.80, results: [] },
  routing:   { accuracy: 0.95, correct: 19, scored: 20, results: [] },
  latency:   { total_median_ms: 320, total_p95_ms: 890, results: [] },
  cache:     { hit_rate: 0.78, results: [] },
  gamedev:   { avg_score: 0.70, pass_rate: 0.70, results: [] },
  summary: {
    humaneval_pass_at_1_pct:  85.0,
    mbpp_pass_at_1_pct:       90.0,
    multipl_e_pass_at_1_pct:  80.0,
    routing_accuracy_pct:     95.0,
    latency_median_ms:        320,
    latency_p95_ms:           890,
    cache_hit_rate_pct:       78.0,
    gamedev_pass_rate_pct:    70.0,
    gamedev_avg_score:        0.70,
    mullm_score:              72.5,
  },
};

test.describe('ELO Composite Score Badge', () => {
  test.use(OPTS);

  test('badge element is present in the DOM', async ({ page }) => {
    await page.goto(`${BASE}/bench`, { waitUntil: 'domcontentloaded' });
    const badge = page.locator('#elo-badge-wrap');
    await expect(badge).toBeAttached({ timeout: 10000 });
  });

  test('badge shows fallback text when no localStorage data', async ({ page }) => {
    // Clear any stored suite data before navigating
    await page.goto(`${BASE}/bench`, { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => localStorage.removeItem('bench_suite_last'));
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(800);

    const numEl = page.locator('#elo-score-num');
    await expect(numEl).toBeVisible({ timeout: 5000 });
    const text = await numEl.textContent();
    // Should show the "no data" placeholder
    expect(text).toContain('Run benchmarks');
  });

  test('badge shows XX/100 number after injecting mock suite data', async ({ page }) => {
    await page.goto(`${BASE}/bench`, { waitUntil: 'domcontentloaded' });

    // Inject mock suite result into localStorage and call updateEloBadge
    await page.evaluate((mockData) => {
      const ts = Date.now();
      localStorage.setItem('bench_suite_last', JSON.stringify({ ts, data: mockData }));
      // Trigger the badge update directly
      if (typeof (window as any).updateEloBadge === 'function') {
        (window as any).updateEloBadge(mockData, ts);
      }
    }, MOCK_SUITE_DATA);

    const numEl = page.locator('#elo-score-num');
    await expect(numEl).toBeVisible({ timeout: 5000 });
    const text = await numEl.textContent();

    // Should contain "/ 100" format
    expect(text).toMatch(/\d+\.\d+\s*\/\s*100/);
    // Score should be 72.5
    expect(text).toContain('72.5');
  });

  test('badge persists XX/100 after page reload with localStorage data', async ({ page }) => {
    // Pre-seed localStorage before first navigation
    await page.goto(`${BASE}/bench`, { waitUntil: 'domcontentloaded' });
    const ts = Date.now();
    await page.evaluate(
      ({ mockData, mockTs }) => {
        localStorage.setItem('bench_suite_last', JSON.stringify({ ts: mockTs, data: mockData }));
      },
      { mockData: MOCK_SUITE_DATA, mockTs: ts }
    );

    // Reload — badge should restore from localStorage
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1000);

    const numEl = page.locator('#elo-score-num');
    await expect(numEl).toBeVisible({ timeout: 8000 });
    const text = await numEl.textContent();
    expect(text).toMatch(/\d+\.\d+\s*\/\s*100/);
    expect(text).toContain('72.5');
  });

  test('tooltip contains weight breakdown categories', async ({ page }) => {
    await page.goto(`${BASE}/bench`, { waitUntil: 'domcontentloaded' });

    // Inject data so tooltip has content
    await page.evaluate((mockData) => {
      const ts = Date.now();
      if (typeof (window as any).updateEloBadge === 'function') {
        (window as any).updateEloBadge(mockData, ts);
      }
    }, MOCK_SUITE_DATA);

    // Hover over the badge to trigger tooltip
    const wrap = page.locator('#elo-badge-wrap');
    await wrap.hover();
    await page.waitForTimeout(300);

    const tooltip = page.locator('#elo-tooltip');
    await expect(tooltip).toBeAttached();

    // Tooltip should contain key benchmark category names
    const tooltipText = await tooltip.textContent();
    expect(tooltipText).toContain('HumanEval');
    expect(tooltipText).toContain('Routing');
    expect(tooltipText).toContain('Cache');
  });

  test('badge wrap loses no-data class when score is populated', async ({ page }) => {
    await page.goto(`${BASE}/bench`, { waitUntil: 'domcontentloaded' });

    // Before data: has no-data class
    await page.evaluate(() => localStorage.removeItem('bench_suite_last'));
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(500);

    const wrap = page.locator('#elo-badge-wrap');
    await expect(wrap).toHaveClass(/no-data/);

    // After injecting data: no-data class removed
    await page.evaluate((mockData) => {
      if (typeof (window as any).updateEloBadge === 'function') {
        (window as any).updateEloBadge(mockData, Date.now());
      }
    }, MOCK_SUITE_DATA);

    await expect(wrap).not.toHaveClass(/no-data/);
  });
});
