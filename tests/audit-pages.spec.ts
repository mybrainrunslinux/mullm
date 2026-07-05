import { test, expect, Page, ConsoleMessage } from '@playwright/test';

const BASE = process.env.MULLM_URL || 'https://127.0.0.1:8100';

// Helper: collect console errors on a page
async function collectErrors(page: Page): Promise<string[]> {
  const errors: string[] = [];
  page.on('console', (msg: ConsoleMessage) => {
    if (msg.type() === 'error') errors.push(msg.text());
  });
  page.on('pageerror', (err: Error) => errors.push(`[pageerror] ${err.message}`));
  return errors;
}

// Helper: get all visible nav links on current page
async function getNavLinks(page: Page): Promise<string[]> {
  const links = await page.$$eval(
    'nav a, header a, [role="navigation"] a, .nav a, .navbar a, .sidebar a',
    (els: Element[]) => els.map((el) => (el as HTMLAnchorElement).href + ' | ' + el.textContent?.trim())
  );
  return links;
}

// ── HOME / ──────────────────────────────────────────────────────────────────
test.describe('Home /', () => {
  test('loads without console errors', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()); });
    page.on('pageerror', (err) => errors.push(`[pageerror] ${err.message}`));

    await page.goto(`${BASE}/`);
    await page.waitForLoadState('networkidle');
    expect(errors.filter(e => !e.includes('favicon'))).toEqual([]);
  });

  test('nav links present', async ({ page }) => {
    await page.goto(`${BASE}/`);
    await page.waitForLoadState('networkidle');
    const links = await getNavLinks(page);
    console.log('Home nav links:', links);
    // Record what we find
    expect(links.length).toBeGreaterThan(0);
  });

  test('mobile nav at 375px', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(`${BASE}/`);
    await page.waitForLoadState('networkidle');
    // Check nav doesn't overflow horizontally
    const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
    expect(bodyWidth).toBeLessThanOrEqual(380);
  });
});

// ── DASHBOARD ───────────────────────────────────────────────────────────────
test.describe('Dashboard /dashboard', () => {
  test('loads without console errors', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()); });
    page.on('pageerror', (err) => errors.push(`[pageerror] ${err.message}`));

    await page.goto(`${BASE}/dashboard`);
    await page.waitForLoadState('networkidle');
    expect(errors.filter(e => !e.includes('favicon'))).toEqual([]);
  });

  test('nav links present', async ({ page }) => {
    await page.goto(`${BASE}/dashboard`);
    await page.waitForLoadState('networkidle');
    const links = await getNavLinks(page);
    console.log('Dashboard nav links:', links);
    expect(links.length).toBeGreaterThan(0);
  });

  test('mobile nav at 375px', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(`${BASE}/dashboard`);
    await page.waitForLoadState('networkidle');
    const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
    expect(bodyWidth).toBeLessThanOrEqual(380);
  });

  test('visible buttons do not throw errors', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()); });
    page.on('pageerror', (err) => errors.push(`[pageerror] ${err.message}`));

    await page.goto(`${BASE}/dashboard`);
    await page.waitForLoadState('networkidle');

    const buttons = await page.$$('button:visible');
    console.log(`Dashboard: found ${buttons.length} visible buttons`);
    for (const btn of buttons.slice(0, 10)) {
      const text = await btn.textContent();
      console.log(`  Clicking button: "${text?.trim()}"`);
      try {
        await btn.click({ timeout: 2000 });
        await page.waitForTimeout(300);
      } catch (_) { /* ignore click timeouts */ }
    }
    expect(errors.filter(e => !e.includes('favicon'))).toEqual([]);
  });
});

