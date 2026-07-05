// Critical path smoke tests — MUST pass before every commit
// These verify the absolute minimum: pages load, no JS crashes, core UI works
const { test, expect } = require("@playwright/test");

const BASE = process.env.MULLM_URL || "https://localhost:8100";

test.describe("Critical Path — blocks commit if failing", () => {
  test.use({ ignoreHTTPSErrors: true });

  test("chat loads with zero critical JS errors", async ({ page }) => {
    const criticalErrors = [];
    page.on("pageerror", (e) => {
      const msg = e.message || "";
      // Ignore highlight.js module.exports warnings (cosmetic, not breaking)
      if (msg.includes("module is not defined") || msg.includes("IDENT_RE") || msg.includes("MODES")) return;
      criticalErrors.push(msg);
    });

    await page.goto(`${BASE}/chat`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(3000);

    expect(criticalErrors).toHaveLength(0);
  });

  test("chat input accepts text and send button exists", async ({ page }) => {
    await page.goto(`${BASE}/chat`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2000);

    const input = page.locator("#queryInput, textarea").first();
    await expect(input).toBeVisible();
    await input.fill("test message");
    const val = await input.inputValue();
    expect(val).toBe("test message");

    const sendBtn = page.locator('#sendBtn, .send-btn, button[title="Send"]').first();
    await expect(sendBtn).toBeVisible();
    await expect(sendBtn).toBeEnabled();
  });

  test("sidebar loads with Dexie chat history", async ({ page }) => {
    await page.goto(`${BASE}/chat`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(3000);

    // Dexie must be defined
    const dexieOk = await page.evaluate(() => typeof Dexie !== "undefined");
    expect(dexieOk).toBe(true);

    // Sidebar must have some content (not just empty icons)
    const sidebar = page.locator('#sidebar, .sidebar, [class*="sidebar"]').first();
    await expect(sidebar).toBeVisible();
  });

  test("sending a message does not crash (streaming path)", async ({ page }) => {
    await page.goto(`${BASE}/chat`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(3000);

    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));

    // Type and click send
    const input = page.locator("#queryInput, textarea").first();
    await input.fill("What is 2+2?");
    const sendBtn = page.locator('#sendBtn, .send-btn, button[title="Send"]').first();
    await sendBtn.click();

    // Wait for response (streaming or not)
    await page.waitForTimeout(8000);

    // No JS crash during send
    const criticalErrors = errors.filter(
      (e) => !e.includes("module is not defined") && !e.includes("IDENT_RE") && !e.includes("MODES")
    );
    expect(criticalErrors).toHaveLength(0);

    // Should have at least one bot response WITH CONTENT (not empty)
    const botMsgs = page.locator('.msg.bot, .msg[class*="bot"]');
    const count = await botMsgs.count();
    expect(count).toBeGreaterThanOrEqual(1);

    // Bot response must have actual content (not empty)
    if (count > 0) {
      const lastContent = await botMsgs
        .last()
        .locator(".content")
        .innerText()
        .catch(() => "");
      expect(lastContent.trim().length).toBeGreaterThan(0);
    }
  });

  test("unblock page loads and cards render", async ({ page }) => {
    // Post a test card using page.evaluate (respects ignoreHTTPSErrors)
    await page.goto(`${BASE}/unblock`, { waitUntil: "domcontentloaded" });
    await page.evaluate(async (base) => {
      await fetch(`${base}/api/agents/blocked`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          agent_id: "precommit-test",
          agent_type: "test",
          parent_id: "test",
          block_reason: "precommit",
          summary: "PRECOMMIT_SMOKE_TEST",
          options: ["OK"],
          severity: "low",
          auto_timeout_s: 30,
        }),
      });
    }, BASE);

    await page.goto(`${BASE}/unblock?precommit=${Date.now()}`, { waitUntil: "domcontentloaded" });
    await expect(page.locator("text=PRECOMMIT_SMOKE_TEST").first()).toBeVisible({ timeout: 10000 });
  });

  test("chat page loads under 3 seconds", async ({ page }) => {
    const start = Date.now();
    await page.goto(`${BASE}/chat`, { waitUntil: "domcontentloaded" });
    const loadTime = Date.now() - start;

    // Page must load DOM in under 3 seconds
    expect(loadTime).toBeLessThan(3000);

    // Input must be interactive quickly
    const interactStart = Date.now();
    const input = page.locator("#queryInput, textarea").first();
    await expect(input).toBeVisible({ timeout: 2000 });
    const interactTime = Date.now() - interactStart;

    // Input visible within 2 seconds of DOM load
    expect(interactTime).toBeLessThan(2000);
  });

  test("dashboard page loads under 3 seconds", async ({ page }) => {
    const start = Date.now();
    await page.goto(`${BASE}/dashboard`, { waitUntil: "domcontentloaded" });
    const loadTime = Date.now() - start;
    expect(loadTime).toBeLessThan(3000);
  });

  test("unblock page loads under 3 seconds", async ({ page }) => {
    const start = Date.now();
    await page.goto(`${BASE}/unblock`, { waitUntil: "domcontentloaded" });
    const loadTime = Date.now() - start;
    expect(loadTime).toBeLessThan(3000);
  });

  test("coding-medium query returns code, not warmup error", async ({ page }) => {
    // Regression: qwen3-coder:30b parked in VRAM blocks qwen3.5:9b from loading.
    // This catches the "Local models are warming up" false-positive after >60s uptime.
    // Uses page.request so ignoreHTTPSErrors is inherited; 45s timeout covers cold model load.
    const res = await page.request.post(`${BASE}/query`, {
      data: {
        content:
          "Write a Python function word_break(s, word_dict) that returns True if s can be segmented into space-separated words from word_dict. DP approach.",
      },
      timeout: 45000,
    });
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    // Must NOT return warmup/error response
    expect(body.response).not.toContain("warming up");
    expect(body.response).not.toContain("try again in a moment");
    expect(body.model_used).not.toBe("error");
    // Must contain actual code
    expect(body.response.toLowerCase()).toMatch(/def word_break|dp|dynamic/);
  });
});
