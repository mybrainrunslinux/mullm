/**
 * Tests for Escalate and PURGE functionality — covers the streaming path bug
 * where dataset.queryContent was never set, breaking both features.
 *
 * Root cause: sendStreaming() called addMessage("bot","",[], {tier, streaming:true})
 * without passing queryContent, so escalate() silently returned and deleteCacheEntry()
 * fell back to DOM traversal which sometimes fails.
 */
import { test, expect, Page } from '@playwright/test';

const BASE = process.env.MULLM_URL || 'https://127.0.0.1:8100';

// SSE stream that returns a short answer then done
const STREAM_SSE = [
  'data: {"token":"The CAP theorem states that "}\n\n',
  'data: {"token":"a distributed system cannot simultaneously guarantee "}\n\n',
  'data: {"token":"Consistency, Availability, and Partition Tolerance."}\n\n',
  'data: {"done":true,"cost":0,"total_ms":300,"tier":"local","model":"qwen3.5:9b"}\n\n',
].join('');

// Non-streaming JSON response
const NORMAL_RESPONSE = {
  response: 'The CAP theorem states that a distributed system cannot simultaneously guarantee Consistency, Availability, and Partition Tolerance.',
  tier_used: 'local',
  model_used: 'qwen3.5:9b',
  provider: 'ollama',
  cost: 0,
  total_latency_ms: 250,
  from_cache: false,
  classification: { category: 'lookup', complexity: 1 },
  suggestions: null,
};

async function mockStreamEndpoint(page: Page) {
  await page.route('**/query/stream**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      headers: {
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
      },
      body: STREAM_SSE,
    });
  });
}

async function mockNormalEndpoint(page: Page) {
  await page.route('**/query**', async (route) => {
    if (route.request().url().includes('/query/stream')) {
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

async function mockCacheDelete(page: Page) {
  await page.route('**/cache/entry', async (route) => {
    if (route.request().method() === 'DELETE') {
      const body = route.request().postDataJSON();
      if (body?.query) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ status: 'deleted', docs_remaining: 42 }),
        });
      } else {
        await route.fulfill({ status: 400, body: '{}' });
      }
    } else {
      await route.continue();
    }
  });
}

async function mockEscalateEndpoint(page: Page) {
  // Mock the /query endpoint called during escalation
  await page.route('**/query**', async (route) => {
    if (route.request().url().includes('/query/stream')) {
      await route.continue();
      return;
    }
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON();
      if (body?.force_tier) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            ...NORMAL_RESPONSE,
            tier_used: body.force_tier,
            response: 'Escalated response: ' + (body.content || ''),
          }),
        });
        return;
      }
    }
    await route.continue();
  });
}

test.describe('Escalate after streaming response', () => {
  test('streaming bot message has queryContent dataset attribute', async ({ page }) => {
    await mockStreamEndpoint(page);
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });

    // Enable streaming (should be on by default, but ensure)
    const streamToggle = page.locator('#streamToggle');
    if (await streamToggle.isVisible()) {
      const color = await streamToggle.evaluate(el => getComputedStyle(el).color);
      // If not teal/active, click to enable
      if (!color.includes('0, 188')) { // teal rgb
        await streamToggle.click();
      }
    }

    const input = page.locator('#chatInput');
    await input.fill('CAP theorem explained');
    await input.press('Enter');

    // Wait for bot message to appear
    const botMsg = page.locator('.msg.bot').last();
    await expect(botMsg).toBeVisible({ timeout: 15000 });

    // Verify dataset.queryContent is set
    const queryContent = await botMsg.evaluate(el => (el as HTMLElement).dataset.queryContent);
    expect(queryContent).toBeTruthy();
    expect(queryContent).toContain('CAP theorem');
  });

  test('escalate button works after streaming response (local → local_multi)', async ({ page }) => {
    await mockStreamEndpoint(page);
    await mockEscalateEndpoint(page);
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });

    const input = page.locator('#chatInput');
    await input.fill('CAP theorem explained');
    await input.press('Enter');

    // Wait for bot message and escalate button
    const botMsg = page.locator('.msg.bot').last();
    await expect(botMsg).toBeVisible({ timeout: 15000 });

    const escBtn = botMsg.locator('.escalate-btn');
    await expect(escBtn).toBeVisible({ timeout: 5000 });
    await expect(escBtn).not.toBeDisabled();

    // Track escalation request
    const escalationPromise = page.waitForRequest(req =>
      req.url().includes('/query') && req.method() === 'POST' &&
      !req.url().includes('stream')
    , { timeout: 5000 }).catch(() => null);

    await escBtn.click();

    const escalationReq = await escalationPromise;
    // Escalation should have fired a /query POST with force_tier
    expect(escalationReq).toBeTruthy();
    if (escalationReq) {
      const body = escalationReq.postDataJSON();
      expect(body.force_tier).toBeTruthy();
      expect(body.content).toContain('CAP theorem');
    }
  });

  test('escalate button is present on streaming responses', async ({ page }) => {
    await mockStreamEndpoint(page);
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });

    const input = page.locator('#chatInput');
    await input.fill('what is the boiling point of water');
    await input.press('Enter');

    const botMsg = page.locator('.msg.bot').last();
    await expect(botMsg).toBeVisible({ timeout: 15000 });

    const escBtn = botMsg.locator('.escalate-btn');
    await expect(escBtn).toBeVisible({ timeout: 5000 });
    expect(await escBtn.textContent()).toMatch(/escalate|▲/i);
  });
});

