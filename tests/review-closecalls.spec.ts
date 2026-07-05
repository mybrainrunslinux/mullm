/**
 * Tests for /review page — Close Calls tab.
 * Mocks /api/review/items for browser tests (deterministic, no server state dependency).
 * Tests 7-8 hit real API endpoints.
 */
import { test, expect, Page } from '@playwright/test';

const BASE = process.env.MULLM_URL || 'https://10.0.0.165:8100';

// Controlled test data — 3 items, all unvoted
const MOCK_ITEMS = {
  items: [
    {
      prompt: 'Should this simple question go to local or cloud?',
      prompt_hash: 'aabbcc1122334455aabbcc1122334455aabbcc11',
      cloud_response: 'This is the cloud response for item 1.',
      local_response: 'This is the local response for item 1.',
      category: 'lookup',
      complexity: 2,
      voted: false,
      verdict: null,
    },
    {
      prompt: 'Explain the difference between TCP and UDP protocols.',
      prompt_hash: 'bbccdd2233445566bbccdd2233445566bbccdd22',
      cloud_response: 'TCP is connection-oriented; UDP is connectionless.',
      local_response: 'Local: TCP is reliable; UDP is fast.',
      category: 'technical',
      complexity: 3,
      voted: false,
      verdict: null,
    },
    {
      prompt: 'What is the capital of France?',
      prompt_hash: 'ccddee3344556677ccddee3344556677ccddee33',
      cloud_response: 'Paris.',
      local_response: 'Paris.',
      category: 'lookup',
      complexity: 1,
      voted: false,
      verdict: null,
    },
  ],
  total: 3,
  voted: 0,
};

async function mockReviewItems(page: Page, overrides: Partial<typeof MOCK_ITEMS> = {}) {
  const data = { ...MOCK_ITEMS, ...overrides };
  await page.route('**/api/review/items', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(data),
    });
  });
}

async function mockVoteEndpoint(page: Page) {
  await page.route('**/api/review/vote', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, total_votes: 1 }),
    });
  });
}

async function navigateToCloseCalls(page: Page) {
  await page.goto(`${BASE}/review`, { waitUntil: 'domcontentloaded' });
  const tab = page.locator('button#tab-closecalls, button[onclick*="closecalls"]');
  await tab.waitFor({ state: 'visible', timeout: 10000 });
  await tab.click();
}

// ── Test 1: Page loads — Close Calls tab does not get stuck on LOADING ────────

test('Close Calls tab: does not show LOADING after 5 seconds', async ({ page }) => {
  await mockReviewItems(page);
  await mockVoteEndpoint(page);
  await navigateToCloseCalls(page);

  // Wait up to 5 seconds for content to appear
  await page.waitForTimeout(5000);

  const loadingEl = page.locator('#cc-loading');
  // Either loading element is gone/hidden, or it no longer says "Loading review items..."
  const loadingText = await loadingEl.textContent().catch(() => '');
  const loadingVisible = await loadingEl.isVisible().catch(() => false);

  const cardVisible = await page.locator('#cc-current-card').isVisible().catch(() => false);
  const doneVisible = await page.locator('.cc-done-screen').isVisible().catch(() => false);

  // At least one of: card appeared, done screen appeared, or loading text is no longer the default
  const notStuck =
    cardVisible ||
    doneVisible ||
    !loadingVisible ||
    (loadingText !== 'Loading review items...' && loadingText !== 'Loading...');

  expect(notStuck, `Close Calls stuck: loading="${loadingText}", cardVisible=${cardVisible}`).toBe(true);
});

// ── Test 2: Items load — a card appears with non-empty prompt text ─────────────

test('Close Calls tab: first card has non-empty prompt text', async ({ page }) => {
  await mockReviewItems(page);
  await mockVoteEndpoint(page);
  await navigateToCloseCalls(page);

  const card = page.locator('#cc-current-card');
  await card.waitFor({ state: 'visible', timeout: 8000 });

  const prompt = page.locator('#cc-current-card .cc-prompt');
  const text = await prompt.textContent();
  expect(text?.trim().length).toBeGreaterThan(0);
});

