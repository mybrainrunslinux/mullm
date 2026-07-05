import { test, expect } from "@playwright/test";

const BASE = process.env.MULLM_URL || "https://127.0.0.1:8100";

test("Culinary Divinity: title -> play -> ingredient click works", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  await page.goto(BASE + "/code/ready/culinary-divinity.html", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(500);
  // Click play
  await page.click("#play");
  await page.waitForTimeout(800);
  // Title should be hidden, dock should have ingredients
  const titleHidden = await page.evaluate(() => document.getElementById("title")?.style.display === "none");
  expect(titleHidden).toBe(true);
  const ingCount = await page.locator(".ing").count();
  expect(ingCount).toBeGreaterThan(10);
  // Click an ingredient
  await page.locator(".ing").first().click();
  await page.waitForTimeout(200);
  expect(errors).toEqual([]);
});

test("Isometric Fortress: title -> play -> select tool -> place wall -> start wave", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  await page.goto(BASE + "/code/ready/isometric-fortress.html", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(400);
  await page.click("#play-btn");
  await page.waitForTimeout(500);
  // Select wall tool
  await page.click("#t-wall");
  await page.waitForTimeout(100);
  // Click on canvas center to attempt placement
  const cv = page.locator("#game");
  const box = await cv.boundingBox();
  if (box) {
    await page.mouse.click(box.x + box.width/2, box.y + box.height/2);
    await page.waitForTimeout(200);
  }
  // Start wave
  await page.click("#start-wave");
  await page.waitForTimeout(1500);
  // Check that wave incremented
  const waveText = await page.locator("#wave-stat").textContent();
  expect(waveText).toBe("1");
  expect(errors).toEqual([]);
});

test("Viking Voyage: title -> play -> open map", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  await page.goto(BASE + "/code/ready/viking-voyage.html", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(400);
  await page.click("#play-btn");
  await page.waitForTimeout(400);
  // Open map
  await page.click("#map-btn");
  await page.waitForTimeout(400);
  const mapVisible = await page.evaluate(() => document.getElementById("map-overlay")?.classList.contains("show"));
  expect(mapVisible).toBe(true);
  // Close map
  await page.click("#map-close");
  await page.waitForTimeout(200);
  // Hunt
  await page.click("#hunt-btn");
  await page.waitForTimeout(200);
  expect(errors).toEqual([]);
});

test("Forge Empires: title -> begin (easy) -> tutorial appears -> select house", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  await page.goto(BASE + "/code/ready/forge-empires.html", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(500);
  // Confirm easy is checked by default
  const easyChecked = await page.locator('input[value="easy"]').isChecked();
  expect(easyChecked).toBe(true);
  await page.click("#begin-btn");
  await page.waitForTimeout(800);
  // Tutorial arrow should appear
  const tutVisible = await page.evaluate(() => document.getElementById("tutorial-arrow")?.style.display === "block");
  expect(tutVisible).toBe(true);
  // Click house
  await page.locator('.build-btn[data-key="house"]').click();
  await page.waitForTimeout(400);
  // Tutorial should advance — text should be different
  const tutText = await page.locator("#tutorial-text").textContent();
  expect(tutText?.toLowerCase()).toContain("farm");
  expect(errors).toEqual([]);
});