test.describe('PURGE after streaming response', () => {
  test('PURGE works after streaming response using queryContent dataset', async ({ page }) => {
    await mockStreamEndpoint(page);
    await mockCacheDelete(page);
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });

    const input = page.locator('#chatInput');
    await input.fill('what is the boiling point of water');
    await input.press('Enter');

    const botMsg = page.locator('.msg.bot').last();
    await expect(botMsg).toBeVisible({ timeout: 15000 });

    // Verify queryContent is set (prerequisite for PURGE to work)
    const queryContent = await botMsg.evaluate(el => (el as HTMLElement).dataset.queryContent);
    expect(queryContent).toBeTruthy();

    // Click PURGE button (need to confirm dialog)
    page.on('dialog', d => d.accept());
    const purgeBtn = botMsg.locator('button').filter({ hasText: /purge/i });
    await expect(purgeBtn).toBeVisible({ timeout: 5000 });

    const deletePromise = page.waitForRequest(req =>
      req.url().includes('/cache/entry') && req.method() === 'DELETE'
    , { timeout: 5000 }).catch(() => null);

    await purgeBtn.click();
    const deleteReq = await deletePromise;

    expect(deleteReq).toBeTruthy();
    if (deleteReq) {
      const body = deleteReq.postDataJSON();
      expect(body.query).toBeTruthy();
      expect(body.query).toContain('boiling point');
    }
  });

  test('PURGE does not show "could not find original query" error for streaming response', async ({ page }) => {
    await mockStreamEndpoint(page);
    await mockCacheDelete(page);
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });

    const input = page.locator('#chatInput');
    await input.fill('CAP theorem distributed systems');
    await input.press('Enter');

    const botMsg = page.locator('.msg.bot').last();
    await expect(botMsg).toBeVisible({ timeout: 15000 });

    page.on('dialog', d => d.accept());
    const purgeBtn = botMsg.locator('button').filter({ hasText: /purge/i });
    await expect(purgeBtn).toBeVisible({ timeout: 5000 });

    // Listen for toast error
    let errorToastSeen = false;
    page.on('console', msg => {
      if (msg.text().toLowerCase().includes('could not find')) errorToastSeen = true;
    });

    await purgeBtn.click();
    await page.waitForTimeout(1000);

    expect(errorToastSeen).toBe(false);
    // Button should show success (✓ PURGED) not error
    await expect(purgeBtn).not.toHaveText(/could not find/i);
  });
});

test.describe('PURGE and Escalate for non-streaming (normal) response', () => {
  test('non-streaming response also has queryContent set', async ({ page }) => {
    await mockNormalEndpoint(page);
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });

    // Disable streaming
    const streamToggle = page.locator('#streamToggle');
    if (await streamToggle.isVisible()) {
      // Click to disable (turn off teal)
      await streamToggle.click();
    }

    const input = page.locator('#chatInput');
    await input.fill('what is the boiling point of water');
    await input.press('Enter');

    const botMsg = page.locator('.msg.bot').last();
    await expect(botMsg).toBeVisible({ timeout: 15000 });

    const queryContent = await botMsg.evaluate(el => (el as HTMLElement).dataset.queryContent);
    expect(queryContent).toBeTruthy();
  });
});
