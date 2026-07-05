// @ts-check
const { test, expect } = require("@playwright/test");

/**
 * Strike a Match — matchstick puzzle game smoke test.
 * Verifies load, HUD, canvas interaction, level navigation and keyboard input.
 */

test.describe("strike-a-match", () => {
  test("loads with HUD, canvas and controls", async ({ page }) => {
    const errors = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/code/ready/strike-a-match.html", { waitUntil: "domcontentloaded" });
    await page.evaluate(() => localStorage.setItem("strike-match-seen-help", "1"));
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle", { timeout: 5000 }).catch(() => {});

    // Title & header visible
    await expect(page.locator("h1")).toContainText(/Strike a Match/i);

    // Canvas is present and sized
    const canvas = page.locator("#game");
    await expect(canvas).toBeVisible();
    const box = await canvas.boundingBox();
    expect(box).not.toBeNull();
    expect(box.width).toBeGreaterThan(50);
    expect(box.height).toBeGreaterThan(50);

    // HUD reads level 1 of N
    await expect(page.locator("#statLevel")).toContainText("1/");

    // Control buttons present
    await expect(page.locator("#btnRestart")).toBeVisible();
    await expect(page.locator("#btnNext")).toBeVisible();
    await expect(page.locator("#btnPrev")).toBeVisible();
    await expect(page.locator("#btnHint")).toBeVisible();
    await expect(page.locator("#btnHelp")).toBeVisible();

    expect(errors, `uncaught errors: ${errors.join("\n")}`).toHaveLength(0);
  });

  test("Help (?) button opens and closes overlay", async ({ page }) => {
    await page.goto("/code/ready/strike-a-match.html", { waitUntil: "domcontentloaded" });
    await page.evaluate(() => localStorage.setItem("strike-match-seen-help", "1"));
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForTimeout(200);

    const overlay = page.locator("#helpOverlay");
    await expect(overlay).toBeHidden();
    await page.locator("#btnHelp").click();
    await expect(overlay).toBeVisible();
    await expect(overlay).toContainText(/How to Play/i);
    await page.locator("#btnHelpClose").click();
    await expect(overlay).toBeHidden();
  });

  test("removing a stick updates HUD counter", async ({ page }) => {
    await page.goto("/code/ready/strike-a-match.html", { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle", { timeout: 5000 }).catch(() => {});

    // Reset any persisted level from prior runs
    await page.evaluate(() => {
      localStorage.removeItem("strike-match-level");
      localStorage.setItem("strike-match-seen-help", "1");
    });
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForTimeout(200);

    // On L1 (2x1 grid) remove 1 stick should be possible.
    // Use keyboard: focus canvas, press space to remove the first-focused stick.
    await page.locator("#game").focus();
    // Tab through sticks a couple times — first present stick is index 0 by default.
    await expect(page.locator("#statMoves")).toContainText("0/1");
    await page.keyboard.press(" ");
    // After one removal, counter advances
    await expect(page.locator("#statMoves")).toContainText("1/1");
  });

  test("Next button advances level", async ({ page }) => {
    await page.goto("/code/ready/strike-a-match.html", { waitUntil: "domcontentloaded" });
    await page.evaluate(() => {
      localStorage.removeItem("strike-match-level");
      localStorage.setItem("strike-match-seen-help", "1");
    });
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForTimeout(200);

    await expect(page.locator("#statLevel")).toContainText("1/");
    await page.locator("#btnNext").click();
    await expect(page.locator("#statLevel")).toContainText("2/");
  });

  test("Hint button shows toast text", async ({ page }) => {
    await page.goto("/code/ready/strike-a-match.html", { waitUntil: "domcontentloaded" });
    await page.evaluate(() => {
      localStorage.removeItem("strike-match-level");
      localStorage.setItem("strike-match-seen-help", "1");
    });
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForTimeout(200);

    await page.locator("#btnHint").click();
    const toast = page.locator("#toast");
    await expect(toast).toHaveClass(/show/);
    await expect(toast).toContainText(/square/i);
  });
});
