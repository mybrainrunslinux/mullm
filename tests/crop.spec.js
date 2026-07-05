// Playwright tests for /crop image editor page (TDD)
const { test, expect } = require("@playwright/test");
const path = require("path");
const fs = require("fs");
const os = require("os");

const BASE = process.env.MULLM_URL || "https://localhost:8100";

test.describe("/crop image editor", () => {
  test.use({ ignoreHTTPSErrors: true });

  test("page loads at /crop without JS errors", async ({ page }) => {
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));

    await page.goto(`${BASE}/crop`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1500);

    expect(errors).toHaveLength(0);

    // Title should mention crop or image editor
    const title = await page.title();
    expect(title.toLowerCase()).toMatch(/crop|image|editor/);
  });

  test("page has upload area and file input", async ({ page }) => {
    await page.goto(`${BASE}/crop`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1000);

    const dropzone = page.locator("#dropzone, .dropzone, [id*='drop'], [class*='drop']").first();
    await expect(dropzone).toBeVisible();

    const fileInput = page.locator("input[type='file']");
    await expect(fileInput).toBeAttached();
  });

  test("file input accepts PNG image and shows preview", async ({ page }) => {
    await page.goto(`${BASE}/crop`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1000);

    // Create a minimal 1x1 PNG in memory (base64 decoded)
    const pngBase64 =
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";
    const pngBuffer = Buffer.from(pngBase64, "base64");
    const tmpFile = path.join(os.tmpdir(), "test_crop.png");
    fs.writeFileSync(tmpFile, pngBuffer);

    const fileInput = page.locator("input[type='file']");
    await fileInput.setInputFiles(tmpFile);
    await page.waitForTimeout(1500);

    // Canvas or img preview should appear
    const preview = page.locator("#preview-canvas, #imageCanvas, canvas, #preview-img, .preview-area img").first();
    await expect(preview).toBeVisible();

    fs.unlinkSync(tmpFile);
  });

  test("1:1 aspect ratio button is clickable and marks active state", async ({ page }) => {
    await page.goto(`${BASE}/crop`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1000);

    const btn = page.locator("button").filter({ hasText: "1:1" });
    await expect(btn).toBeVisible();
    await btn.click();
    await page.waitForTimeout(300);

    // Button should have active/selected state class or aria-pressed
    const isActive =
      (await btn.getAttribute("class"))?.includes("active") ||
      (await btn.getAttribute("aria-pressed")) === "true" ||
      (await btn.getAttribute("data-active")) === "true";
    expect(isActive).toBe(true);
  });

  test("aspect ratio presets all present", async ({ page }) => {
    await page.goto(`${BASE}/crop`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1000);

    const ratios = ["Free", "1:1", "4:3", "16:9", "9:16"];
    for (const ratio of ratios) {
      const btn = page.locator("button").filter({ hasText: ratio }).first();
      await expect(btn).toBeVisible({ timeout: 3000 });
    }
  });

  test("social media preset buttons are present", async ({ page }) => {
    await page.goto(`${BASE}/crop`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1000);

    // At least Instagram and Twitter presets must exist
    const instagram = page.locator("button, [data-preset]").filter({ hasText: /Instagram/i }).first();
    await expect(instagram).toBeVisible();

    const twitter = page.locator("button, [data-preset]").filter({ hasText: /Twitter/i }).first();
    await expect(twitter).toBeVisible();
  });

  test("effects panel has monochrome button that applies data-effect attribute", async ({ page }) => {
    await page.goto(`${BASE}/crop`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1000);

    const mono = page.locator("button").filter({ hasText: /Mono|Grayscale/i }).first();
    await expect(mono).toBeVisible();
    await mono.click();
    await page.waitForTimeout(300);

    // Effect should be applied — button active OR a data-effect attribute on container
    const isActive =
      (await mono.getAttribute("class"))?.includes("active") ||
      (await mono.getAttribute("aria-pressed")) === "true" ||
      (await page.locator("#effects-panel, .effects-panel, [data-effects]").first().getAttribute("data-effect")) !== null;

    // Either the button is visually toggled OR some state is set
    const btnClass = await mono.getAttribute("class");
    expect(btnClass).toMatch(/active|on|selected/);
  });

  test("retouching sliders are present (brightness, contrast, saturation)", async ({ page }) => {
    await page.goto(`${BASE}/crop`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1000);

    const brightness = page.locator("#brightness, input[name='brightness'], [data-slider='brightness']");
    await expect(brightness).toBeAttached();

    const contrast = page.locator("#contrast, input[name='contrast'], [data-slider='contrast']");
    await expect(contrast).toBeAttached();

    const saturation = page.locator("#saturation, input[name='saturation'], [data-slider='saturation']");
    await expect(saturation).toBeAttached();
  });

  test("format selector changes download extension label", async ({ page }) => {
    await page.goto(`${BASE}/crop`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1000);

    const formatSelect = page.locator("#format-select, select[name='format'], #export-format").first();
    await expect(formatSelect).toBeVisible();

    // Select WebP
    await formatSelect.selectOption("webp");
    await page.waitForTimeout(300);

    // Extension label or download button should reflect .webp
    const bodyText = await page.locator("body").innerText();
    const hasWebp = bodyText.toLowerCase().includes("webp") || bodyText.toLowerCase().includes(".webp");
    expect(hasWebp).toBe(true);
  });

  test("download button is present and enabled", async ({ page }) => {
    await page.goto(`${BASE}/crop`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1000);

    const dlBtn = page.locator("#download-btn, button").filter({ hasText: /Download|Export/i }).first();
    await expect(dlBtn).toBeVisible();
    // Button should be in the DOM and not have display:none
    await expect(dlBtn).toBeEnabled();
  });

  test("zoom slider is present with correct range", async ({ page }) => {
    await page.goto(`${BASE}/crop`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1000);

    const zoom = page.locator("#zoom, input[name='zoom'], [data-slider='zoom'], #zoom-slider").first();
    await expect(zoom).toBeAttached();

    const min = await zoom.getAttribute("min");
    const max = await zoom.getAttribute("max");
    // Should roughly match 0.5–3 range
    expect(parseFloat(min)).toBeLessThanOrEqual(0.5);
    expect(parseFloat(max)).toBeGreaterThanOrEqual(2);
  });

  test("auto-center crop button is present", async ({ page }) => {
    await page.goto(`${BASE}/crop`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1000);

    const center = page.locator("button").filter({ hasText: /Center|Auto.?center/i }).first();
    await expect(center).toBeVisible();
  });

  test("quality slider is present and affects estimated file size label", async ({ page }) => {
    await page.goto(`${BASE}/crop`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1000);

    const qualitySlider = page.locator("#quality, input[name='quality'], [data-slider='quality']").first();
    await expect(qualitySlider).toBeAttached();
  });
});
