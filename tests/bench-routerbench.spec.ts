/**
 * RouterBench panel tests — validates the $0 router leaderboard comparison.
 * Uses page.route() to mock API calls — never actually runs the benchmark.
 */
import { test, expect, Page } from '@playwright/test';

const BASE = process.env.MULLM_URL || 'https://127.0.0.1:8100';

const MOCK_ROUTERBENCH_RESULT = {
  mode: 'routerbench',
  routers: [
    {
      router: 'mullm',
      mullm_score: 0.9801,
      quality_score: 0.9200,
      local_pct: 0.8400,
      routing_precision: 0.9500,
      routing_recall: 0.8800,
      cost_efficiency: 1.1322,
      savings_vs_cloud: 0.168,
    },
    {
      router: 'always_local',
      mullm_score: 0.7071,
      quality_score: 0.7000,
      local_pct: 1.0000,
      routing_precision: 0.7000,
      routing_recall: 1.0000,
      cost_efficiency: 2.0000,
      savings_vs_cloud: 0.2,
    },
    {
      router: 'random',
      mullm_score: 0.4950,
      quality_score: 0.5000,
      local_pct: 0.5000,
      routing_precision: 0.5000,
      routing_recall: 0.5000,
      cost_efficiency: 1.0000,
      savings_vs_cloud: 0.1,
    },
    {
      router: 'bert',
      mullm_score: 0.8100,
      quality_score: 0.8100,
      local_pct: 0.7500,
      routing_precision: 0.8500,
      routing_recall: 0.7800,
      cost_efficiency: 1.0400,
      savings_vs_cloud: 0.15,
    },
    {
      router: 'always_cloud',
      mullm_score: 0.0000,
      quality_score: 0.3000,
      local_pct: 0.0000,
      routing_precision: 0.0000,
      routing_recall: 0.0000,
      cost_efficiency: 0.0000,
      savings_vs_cloud: 0.0,
    },
  ],
  winner: 'mullm',
  timestamp: new Date().toISOString(),
  total_problems: 200,
  threshold: 0.5,
};

async function mockRouterBenchAPI(page: Page) {
  // Mock the bench run endpoint
  await page.route('**/api/bench/run', async (route) => {
    const body = route.request().postDataJSON();
    if (body?.mode === 'routerbench') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_ROUTERBENCH_RESULT),
      });
    } else {
      await route.continue();
    }
  });
}

test.describe('RouterBench panel', () => {
  test('RouterBench panel exists and "Set the Bar" is gone', async ({ page }) => {
    await page.goto(`${BASE}/bench`, { waitUntil: 'domcontentloaded' });

    // RouterBench card must be present
    const routerBenchCard = page.locator('.mode-card.bar');
    await expect(routerBenchCard).toBeVisible({ timeout: 10000 });
    const cardTitle = routerBenchCard.locator('.mode-card-title');
    await expect(cardTitle).toContainText('RouterBench');

    // "Set the Bar" text should NOT appear in mode cards
    const modeCards = page.locator('.mode-card');
    const cardTexts = await modeCards.allTextContents();
    const hasSetTheBar = cardTexts.some(t => t.includes('Set the Bar'));
    expect(hasSetTheBar).toBe(false);
  });

  test('RouterBench tab exists and "Set the Bar" tab is gone', async ({ page }) => {
    await page.goto(`${BASE}/bench`, { waitUntil: 'domcontentloaded' });

    // Tab must say "RouterBench"
    const tab = page.locator('#he-tab-bar');
    await expect(tab).toBeVisible({ timeout: 10000 });
    await expect(tab).toContainText('RouterBench');

    // Old text should be gone from the tab
    await expect(tab).not.toContainText('Set the Bar');
  });

  test('RouterBench card has correct pills and button', async ({ page }) => {
    await page.goto(`${BASE}/bench`, { waitUntil: 'domcontentloaded' });

    const card = page.locator('.mode-card.bar');
    await expect(card).toBeVisible({ timeout: 10000 });

    // Should have $0 pill
    await expect(card.locator('.meta-pill').first()).toContainText('$0');

    // Should have Run RouterBench button
    const btn = page.locator('#btn-routerbench');
    await expect(btn).toBeVisible();
    await expect(btn).toContainText('Run RouterBench');
  });

  test('RouterBench panel shows empty state initially', async ({ page }) => {
    await page.goto(`${BASE}/bench`, { waitUntil: 'domcontentloaded' });

    // Switch to the RouterBench tab
    await page.locator('#he-tab-bar').click();

    // Empty state should be visible
    const emptyState = page.locator('#he-bar-empty');
    await expect(emptyState).toBeVisible({ timeout: 5000 });
    await expect(emptyState).toContainText('Run RouterBench');
  });

  test('clicking Run RouterBench calls API and renders 5-row leaderboard', async ({ page }) => {
    await mockRouterBenchAPI(page);
    await page.goto(`${BASE}/bench`, { waitUntil: 'domcontentloaded' });

    // Click the RouterBench button
    const btn = page.locator('#btn-routerbench');
    await expect(btn).toBeVisible({ timeout: 10000 });
    await btn.click();

    // Switch to the RouterBench results tab
    await page.locator('#he-tab-bar').click();

    // Leaderboard table should appear with 5 router rows
    const tableRows = page.locator('#he-bar-body tr');
    await expect(tableRows.first()).toBeVisible({ timeout: 10000 });
    const rowCount = await tableRows.count();
    expect(rowCount).toBe(5);
  });

  test('RouterBench leaderboard highlights mullm as winner', async ({ page }) => {
    await mockRouterBenchAPI(page);
    await page.goto(`${BASE}/bench`, { waitUntil: 'domcontentloaded' });

    await page.locator('#btn-routerbench').click();
    await page.locator('#he-tab-bar').click();

    // Winner row should have winner class or teal styling
    const winnerRow = page.locator('#he-bar-body tr.rb-winner');
    await expect(winnerRow).toBeVisible({ timeout: 10000 });
    await expect(winnerRow).toContainText('mullm');
  });

  test('RouterBench score cards appear after run', async ({ page }) => {
    await mockRouterBenchAPI(page);
    await page.goto(`${BASE}/bench`, { waitUntil: 'domcontentloaded' });

    await page.locator('#btn-routerbench').click();
    await page.locator('#he-tab-bar').click();

    // Score cards should be visible
    const scoreGrid = page.locator('#he-bar-scores');
    await expect(scoreGrid).toBeVisible({ timeout: 10000 });
  });

  test('RouterBench shows all 5 router names in table', async ({ page }) => {
    await mockRouterBenchAPI(page);
    await page.goto(`${BASE}/bench`, { waitUntil: 'domcontentloaded' });

    await page.locator('#btn-routerbench').click();
    await page.locator('#he-tab-bar').click();

    const tbody = page.locator('#he-bar-body');
    await expect(tbody).toBeVisible({ timeout: 10000 });
    const tableText = await tbody.innerText();

    expect(tableText).toContain('mullm');
    expect(tableText).toContain('always_local');
    expect(tableText).toContain('random');
    expect(tableText).toContain('bert');
    expect(tableText).toContain('always_cloud');
  });
});