// ── Test 3: Vote local_ok — POST intercepted, card advances, progress increments ─

test('Close Calls: vote local_ok sends POST, card advances, progress increments', async ({ page }) => {
  await mockReviewItems(page);

  // Intercept the vote POST and capture body
  const voteBodies: string[] = [];
  await page.route('**/api/review/vote', async (route) => {
    voteBodies.push(route.request().postData() || '');
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, total_votes: 1 }),
    });
  });

  await navigateToCloseCalls(page);
  const card = page.locator('#cc-current-card');
  await card.waitFor({ state: 'visible', timeout: 8000 });

  // Read initial prompt + progress
  const initialPrompt = await page.locator('#cc-current-card .cc-prompt').textContent();
  const initialProgress = await page.locator('#cc-progress-text').textContent();

  // Click the "LOCAL" vote button
  const localBtn = page.locator('.cc-vote-btn.local-ok').first();
  await localBtn.waitFor({ state: 'visible', timeout: 5000 });
  await localBtn.click();

  // Wait a tick for async render
  await page.waitForTimeout(500);

  // Card should have changed (new prompt or done screen)
  const newPrompt = await page.locator('#cc-current-card .cc-prompt').textContent().catch(() => '');
  const newProgress = await page.locator('#cc-progress-text').textContent();
  const doneVisible = await page.locator('.cc-done-screen').isVisible().catch(() => false);

  // Prompt should have changed OR done screen appeared (all items voted)
  const cardAdvanced = doneVisible || newPrompt !== initialPrompt;
  expect(cardAdvanced, `Card did not advance: initial="${initialPrompt}", new="${newPrompt}"`).toBe(true);

  // Progress should have incremented
  const progressChanged = newProgress !== initialProgress;
  expect(progressChanged, `Progress did not change: "${initialProgress}" -> "${newProgress}"`).toBe(true);

  // Vote POST should have been fired
  await page.waitForTimeout(300);
  expect(voteBodies.length).toBeGreaterThan(0);
  const body = JSON.parse(voteBodies[0]);
  expect(body.verdict).toBe('local_ok');
  expect(body.prompt_hash).toBeTruthy();
});

// ── Test 4: Vote cloud_needed — POST intercepted, card advances ───────────────

test('Close Calls: vote cloud_needed sends POST with correct verdict', async ({ page }) => {
  await mockReviewItems(page);

  const voteBodies: string[] = [];
  await page.route('**/api/review/vote', async (route) => {
    voteBodies.push(route.request().postData() || '');
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, total_votes: 1 }),
    });
  });

  await navigateToCloseCalls(page);
  const card = page.locator('#cc-current-card');
  await card.waitFor({ state: 'visible', timeout: 8000 });

  const initialPrompt = await page.locator('#cc-current-card .cc-prompt').textContent();

  const cloudBtn = page.locator('.cc-vote-btn.cloud-needed').first();
  await cloudBtn.waitFor({ state: 'visible', timeout: 5000 });
  await cloudBtn.click();

  await page.waitForTimeout(500);

  const newPrompt = await page.locator('#cc-current-card .cc-prompt').textContent().catch(() => '');
  const doneVisible = await page.locator('.cc-done-screen').isVisible().catch(() => false);
  const cardAdvanced = doneVisible || newPrompt !== initialPrompt;
  expect(cardAdvanced).toBe(true);

  await page.waitForTimeout(300);
  expect(voteBodies.length).toBeGreaterThan(0);
  const body = JSON.parse(voteBodies[0]);
  expect(body.verdict).toBe('cloud_needed');
});

// ── Test 5: Keyboard shortcut "1" — vote local_ok ────────────────────────────

