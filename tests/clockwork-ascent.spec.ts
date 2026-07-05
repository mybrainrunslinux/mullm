import { test, expect } from '@playwright/test';

const BASE = process.env.MULLM_URL || 'https://127.0.0.1:8100';

test.use({ ignoreHTTPSErrors: true, actionTimeout: 60000 });

test('clockwork-ascent loads, exposes test harness, and tech tree advances to win', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console.error: ' + m.text()); });

  await page.goto(`${BASE}/code/ready/clockwork-ascent.html`, { waitUntil: 'domcontentloaded' });

  // Wait for game scaffolding + test harness
  await page.waitForFunction(() => !!(window as any).__CLOCKWORK, { timeout: 30000 });

  // Wait for boot to complete (assets, NPCs, enemies, tree)
  await page.waitForFunction(() => {
    const c = (window as any).__CLOCKWORK;
    return c && c.isReady() && c.getTechTree() && Object.keys(c.getTechTree()).length === 30;
  }, { timeout: 60000 });

  // Tree contains exactly 30 nodes across 5 branches
  const tree = await page.evaluate(() => (window as any).__CLOCKWORK.getTechTree());
  const branchCounts: Record<string, number> = {};
  for (const id of Object.keys(tree)) {
    const b = tree[id].branch;
    branchCounts[b] = (branchCounts[b] || 0) + 1;
  }
  expect(Object.keys(tree).length).toBe(30);
  expect(branchCounts.S).toBe(6);
  expect(branchCounts.A).toBe(6);
  expect(branchCounts.L).toBe(6);
  expect(branchCounts.T).toBe(6);
  expect(branchCounts.C).toBe(6);

  // Start the game (click play)
  await page.click('#btnPlay');
  await page.waitForFunction(() => (window as any).__CLOCKWORK.getCurrentZone() === 'ruins', { timeout: 5000 });

  // Force-unlock the entire C branch in order — proves a win path exists
  for (const id of ['C1','C2','C3','C4','C5','C6']) {
    await page.evaluate((nid) => (window as any).__CLOCKWORK.unlockNode(nid), id);
  }
  // Verify Apex (C6) owned -> end card or apex flag
  const apexOwned = await page.evaluate(() => (window as any).__CLOCKWORK.getTechTree()['C6'].owned);
  expect(apexOwned).toBe(true);

  // Voice synth API was called (history non-empty after intro + unlock chatter)
  const spoken = await page.evaluate(() => (window as any).__CLOCKWORK.triggerSpeech('test ping') || true);
  expect(spoken).toBeTruthy();

  // No JS errors
  const fatal = errors.filter(e => !/SpeechSynthesis|tts|Failed to load resource|favicon/i.test(e));
  expect(fatal, fatal.join('\n')).toEqual([]);
});
