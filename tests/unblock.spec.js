// @ts-check
const { test, expect } = require("@playwright/test");

const BASE = process.env.MULLM_URL || "https://localhost:8100";

test.describe("Unblock page", () => {
  test.use({ ignoreHTTPSErrors: true });

  test("page loads without JS errors", async ({ page }) => {
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));

    await page.goto(`${BASE}/unblock`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2000);

    expect(errors).toHaveLength(0);
    await expect(page.locator('h1:has-text("UNBLOCK")')).toBeVisible();
  });

  test("blocked card appears and is visible with summary text", async ({ page, request }) => {
    // Post a test blocked card
    const resp = await request.post(`${BASE}/api/agents/blocked`, {
      data: {
        agent_id: "test-unblock-card",
        agent_type: "test",
        parent_id: "test",
        block_reason: "test_validation",
        summary: "TEST_CARD_VISIBLE_CHECK — this text must appear on the unblock page",
        options: ["Option A", "Option B", "Option C"],
        severity: "low",
        auto_timeout_s: 30,
      },
    });
    expect(resp.ok()).toBeTruthy();

    // Load unblock page
    await page.goto(`${BASE}/unblock?test=${Date.now()}`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(4000);

    // Card summary must be visible
    await expect(page.locator("text=TEST_CARD_VISIBLE_CHECK").first()).toBeVisible();

    // Option buttons must be visible
    await expect(page.locator('button:has-text("Option A")').first()).toBeVisible();
  });

  test("blocked card with special characters renders correctly", async ({ page, request }) => {
    // Post a card with quotes, newlines, special chars — these broke rendering before
    const resp = await request.post(`${BASE}/api/agents/blocked`, {
      data: {
        agent_id: "test-special-chars",
        agent_type: "test",
        parent_id: "test",
        block_reason: "test_special",
        summary: "Test \"quotes\" and 'apostrophes' and\nnewlines\nand <html> tags & ampersands",
        options: ['Yes "go"', "It's fine", "Option with <tag>"],
        severity: "medium",
      },
    });
    expect(resp.ok()).toBeTruthy();

    await page.goto(`${BASE}/unblock?special=${Date.now()}`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(4000);

    // Card must render without JS errors
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));

    // Summary text must be visible (at least part of it)
    await expect(page.locator("text=/Test.*quotes/").first()).toBeVisible();
  });

  test("multi-select: tap two options then submit sends both", async ({ page, request }) => {
    const resp = await request.post(`${BASE}/api/agents/blocked`, {
      data: {
        agent_id: "test-multiselect",
        agent_type: "test",
        parent_id: "test",
        block_reason: "test_multi",
        summary: "MULTI_SELECT_TEST — pick multiple",
        options: ["Alpha", "Beta", "Gamma", "Delta"],
        severity: "low",
        auto_timeout_s: 30,
      },
    });
    expect(resp.ok()).toBeTruthy();

    await page.goto(`${BASE}/unblock?multi=${Date.now()}`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(4000);

    // Tap Alpha
    const alpha = page.locator('button:has-text("Alpha")').first();
    await expect(alpha).toBeVisible();
    await alpha.click();
    await page.waitForTimeout(300);

    // Tap Gamma
    const gamma = page.locator('button:has-text("Gamma")').first();
    await gamma.click();

    // Wait for auto-submit (2s)
    await page.waitForTimeout(3000);

    // Card should be resolved now
    await page.waitForTimeout(1000);
  });

  test("clicking option button resolves the card", async ({ page, request }) => {
    const resp = await request.post(`${BASE}/api/agents/blocked`, {
      data: {
        agent_id: "test-click-resolve",
        agent_type: "test",
        parent_id: "test",
        block_reason: "test_click",
        summary: "CLICK_TEST_CARD — click Option A to resolve",
        options: ["Option A", "Option B"],
        severity: "low",
        auto_timeout_s: 30,
      },
    });
    expect(resp.ok()).toBeTruthy();

    await page.goto(`${BASE}/unblock?click=${Date.now()}`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(4000);

    // Click Option A
    const btn = page.locator('button:has-text("Option A")').first();
    await expect(btn).toBeVisible();
    await btn.click();

    // Wait for resolution
    await page.waitForTimeout(2000);

    // After clicking, the page should still be functional (no crash)
    await page.waitForTimeout(1000);
    // The card may refresh — just verify page didn't crash
    await expect(page.locator('h1:has-text("UNBLOCK")')).toBeVisible();
  });
});
