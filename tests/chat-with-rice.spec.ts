/**
 * Tests for the WITH RICE toggle button in chat.html.
 * Verifies: button exists, toggles visual state, and sends powerup:true in payload.
 */
import { test, expect, Page } from '@playwright/test';

const BASE = process.env.MULLM_URL || 'https://127.0.0.1:8100';

const NORMAL_RESPONSE = {
  response: 'Test response',
  tier_used: 'local',
  model_used: 'qwen3.5:9b',
  provider: 'ollama',
  cost: 0,
  total_latency_ms: 150,
  from_cache: false,
  classification: { category: 'lookup', complexity: 1 },
  suggestions: null,
};

async function mockQueryEndpoint(page: Page) {
  await page.route('**/query', async (route) => {
    if (route.request().method() !== 'POST') {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(NORMAL_RESPONSE),
    });
  });
}

test('WITH RICE — button exists in chat input area', async ({ page }) => {
  await page.goto(`${BASE}/chat`, { waitUntil: 'domcontentloaded' });
  const riceBtn = page.locator('#riceToggle');
  await expect(riceBtn).toBeVisible({ timeout: 10000 });
  await expect(riceBtn).toHaveText(/RICE/i);
});

test('WITH RICE — button has correct tooltip', async ({ page }) => {
  await page.goto(`${BASE}/chat`, { waitUntil: 'domcontentloaded' });
  const riceBtn = page.locator('#riceToggle');
  await expect(riceBtn).toBeVisible({ timeout: 10000 });
  const title = await riceBtn.getAttribute('title');
  expect(title).toContain('RICE');
});

test('WITH RICE — button starts with aria-pressed false', async ({ page }) => {
  await page.goto(`${BASE}/chat`, { waitUntil: 'domcontentloaded' });
  const riceBtn = page.locator('#riceToggle');
  await expect(riceBtn).toBeVisible({ timeout: 10000 });
  await expect(riceBtn).toHaveAttribute('aria-pressed', 'false');
});

test('WITH RICE — toggle changes aria-pressed to true', async ({ page }) => {
  await page.goto(`${BASE}/chat`, { waitUntil: 'domcontentloaded' });
  const riceBtn = page.locator('#riceToggle');
  await expect(riceBtn).toBeVisible({ timeout: 10000 });
  await riceBtn.click();
  await expect(riceBtn).toHaveAttribute('aria-pressed', 'true');
});

test('WITH RICE — toggle twice returns to false', async ({ page }) => {
  await page.goto(`${BASE}/chat`, { waitUntil: 'domcontentloaded' });
  const riceBtn = page.locator('#riceToggle');
  await expect(riceBtn).toBeVisible({ timeout: 10000 });
  await riceBtn.click();
  await riceBtn.click();
  await expect(riceBtn).toHaveAttribute('aria-pressed', 'false');
});

test('WITH RICE — enabled button has gold color style', async ({ page }) => {
  await page.goto(`${BASE}/chat`, { waitUntil: 'domcontentloaded' });
  const riceBtn = page.locator('#riceToggle');
  await expect(riceBtn).toBeVisible({ timeout: 10000 });
  await riceBtn.click();
  // After enabling, color should reference gold (not var(--text3))
  const color = await riceBtn.evaluate((el: HTMLElement) => el.style.color);
  expect(color).toContain('gold');
});

test('WITH RICE — sends powerup:true in query payload when enabled @spend', async ({ page }) => {
  // Capture outgoing request bodies before navigation
  const requestBodies: string[] = [];

  await page.goto(`${BASE}/chat`, { waitUntil: 'domcontentloaded' });

  // Mock both /query and /query/stream so no real requests are made
  await page.route('**/query/stream**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: 'data: {"token":"ok"}\n\ndata: {"done":true,"cost":0,"total_ms":100,"tier":"local","model":"qwen3.5:9b"}\n\n',
    });
  });
  await page.route('**/query', async (route) => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    requestBodies.push(route.request().postData() || '');
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(NORMAL_RESPONSE),
    });
  });

  // Intercept all POST /query requests
  page.on('request', (req) => {
    if (req.url().includes('/query') && req.method() === 'POST' && !req.url().includes('stream')) {
      requestBodies.push(req.postData() || '');
    }
  });

  // Disable streaming to use POST /query not GET /query/stream
  const streamBtn = page.locator('#streamToggle');
  await expect(streamBtn).toBeVisible({ timeout: 10000 });
  // Click to turn OFF streaming (it defaults to ON)
  await streamBtn.click();

  // Enable RICE mode
  const riceBtn = page.locator('#riceToggle');
  await expect(riceBtn).toBeVisible({ timeout: 5000 });
  await riceBtn.click();
  await expect(riceBtn).toHaveAttribute('aria-pressed', 'true');

  // Type and send a message
  const textarea = page.locator('#queryInput');
  await textarea.fill('hello rice test');
  await textarea.press('Enter');

  // Wait for request to fire
  await page.waitForTimeout(1000);

  // At least one request should have powerup: true
  const hasRice = requestBodies.some((body) => {
    try {
      return JSON.parse(body).powerup === true;
    } catch {
      return false;
    }
  });
  expect(hasRice).toBe(true);
});

test('WITH RICE — does NOT send powerup when disabled', async ({ page }) => {
  const requestBodies: string[] = [];

  await page.goto(`${BASE}/chat`, { waitUntil: 'domcontentloaded' });

  await page.route('**/query/stream**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: 'data: {"token":"ok"}\n\ndata: {"done":true,"cost":0,"total_ms":100,"tier":"local","model":"qwen3.5:9b"}\n\n',
    });
  });
  await page.route('**/query', async (route) => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    requestBodies.push(route.request().postData() || '');
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(NORMAL_RESPONSE),
    });
  });

  // Disable streaming
  const streamBtn = page.locator('#streamToggle');
  await expect(streamBtn).toBeVisible({ timeout: 10000 });
  await streamBtn.click();

  // Do NOT click RICE toggle — leave it off
  const textarea = page.locator('#queryInput');
  await textarea.fill('hello no rice');
  await textarea.press('Enter');

  await page.waitForTimeout(1000);

  // No request should have powerup: true
  const hasRice = requestBodies.some((body) => {
    try {
      return JSON.parse(body).powerup === true;
    } catch {
      return false;
    }
  });
  expect(hasRice).toBe(false);
});