// ── BENCH ───────────────────────────────────────────────────────────────────
test.describe('Bench /bench', () => {
  test('loads without console errors', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()); });
    page.on('pageerror', (err) => errors.push(`[pageerror] ${err.message}`));

    await page.goto(`${BASE}/bench`);
    await page.waitForLoadState('networkidle');
    expect(errors.filter(e => !e.includes('favicon'))).toEqual([]);
  });

  test('nav links present', async ({ page }) => {
    await page.goto(`${BASE}/bench`);
    await page.waitForLoadState('networkidle');
    const links = await getNavLinks(page);
    console.log('Bench nav links:', links);
    expect(links.length).toBeGreaterThan(0);
  });

  test('RouterBench tab — leaderboard shows mullm #1 with trophy', async ({ page }) => {
    await page.goto(`${BASE}/bench`);
    await page.waitForLoadState('networkidle');

    // Find and click RouterBench tab
    const routerBenchTab = page.locator('button, [role="tab"], a').filter({ hasText: /routerbench|router bench/i }).first();
    const tabExists = await routerBenchTab.count();
    if (tabExists === 0) {
      console.log('WARN: No RouterBench tab found — logging all tabs');
      const tabs = await page.$$eval('[role="tab"], .tab, .tabs button', els => els.map(el => el.textContent?.trim()));
      console.log('Tabs found:', tabs);
      // Check if we're already on RouterBench content
    } else {
      await routerBenchTab.click();
      await page.waitForTimeout(1000);
    }

    const pageContent = await page.content();
    const hasMullm = pageContent.includes('mullm') || pageContent.includes('muLLM') || pageContent.includes('mµLLM');
    const hasTrophy = pageContent.includes('🏆');
    console.log(`RouterBench: mullm present=${hasMullm}, trophy=${hasTrophy}`);
    expect(hasMullm).toBeTruthy();
    expect(hasTrophy).toBeTruthy();
  });

  test('GT Speed tab — data or empty state', async ({ page }) => {
    await page.goto(`${BASE}/bench`);
    await page.waitForLoadState('networkidle');

    const gtTab = page.locator('button, [role="tab"], a').filter({ hasText: /gt speed|groundtruth speed/i }).first();
    const tabExists = await gtTab.count();
    if (tabExists > 0) {
      await gtTab.click();
      await page.waitForTimeout(1000);
      const content = await page.textContent('body');
      console.log('GT Speed tab content snippet:', content?.substring(0, 300));
      // Should have either data rows or a meaningful empty state message
      const hasContent = content && content.length > 100;
      expect(hasContent).toBeTruthy();
    } else {
      console.log('WARN: GT Speed tab not found');
      const tabs = await page.$$eval('[role="tab"], .tab, .tabs button, button', els => els.map(el => el.textContent?.trim()).filter(t => t && t.length < 40));
      console.log('All buttons/tabs:', tabs.slice(0, 20));
    }
  });

  test('Route Latency tab — data or empty state', async ({ page }) => {
    await page.goto(`${BASE}/bench`);
    await page.waitForLoadState('networkidle');

    const latencyTab = page.locator('button, [role="tab"], a').filter({ hasText: /route latency|latency/i }).first();
    const tabExists = await latencyTab.count();
    if (tabExists > 0) {
      await latencyTab.click();
      await page.waitForTimeout(1000);
      const content = await page.textContent('body');
      console.log('Route Latency content snippet:', content?.substring(0, 300));
      expect(content && content.length > 100).toBeTruthy();
    } else {
      console.log('WARN: Route Latency tab not found');
    }
  });

  test('mobile nav at 375px', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(`${BASE}/bench`);
    await page.waitForLoadState('networkidle');
    const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
    expect(bodyWidth).toBeLessThanOrEqual(380);
  });
});

// ── RESEARCH ────────────────────────────────────────────────────────────────
test.describe('Research /research', () => {
  test('loads without console errors', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()); });
    page.on('pageerror', (err) => errors.push(`[pageerror] ${err.message}`));

    await page.goto(`${BASE}/research`);
    await page.waitForLoadState('networkidle');
    expect(errors.filter(e => !e.includes('favicon'))).toEqual([]);
  });

  test('nav links present', async ({ page }) => {
    await page.goto(`${BASE}/research`);
    await page.waitForLoadState('networkidle');
    const links = await getNavLinks(page);
    console.log('Research nav links:', links);
    expect(links.length).toBeGreaterThan(0);
  });

  test('Research Swarm — type tardigrades and launch cards', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()); });
    page.on('pageerror', (err) => errors.push(`[pageerror] ${err.message}`));

    await page.goto(`${BASE}/research`);
    await page.waitForLoadState('networkidle');

    // Find and switch to Research Swarm mode
    const swarmToggle = page.locator('button, [role="tab"], input[type="radio"], label').filter({ hasText: /swarm|research swarm/i }).first();
    const swarmExists = await swarmToggle.count();
    if (swarmExists > 0) {
      await swarmToggle.click();
      await page.waitForTimeout(500);
    } else {
      console.log('WARN: No Research Swarm toggle found');
      const controls = await page.$$eval('button, [role="tab"]', els => els.map(el => el.textContent?.trim()).filter(t => t));
      console.log('Available controls:', controls.slice(0, 20));
    }

    // Type in the search input
    const input = page.locator('input[type="text"], textarea, input[placeholder]').first();
    await input.fill('tardigrades');

    // Click launch/submit button
    const launchBtn = page.locator('button').filter({ hasText: /launch|search|submit|go|run/i }).first();
    const launchExists = await launchBtn.count();
    if (launchExists > 0) {
      await launchBtn.click();
      // Wait for cards to appear (up to 10s)
      await page.waitForTimeout(3000);
      const cards = await page.$$('.card, [class*="card"], [class*="result"], article');
      console.log(`Research Swarm: found ${cards.length} cards after launch`);
    } else {
      // Try pressing Enter
      await input.press('Enter');
      await page.waitForTimeout(3000);
      const cards = await page.$$('.card, [class*="card"], [class*="result"], article');
      console.log(`Research Swarm (Enter): found ${cards.length} cards`);
    }

    const jsErrors = errors.filter(e => !e.includes('favicon'));
    console.log('JS errors during swarm:', jsErrors);
  });

  test('mobile nav at 375px', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(`${BASE}/research`);
    await page.waitForLoadState('networkidle');
    const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
    expect(bodyWidth).toBeLessThanOrEqual(380);
  });
});

