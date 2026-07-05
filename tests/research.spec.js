// @ts-check
const { test, expect } = require("@playwright/test");

const BASE = process.env.MULLM_URL || "https://127.0.0.1:8100";

test.describe("Research page", () => {
  test("Test 1: Mode toggle — Research Swarm shows #swarm-topic", async ({ page }) => {
    await page.goto(`${BASE}/research`);
    await page.waitForLoadState("domcontentloaded");

    // Initially swarm section should be hidden
    const swarmSection = page.locator("#swarm-section");
    await expect(swarmSection).toBeHidden();

    // Click Research Swarm button
    await page.click("#btn-swarm");

    // #swarm-topic inside #swarm-section should be visible
    const swarmTopic = page.locator("#swarm-topic");
    await expect(swarmTopic).toBeVisible({ timeout: 3000 });
  });

  test("Test 2: Parallel mode — #query-rows inputs are visible", async ({ page }) => {
    await page.goto(`${BASE}/research`);
    await page.waitForLoadState("domcontentloaded");

    // Click Parallel Research (should already be active, but click anyway)
    await page.click("#btn-parallel");

    // parallel-section should be visible
    const parallelSection = page.locator("#parallel-section");
    await expect(parallelSection).toBeVisible({ timeout: 3000 });

    // at least one input in query-rows should be visible
    const firstInput = page.locator("#query-rows .query-row input").first();
    await expect(firstInput).toBeVisible({ timeout: 3000 });
  });

  test("Test 3: Freshness toggle — hint text changes", async ({ page }) => {
    await page.goto(`${BASE}/research`);
    await page.waitForLoadState("domcontentloaded");

    const hint = page.locator("#freshness-hint");

    // Click Classic
    await page.click('.fresh-btn[data-val="classic"]');
    const classicText = await hint.textContent();

    // Click Balanced
    await page.click('.fresh-btn[data-val="balanced"]');
    const balancedText = await hint.textContent();

    // Click Recent
    await page.click('.fresh-btn[data-val="recent"]');
    const recentText = await hint.textContent();

    console.log(`Classic hint: "${classicText}"`);
    console.log(`Balanced hint: "${balancedText}"`);
    console.log(`Recent hint: "${recentText}"`);

    // All three should be different
    expect(classicText).not.toBe(balancedText);
    expect(balancedText).not.toBe(recentText);
    expect(classicText).not.toBe(recentText);

    // Each should have meaningful content
    expect(classicText.trim().length).toBeGreaterThan(0);
    expect(balancedText.trim().length).toBeGreaterThan(0);
    expect(recentText.trim().length).toBeGreaterThan(0);
  });

  test("Test 4: Swarm launch — at least 1 card appears in #cards-grid", async ({ page }) => {
    // 90 second timeout for this test
    test.setTimeout(120000);

    await page.goto(`${BASE}/research`);
    await page.waitForLoadState("domcontentloaded");

    // Switch to swarm mode
    await page.click("#btn-swarm");
    await expect(page.locator("#swarm-topic")).toBeVisible({ timeout: 3000 });

    // Type research topic
    await page.fill("#swarm-topic", "tardigrade extreme survival mechanisms");

    // Click Launch Research
    await page.click("#launch-btn");

    // Wait up to 90 seconds for at least 1 card (class is 'research-card')
    await expect(page.locator("#cards-grid .research-card").first()).toBeVisible({ timeout: 90000 });

    const cardCount = await page.locator("#cards-grid .research-card").count();
    console.log(`Cards appeared: ${cardCount}`);
    expect(cardCount).toBeGreaterThanOrEqual(1);
  });

  test("Test 5: Citation right-click — #cite-menu appears", async ({ page }) => {
    test.setTimeout(120000);

    await page.goto(`${BASE}/research`);
    await page.waitForLoadState("domcontentloaded");

    // Switch to swarm mode and run a quick query to get a card
    await page.click("#btn-swarm");
    await expect(page.locator("#swarm-topic")).toBeVisible({ timeout: 3000 });
    await page.fill("#swarm-topic", "tardigrade extreme survival mechanisms");
    await page.click("#launch-btn");

    // Wait for a done card with text content (has .card-result with non-empty text)
    // A done card has class 'research-card done' (not 'running')
    await expect(page.locator(".research-card.done").first()).toBeVisible({ timeout: 90000 });

    const cardResult = page.locator(".research-card.done .card-result").first();
    await expect(cardResult).toBeVisible({ timeout: 5000 });

    // Use evaluate to select text within the card-result, then dispatch contextmenu
    // The cite menu requires window.getSelection() to return non-empty text
    await page.evaluate(() => {
      const el = document.querySelector(".research-card.done .card-result");
      if (!el || !el.textContent.trim()) {
        // Inject some text if empty
        el.textContent = "Tardigrade research text for citation test.";
      }
      // Select all text in the element
      const range = document.createRange();
      range.selectNodeContents(el);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    });

    // Dispatch contextmenu event on the card result
    await cardResult.dispatchEvent("contextmenu");

    // cite-menu should appear
    const citeMenu = page.locator("#cite-menu");
    await expect(citeMenu).toBeVisible({ timeout: 3000 });

    // Verify APA/MLA/Chicago/BibTeX buttons present
    await expect(citeMenu.locator("text=APA")).toBeVisible();
    await expect(citeMenu.locator("text=MLA")).toBeVisible();
    await expect(citeMenu.locator("text=Chicago")).toBeVisible();
    await expect(citeMenu.locator("text=BibTeX")).toBeVisible();

    console.log("Cite menu appeared with all 4 format buttons");
  });

  test("Test 6: Export bar visible after run completes", async ({ page }) => {
    // Allow 150s — swarm run can take ~80s with model timeouts
    test.setTimeout(180000);

    await page.goto(`${BASE}/research`);
    await page.waitForLoadState("domcontentloaded");

    // Use "balanced" freshness to allow cache hits (faster completion)
    await page.click('.fresh-btn[data-val="balanced"]');

    // Switch to swarm mode and run
    await page.click("#btn-swarm");
    await expect(page.locator("#swarm-topic")).toBeVisible({ timeout: 3000 });
    await page.fill("#swarm-topic", "tardigrade extreme survival mechanisms");
    await page.click("#launch-btn");

    // Wait for export-bar to become visible (shown only after final SSE "done" event)
    const exportBar = page.locator("#export-bar");
    await expect(exportBar).toBeVisible({ timeout: 150000 });

    // Verify Markdown/PDF/LaTeX buttons present
    await expect(exportBar.locator("text=Markdown")).toBeVisible();
    await expect(exportBar.locator("text=PDF")).toBeVisible();
    await expect(exportBar.locator("text=LaTeX")).toBeVisible();

    console.log("Export bar visible with Markdown/PDF/LaTeX buttons");
  });
});