test('Close Calls: keyboard "1" casts local_ok vote', async ({ page }) => {
  await mockReviewItems(page);

  const voteBodies: string[] = [];
  await page.route('**/api/review/vote', async (route) => {
    voteBodies.push(route.request().postData() || '');
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, total_votes: 1 }),
    });
  });

  await navigateToCloseCalls(page);
  const card = page.locator('#cc-current-card');
  await card.waitFor({ state: 'visible', timeout: 8000 });

  const initialPrompt = await page.locator('#cc-current-card .cc-prompt').textContent();

  // Click somewhere neutral to ensure focus is not on an input
  await page.locator('body').click();
  await page.keyboard.press('1');

  await page.waitForTimeout(500);

  const newPrompt = await page.locator('#cc-current-card .cc-prompt').textContent().catch(() => '');
  const doneVisible = await page.locator('.cc-done-screen').isVisible().catch(() => false);
  const cardAdvanced = doneVisible || newPrompt !== initialPrompt;
  expect(cardAdvanced, `Keyboard "1" did not advance card`).toBe(true);

  await page.waitForTimeout(300);
  expect(voteBodies.length).toBeGreaterThan(0);
  const body = JSON.parse(voteBodies[0]);
  expect(body.verdict).toBe('local_ok');
});

// ── Test 6: Skip — "S" key advances card without voting ──────────────────────

test('Close Calls: keyboard "S" skips card without voting', async ({ page }) => {
  await mockReviewItems(page);

  const voteBodies: string[] = [];
  await page.route('**/api/review/vote', async (route) => {
    voteBodies.push(route.request().postData() || '');
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true }),
    });
  });

  await navigateToCloseCalls(page);
  const card = page.locator('#cc-current-card');
  await card.waitFor({ state: 'visible', timeout: 8000 });

  const initialPrompt = await page.locator('#cc-current-card .cc-prompt').textContent();

  // Click neutral area, then press S
  await page.locator('body').click();
  await page.keyboard.press('s');

  await page.waitForTimeout(500);

  const newPrompt = await page.locator('#cc-current-card .cc-prompt').textContent().catch(() => '');
  // Skip moves first unvoted to end, so prompt changes (we have 3 items)
  expect(newPrompt).not.toBe(initialPrompt);

  // No votes should have been posted
  await page.waitForTimeout(300);
  expect(voteBodies.length).toBe(0);
});

// ── Test 7: API /api/review/items — real endpoint ────────────────────────────

test('API /api/review/items returns {items, total} with correct fields', async ({ request }) => {
  const resp = await request.get(`${BASE}/api/review/items`);
  expect(resp.ok()).toBeTruthy();
  const body = await resp.json();
  expect(typeof body.total).toBe('number');
  expect(Array.isArray(body.items)).toBe(true);

  if (body.items.length > 0) {
    const item = body.items[0];
    expect(typeof item.prompt).toBe('string');
    expect(item.prompt.length).toBeGreaterThan(0);
    // cloud_response and local_response may be null/empty but keys should exist or prompt_hash present
    expect(typeof item.prompt_hash).toBe('string');
  }
});

// ── Test 8: API /api/review/vote — POST with valid payload returns {ok: true} ─

test('API /api/review/vote returns {ok: true} for valid vote', async ({ request }) => {
  // First fetch items to get a real prompt_hash
  const itemsResp = await request.get(`${BASE}/api/review/items`);
  expect(itemsResp.ok()).toBeTruthy();
  const itemsBody = await itemsResp.json();

  let promptHash = 'ca87bf1e1f02f3e966ca720e6ac4d455f531b804'; // fallback known hash
  if (itemsBody.items.length > 0 && itemsBody.items[0].prompt_hash) {
    promptHash = itemsBody.items[0].prompt_hash;
  }

  const resp = await request.post(`${BASE}/api/review/vote`, {
    data: { prompt_hash: promptHash, verdict: 'local_ok' },
  });
  expect(resp.ok()).toBeTruthy();
  const body = await resp.json();
  expect(body.ok).toBe(true);
});
