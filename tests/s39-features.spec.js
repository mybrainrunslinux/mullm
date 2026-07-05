// S39 feature tests: gen intercept, image gallery, intake, video upscale endpoint
const { test, expect } = require("@playwright/test");

const BASE = process.env.MULLM_URL || "https://localhost:8100";

test.describe("S39: Generation intercept in chat", () => {
  test.use({ ignoreHTTPSErrors: true });

  test("3D model preset shows generation intercept card not LLM refusal", async ({ page }) => {
    const jsErrors = [];
    page.on("pageerror", (e) => {
      const msg = e.message || "";
      if (!msg.includes("module is not defined") && !msg.includes("IDENT_RE")) {
        jsErrors.push(msg);
      }
    });
    await page.goto(`${BASE}/chat`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2000);

    const input = page.locator("#queryInput, textarea").first();
    await input.fill("Generate a 3D model of a medieval castle with towers and a drawbridge");
    await input.press("Enter");

    // Wait for the intercept card to appear (not an LLM response)
    await page.waitForTimeout(1500);

    // Should show generation intercept card, not "I can't generate" text
    const pageText = await page.textContent("body");
    expect(pageText).not.toContain("I can't generate or create actual 3D models");
    expect(pageText).not.toContain("I cannot generate");

    // Should show the gen intercept card UI
    const genCard = page.locator(".gen-intercept-card");
    await expect(genCard).toBeVisible({ timeout: 5000 });

    // Should have a button to open 3D Studio
    const studioBtn = page.locator('a[href="/3d"]');
    await expect(studioBtn).toBeVisible();

    expect(jsErrors).toHaveLength(0);
  });

  test("image generation preset shows intercept card", async ({ page }) => {
    await page.goto(`${BASE}/chat`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2000);

    const input = page.locator("#queryInput, textarea").first();
    await input.fill("Generate an image of a neon cyberpunk city at night with flying cars");
    await input.press("Enter");
    await page.waitForTimeout(1500);

    const genCard = page.locator(".gen-intercept-card");
    await expect(genCard).toBeVisible({ timeout: 5000 });
  });

  test("regular chat message is NOT intercepted", async ({ page }) => {
    await page.goto(`${BASE}/chat`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2000);

    const input = page.locator("#queryInput, textarea").first();
    await input.fill("What is 2 + 2?");
    await input.press("Enter");
    await page.waitForTimeout(1500);

    // Should NOT show gen intercept card for a math question
    const genCard = page.locator(".gen-intercept-card");
    await expect(genCard).not.toBeVisible();
  });
});

test.describe("S39: Image gallery loads", () => {
  test.use({ ignoreHTTPSErrors: true });

  test("/api/image/list returns valid JSON with images key", async ({ request }) => {
    const resp = await request.get(`${BASE}/api/image/list`, {
      ignoreHTTPSErrors: true
    });
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data).toHaveProperty("images");
    expect(data).toHaveProperty("total");
    expect(typeof data.total).toBe("number");
  });

  test("/image page gallery section visible", async ({ page }) => {
    await page.goto(`${BASE}/image`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2000);
    // Gallery container should exist
    const gallery = page.locator("#gallery-grid, .masonry-grid, .gallery-card").first();
    await expect(gallery).toBeVisible({ timeout: 5000 });
  });
});

test.describe("S39: Intake UI", () => {
  test.use({ ignoreHTTPSErrors: true });

  test("/intake page loads", async ({ page }) => {
    const jsErrors = [];
    page.on("pageerror", (e) => jsErrors.push(e.message));
    await page.goto(`${BASE}/intake`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2000);
    const textarea = page.locator("#intakeText");
    await expect(textarea).toBeVisible();
    const submitBtn = page.locator(".submit-btn");
    await expect(submitBtn).toBeVisible();
    expect(jsErrors.filter(e => !e.includes("IDENT_RE"))).toHaveLength(0);
  });

  test("POST /api/intake with task text returns queued response", async ({ request }) => {
    const resp = await request.post(`${BASE}/api/intake`, {
      data: { text: "S39 test: build a simple hello world game" },
      ignoreHTTPSErrors: true
    });
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.type).toBe("task");
    expect(data.action).toBe("queued");
    expect(data).toHaveProperty("queue_position");
  });

  test("POST /api/intake with question returns answered response", async ({ request }) => {
    const resp = await request.post(`${BASE}/api/intake`, {
      data: { text: "What is the capital of France?" },
      ignoreHTTPSErrors: true
    });
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.type).toBe("question");
    expect(data.action).toBe("answered");
    expect(data.response).toBeTruthy();
  });

  test("GET /api/intake/queue returns items list", async ({ request }) => {
    const resp = await request.get(`${BASE}/api/intake/queue`, {
      ignoreHTTPSErrors: true
    });
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data).toHaveProperty("items");
    expect(Array.isArray(data.items)).toBeTruthy();
  });
});

test.describe("S39: Video upscale endpoint", () => {
  test.use({ ignoreHTTPSErrors: true });

  test("POST /api/video/upscale returns 400 when no url provided", async ({ request }) => {
    const resp = await request.post(`${BASE}/api/video/upscale`, {
      data: {},
      ignoreHTTPSErrors: true
    });
    // Should return 400 for missing url (not 404 which would mean route not found)
    expect(resp.status()).toBe(400);
  });

  test("/comfyui page no longer shows upscale-not-active message", async ({ page }) => {
    await page.goto(`${BASE}/comfyui`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2000);
    const pageText = await page.textContent("body");
    expect(pageText).not.toContain("not yet active");
  });
});

test.describe("S39: Chat savings bench param", () => {
  test.use({ ignoreHTTPSErrors: true });

  test("/api/dashboard?bench=opus_ext returns savings", async ({ request }) => {
    const resp = await request.get(`${BASE}/api/dashboard?bench=opus_ext`, {
      ignoreHTTPSErrors: true
    });
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data).toHaveProperty("savings");
    expect(typeof data.savings).toBe("number");
  });
});
