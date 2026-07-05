import { test, expect } from '@playwright/test';

const BASE = process.env.MULLM_URL || 'https://127.0.0.1:8100';

test.use({ ignoreHTTPSErrors: true });

// ─────────────────────────────────────────────────────────────────────
// 1. clean-the-garage: every level completable; toolbox picks up cleanly
// ─────────────────────────────────────────────────────────────────────
test('garage: level 1 fully completable (tire then toolbox)', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(`${BASE}/code/ready/clean-the-garage.html`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);

  const result = await page.evaluate(async () => {
    const G: any = (window as any).GAME;
    const tire = G.state.items.find((i: any) => i.id === 'tire');
    G.pickUp(tire);
    await new Promise(r => setTimeout(r, 1000));
    const toolbox = G.state.items.find((i: any) => i.id === 'toolbox');
    G.pickUp(toolbox);
    await new Promise(r => setTimeout(r, 800));
    return {
      picked: G.state.picked,
      win: G.state.win,
      level: G.state.levelIdx
    };
  });
  expect(result.picked).toEqual(['tire','toolbox']);
  expect(result.win).toBe(true);
  expect(errors.filter(e => !e.includes('favicon'))).toHaveLength(0);
});

test('garage: level 15 has tall stacks (taller than 0.45)', async ({ page }) => {
  await page.goto(`${BASE}/code/ready/clean-the-garage.html`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);
  const heights = await page.evaluate(() => {
    const G: any = (window as any).GAME;
    const lvl = G.LEVELS.find((l: any) => l.n === 15);
    if (!lvl) return [];
    return lvl.items.map((it: any) => it.stackH || 0);
  });
  const maxH = Math.max(...heights);
  expect(maxH).toBeGreaterThan(0.45); // taller than a single pair stack
});

test('garage: every level 1-100 is completable (all stacks resolvable in declared order)', async ({ page }) => {
  await page.goto(`${BASE}/code/ready/clean-the-garage.html`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);
  const result = await page.evaluate(() => {
    const G: any = (window as any).GAME;
    const failures: any[] = [];
    for (let i = 0; i < G.LEVELS.length; i++) {
      const lvl = G.LEVELS[i];
      // Simulate picking in declared order; ensure no item is blocked when we reach it.
      const picked = new Set<string>();
      // alive map: id -> placement (allow lookup)
      const alive = new Map<string, any>();
      lvl.items.forEach((p: any) => alive.set(p.id, p));
      let ok = true;
      let failureReason = '';
      for (const targetId of lvl.order) {
        const me = alive.get(targetId);
        if (!me) { ok = false; failureReason = `item ${targetId} not in placements`; break; }
        // simulate isItemBlocked: same x/z within 0.3, higher stackH still alive
        for (const [otherId, other] of alive) {
          if (otherId === targetId) continue;
          if (Math.abs(other.x - me.x) < 0.3 && Math.abs(other.z - me.z) < 0.3) {
            if ((other.stackH || 0) > (me.stackH || 0) + 0.05) {
              ok = false;
              failureReason = `${targetId} blocked by ${otherId} (stackH ${other.stackH} > ${me.stackH})`;
              break;
            }
          }
        }
        if (!ok) break;
        picked.add(targetId);
        alive.delete(targetId);
      }
      if (!ok) failures.push({ level: lvl.n, reason: failureReason, order: lvl.order });
    }
    return { failures, totalLevels: G.LEVELS.length };
  });
  if (result.failures.length > 0) {
    console.log('UNCOMPLETABLE LEVELS:', JSON.stringify(result.failures.slice(0, 5), null, 2));
  }
  expect(result.failures).toHaveLength(0);
  expect(result.totalLevels).toBeGreaterThanOrEqual(100);
});

// ─────────────────────────────────────────────────────────────────────
// 2. zipper-merge: difficulty selector + speed
// ─────────────────────────────────────────────────────────────────────
test('zipper: has difficulty selector with three buttons defaulting to Normal', async ({ page }) => {
  await page.goto(`${BASE}/code/ready/zipper-merge.html`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  // Clear any saved preference for reliable default check
  await page.evaluate(() => { try { localStorage.removeItem('zipper-diff'); } catch(_) {} });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);

  const easy = page.locator('#diff-easy');
  const normal = page.locator('#diff-normal');
  const hard = page.locator('#diff-hard');
  await expect(easy).toBeVisible();
  await expect(normal).toBeVisible();
  await expect(hard).toBeVisible();
  await expect(normal).toHaveAttribute('aria-pressed', 'true');
  await expect(easy).toHaveAttribute('aria-pressed', 'false');
  await expect(hard).toHaveAttribute('aria-pressed', 'false');
});

test('zipper: Easy speed is well below Hard speed', async ({ page }) => {
  await page.goto(`${BASE}/code/ready/zipper-merge.html`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  const ratio = await page.evaluate(() => {
    const D = (window as any).DIFFICULTY;
    return D ? (D.easy.speed / D.hard.speed) : null;
  });
  expect(ratio).not.toBeNull();
  // Easy should be 0.4-0.6x of Normal; Hard ≥ Normal. So Easy/Hard ≤ ~0.65.
  expect(ratio!).toBeLessThanOrEqual(0.65);
  expect(ratio!).toBeGreaterThan(0.3);
});

test('zipper: Hard mode label says HARD MODE', async ({ page }) => {
  await page.goto(`${BASE}/code/ready/zipper-merge.html`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await page.click('#diff-hard');
  await page.waitForTimeout(200);
  const label = await page.locator('#modeLabel').textContent();
  expect(label).toMatch(/HARD/i);
});

// ─────────────────────────────────────────────────────────────────────
// 3. pole-position: car never goes below road surface
// ─────────────────────────────────────────────────────────────────────
test('pole-position: car stays at or above road surface across many positions', async ({ page }) => {
  page.on('pageerror', e => console.log('pageerror:', e.message));
  await page.goto(`${BASE}/code/ready/pole-position.html`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);

  const result = await page.evaluate(() => {
    // Try to start a race so playerState exists
    if (typeof (window as any).startRace === 'function') {
      try { (window as any).startRace(((window as any).GAME && (window as any).GAME.track) || 'desert'); } catch(_) {}
    }
    if (!(window as any).playerState) {
      (window as any).playerState = { x: 0, z: 0, speed: 100, steer: 0 };
    }
    const ps = (window as any).playerState;
    const samples: any[] = [];
    // sample many z positions around the track
    for (let i = 0; i < 50; i++) {
      ps.z = i * 50;
      if (typeof (window as any).updatePlayerCarTransform === 'function') {
        (window as any).updatePlayerCarTransform();
      }
      const roadY = (typeof (window as any).getRoadSurfaceY === 'function')
        ? (window as any).getRoadSurfaceY() : 0;
      const car = (window as any).playerCar;
      samples.push({
        z: ps.z,
        roadY,
        carY: car ? car.position.y : null,
        belowRoad: car ? (car.position.y < roadY - 0.01) : false
      });
    }
    return samples;
  });

  const violations = result.filter(s => s.belowRoad);
  if (violations.length > 0) {
    console.log('Violations:', JSON.stringify(violations.slice(0, 5)));
  }
  expect(violations).toHaveLength(0);
});