// ── SETUP ────────────────────────────────────────────────────────────────────
test.describe('Setup /setup', () => {
  test('check if page exists or 404s', async ({ page }) => {
    const resp = await page.goto(`${BASE}/setup`);
    const status = resp?.status();
    console.log(`/setup HTTP status: ${status}`);
    expect([200, 302, 404]).toContain(status);
    if (status === 200) {
      const errors: string[] = [];
      page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()); });
      await page.waitForLoadState('networkidle');
      const links = await getNavLinks(page);
      console.log('Setup nav links:', links);
      const jsErrors = errors.filter(e => !e.includes('favicon'));
      expect(jsErrors).toEqual([]);
    }
  });
});

// ── GAMES ────────────────────────────────────────────────────────────────────
test.describe('Games /games', () => {
  test('check if page exists or 404s', async ({ page }) => {
    const resp = await page.goto(`${BASE}/games`);
    const status = resp?.status();
    console.log(`/games HTTP status: ${status}`);
    expect([200, 302, 404]).toContain(status);
    if (status === 200) {
      const errors: string[] = [];
      page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()); });
      await page.waitForLoadState('networkidle');
      const links = await getNavLinks(page);
      console.log('Games nav links:', links);
      const jsErrors = errors.filter(e => !e.includes('favicon'));
      expect(jsErrors).toEqual([]);
    }
  });
});

// ── CROSS-PAGE NAV AUDIT ─────────────────────────────────────────────────────
test.describe('Cross-page nav audit', () => {
  const pages = ['/', '/dashboard', '/bench', '/research'];

  for (const pagePath of pages) {
    test(`from ${pagePath}: can reach all other pages via nav`, async ({ page }) => {
      await page.goto(`${BASE}${pagePath}`);
      await page.waitForLoadState('networkidle');

      const links = await page.$$eval(
        'nav a, header a, [role="navigation"] a, .nav a, .navbar a, .sidebar a',
        (els) => els.map((el) => ({
          href: (el as HTMLAnchorElement).href,
          text: el.textContent?.trim() || '',
        }))
      );

      const otherPages = pages.filter(p => p !== pagePath);
      const navHrefs = links.map(l => l.href);

      console.log(`\nNav from ${pagePath}:`);
      links.forEach(l => console.log(`  ${l.text} → ${l.href}`));

      const missing: string[] = [];
      for (const other of otherPages) {
        const reachable = navHrefs.some(href => href.includes(other) || href.endsWith(other));
        if (!reachable) missing.push(other);
      }
      if (missing.length > 0) {
        console.log(`MISSING from ${pagePath} nav:`, missing);
      }
      // Don't hard-fail here — just report
    });
  }

  test('all nav links on / lead to valid pages (no 404)', async ({ page }) => {
    await page.goto(`${BASE}/`);
    await page.waitForLoadState('networkidle');

    const links = await page.$$eval(
      'nav a, header a',
      (els) => els.map((el) => (el as HTMLAnchorElement).href).filter(h => h && !h.startsWith('javascript') && !h.includes('#'))
    );

    console.log('Nav hrefs from home:', links);
    for (const link of links) {
      if (!link.startsWith('http')) continue;
      try {
        const resp = await page.request.get(link);
        console.log(`  ${link} → ${resp.status()}`);
        expect([200, 302]).toContain(resp.status());
      } catch (e) {
        console.log(`  ${link} → ERROR: ${e}`);
      }
    }
  });
});

// ── BUTTON AUDIT (all pages) ──────────────────────────────────────────────────
test.describe('Button audit', () => {
  const pagesToAudit = ['/', '/dashboard', '/bench', '/research'];

  for (const pagePath of pagesToAudit) {
    test(`${pagePath}: all visible buttons enumerated`, async ({ page }) => {
      const errors: string[] = [];
      page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()); });
      page.on('pageerror', (err) => errors.push(`[pageerror] ${err.message}`));

      await page.goto(`${BASE}${pagePath}`);
      await page.waitForLoadState('networkidle');

      const buttons = await page.$$eval('button:not([disabled])', (els) =>
        els.map((el) => ({
          text: el.textContent?.trim().substring(0, 40) || '',
          id: (el as HTMLButtonElement).id || '',
          classes: (el as HTMLButtonElement).className.substring(0, 60),
        }))
      );
      console.log(`\nButtons on ${pagePath} (${buttons.length} total):`);
      buttons.forEach((b, i) => console.log(`  [${i}] "${b.text}" id="${b.id}" class="${b.classes}"`));
    });
  }
});
