// Performance benchmark: REAL browser interactions via Playwright
// Measures what the user actually experiences — page load, typing, response render
const { test, expect } = require("@playwright/test");

const BASE = process.env.MULLM_URL || "https://localhost:8100";

test.describe("Performance Benchmark — Real Browser", () => {
  test.use({ ignoreHTTPSErrors: true });

  test("chat page: full load to interactive", async ({ page }) => {
    const metrics = {};

    // Measure full page load (browser fetches HTML, CSS, JS, renders DOM)
    const navStart = Date.now();
    await page.goto(`${BASE}/chat`, { waitUntil: "load" });
    metrics.fullLoad = Date.now() - navStart;

    // Measure time until input is actually interactive
    const interactStart = Date.now();
    const input = page.locator("#queryInput, textarea").first();
    await expect(input).toBeVisible({ timeout: 5000 });
    await input.click();
    await input.fill("test");
    const val = await input.inputValue();
    expect(val).toBe("test");
    metrics.interactive = Date.now() - interactStart;

    // Measure sidebar render
    const sidebarStart = Date.now();
    const sidebar = page.locator('#sidebar, .sidebar, [class*="sidebar"]').first();
    await expect(sidebar).toBeVisible({ timeout: 3000 });
    metrics.sidebarRender = Date.now() - sidebarStart;

    // Web Vitals via Performance API
    const perfMetrics = await page.evaluate(() => {
      const entries = performance.getEntriesByType("navigation")[0];
      const paint = performance.getEntriesByType("paint");
      const fcp = paint.find((p) => p.name === "first-contentful-paint");
      return {
        domContentLoaded: Math.round(entries?.domContentLoadedEventEnd - entries?.startTime),
        loadComplete: Math.round(entries?.loadEventEnd - entries?.startTime),
        firstContentfulPaint: fcp ? Math.round(fcp.startTime) : null,
        transferSize: entries?.transferSize || 0,
      };
    });
    Object.assign(metrics, perfMetrics);

    console.log("\n=== CHAT PAGE PERFORMANCE ===");
    console.log(`  Full load (navigation):   ${metrics.fullLoad}ms`);
    console.log(`  DOMContentLoaded:         ${metrics.domContentLoaded}ms`);
    console.log(`  Load complete:            ${metrics.loadComplete}ms`);
    console.log(`  First Contentful Paint:   ${metrics.firstContentfulPaint}ms`);
    console.log(`  Input interactive:        ${metrics.interactive}ms`);
    console.log(`  Sidebar visible:          ${metrics.sidebarRender}ms`);
    console.log(`  Transfer size:            ${(metrics.transferSize / 1024).toFixed(1)}KB`);

    // Assertions — these are the quality gates
    expect(metrics.fullLoad).toBeLessThan(4000);
    expect(metrics.interactive).toBeLessThan(2000);
    expect(metrics.domContentLoaded).toBeLessThan(3000);
  });

  test("chat: type query and get response render time", async ({ page }) => {
    await page.goto(`${BASE}/chat`, { waitUntil: "load" });
    await page.waitForTimeout(1000);

    const input = page.locator("#queryInput, textarea").first();
    await expect(input).toBeVisible();

    // Simulate real typing speed (~50ms per char)
    const query = "what is http 404";
    const typeStart = Date.now();
    await input.click();
    await page.keyboard.type(query, { delay: 50 });
    const typeTime = Date.now() - typeStart;

    // Click send and measure time to first visible response
    const sendBtn = page.locator('#sendBtn, .send-btn, button[title="Send"]').first();
    const sendStart = Date.now();
    await sendBtn.click();

    // Wait for a bot response to appear
    const botMsg = page.locator('.msg.bot .content, .bot-message, [class*="bot"] .content').first();
    await expect(botMsg).toBeVisible({ timeout: 15000 });
    const firstResponse = Date.now() - sendStart;

    // Wait for response to have actual text content
    await page.waitForFunction(
      () => {
        const el = document.querySelector('.msg.bot .content, .bot-message, [class*="bot"] .content');
        return el && el.textContent.trim().length > 5;
      },
      { timeout: 15000 }
    );
    const fullResponse = Date.now() - sendStart;

    console.log("\n=== CHAT QUERY PERFORMANCE ===");
    console.log(`  Typing (${query.length} chars):    ${typeTime}ms`);
    console.log(`  First response visible:   ${firstResponse}ms`);
    console.log(`  Full response rendered:   ${fullResponse}ms`);

    // Realtime/LUT queries should respond fast
    expect(firstResponse).toBeLessThan(5000);
  });

  test("dashboard: load and data render", async ({ page }) => {
    const navStart = Date.now();
    await page.goto(`${BASE}/dashboard`, { waitUntil: "load" });
    const loadTime = Date.now() - navStart;

    // Wait for actual data to render (not just loading spinners)
    const dataStart = Date.now();
    await page.waitForFunction(
      () => {
        const cards = document.querySelectorAll('[class*="card-value"], [class*="stat"]');
        return cards.length > 0 && [...cards].some((c) => c.textContent.trim() !== "—" && c.textContent.trim() !== "");
      },
      { timeout: 10000 }
    );
    const dataRender = Date.now() - dataStart;

    const perfMetrics = await page.evaluate(() => {
      const entries = performance.getEntriesByType("navigation")[0];
      return {
        domContentLoaded: Math.round(entries?.domContentLoadedEventEnd - entries?.startTime),
        loadComplete: Math.round(entries?.loadEventEnd - entries?.startTime),
      };
    });

    console.log("\n=== DASHBOARD PERFORMANCE ===");
    console.log(`  Full load:            ${loadTime}ms`);
    console.log(`  DOMContentLoaded:     ${perfMetrics.domContentLoaded}ms`);
    console.log(`  Load complete:        ${perfMetrics.loadComplete}ms`);
    console.log(`  Data rendered:        ${dataRender}ms`);

    expect(loadTime).toBeLessThan(4000);
    expect(dataRender).toBeLessThan(5000);
  });

  test("unblock: load and badges render", async ({ page }) => {
    const navStart = Date.now();
    await page.goto(`${BASE}/unblock`, { waitUntil: "load" });
    const loadTime = Date.now() - navStart;

    // Wait for activity bar (badges) to appear
    const badgeStart = Date.now();
    await page.waitForFunction(
      () => {
        const bar = document.querySelector('#activityBar, [id*="activity"]');
        return bar && bar.children.length > 0;
      },
      { timeout: 10000 }
    );
    const badgeRender = Date.now() - badgeStart;

    // Count badges
    const badgeCount = await page.evaluate(() => {
      const bar = document.querySelector('#activityBar, [id*="activity"]');
      return bar ? bar.children.length : 0;
    });

    console.log("\n=== UNBLOCK PERFORMANCE ===");
    console.log(`  Full load:            ${loadTime}ms`);
    console.log(`  Badge render:         ${badgeRender}ms`);
    console.log(`  Badge count:          ${badgeCount}`);

    expect(loadTime).toBeLessThan(4000);
  });

  test("performance page: load with benchmark tabs", async ({ page }) => {
    const navStart = Date.now();
    await page.goto(`${BASE}/perf`, { waitUntil: "load" });
    const loadTime = Date.now() - navStart;

    // Wait for benchmark data to render
    const benchStart = Date.now();
    await page.waitForFunction(
      () => {
        const el = document.querySelector("#benchBefore");
        return el && el.textContent.trim().length > 10;
      },
      { timeout: 10000 }
    );
    const benchRender = Date.now() - benchStart;

    console.log("\n=== PERF PAGE PERFORMANCE ===");
    console.log(`  Full load:            ${loadTime}ms`);
    console.log(`  Benchmark render:     ${benchRender}ms`);

    expect(loadTime).toBeLessThan(4000);
  });

  test("chat: rapid interaction stress (no mashing)", async ({ page }) => {
    await page.goto(`${BASE}/chat`, { waitUntil: "load" });
    await page.waitForTimeout(1000);

    const input = page.locator("#queryInput, textarea").first();
    await expect(input).toBeVisible();

    // 3 sequential queries with realistic pauses between them
    const queries = ["what is 2+2", "what is http 200", "what is git status"];
    const times = [];

    for (const q of queries) {
      await input.click();
      await input.fill("");
      await page.keyboard.type(q, { delay: 30 });

      const sendBtn = page.locator('#sendBtn, .send-btn, button[title="Send"]').first();
      const start = Date.now();
      await sendBtn.click();

      // Wait for new bot response
      await page.waitForFunction((count) => document.querySelectorAll(".msg.bot").length > count, times.length, {
        timeout: 15000,
      });
      times.push(Date.now() - start);

      // Realistic pause between queries
      await page.waitForTimeout(500);
    }

    console.log("\n=== RAPID INTERACTION (3 queries) ===");
    times.forEach((t, i) => console.log(`  Query ${i + 1} ("${queries[i]}"): ${t}ms`));
    console.log(`  Average: ${Math.round(times.reduce((a, b) => a + b, 0) / times.length)}ms`);

    // Each query should complete reasonably fast
    times.forEach((t) => expect(t).toBeLessThan(10000));
  });
});
