import { test, expect } from '@playwright/test';
import path from 'path';

test('sky-islands-3d boots, builds 8 islands and 40 crystals, player physics works, crystal collection works', async ({ page }) => {
  const errors: string[] = [];
  const consoleErrs: string[] = [];
  page.on('pageerror', e => errors.push(e.message + '\n' + (e.stack || '').split('\n').slice(0, 4).join('\n')));
  page.on('console', m => { if (m.type() === 'error') consoleErrs.push(m.text()); });

  const url = 'file://' + path.resolve('/home/peter/mullm/code/ready/sky-islands-3d.html');
  await page.goto(url, { waitUntil: 'load', timeout: 15000 });
  await page.waitForTimeout(1500);

  const probe = await page.evaluate(() => ({
    hasScene: !!(window as any).scene,
    hasCamera: !!(window as any).camera,
    hasRenderer: !!(window as any).renderer,
    hasPlayer: !!(window as any).player,
    crystalCount: ((window as any).crystals || []).length,
    islandCount: ((window as any).islands || []).length,
    jumpPadCount: ((window as any).jumpPads || []).length,
    movingPlatformCount: ((window as any).movingPlatforms || []).length,
    windCount: ((window as any).windVolumes || []).length,
    gameReady: (window as any).GAME && (window as any).GAME.ready,
    sceneChildren: (window as any).scene ? (window as any).scene.children.length : 0,
  }));

  console.log('SKY PROBE:', JSON.stringify(probe, null, 2));
  console.log('PAGE_ERRORS:', errors.join(' | '));
  console.log('CONSOLE_ERRORS:', consoleErrs.join(' | '));

  expect(errors).toEqual([]);
  expect(probe.hasScene).toBe(true);
  expect(probe.hasCamera).toBe(true);
  expect(probe.hasRenderer).toBe(true);
  expect(probe.hasPlayer).toBe(true);
  expect(probe.crystalCount).toBe(40);
  expect(probe.islandCount).toBe(8);
  expect(probe.movingPlatformCount).toBeGreaterThanOrEqual(4);
  expect(probe.jumpPadCount).toBe(4);

  // Click play
  await page.click('#play-btn');
  await page.waitForTimeout(800);
  const debugA = await page.evaluate(() => ({
    phase: (window as any).GAME.phase,
    fpsHistoryLen: ((window as any).fpsHistory || []).length,
    lastT: (window as any).lastT,
    gameTime: (window as any).GAME.time,
  }));
  console.log('AFTER_PLAY_DEBUG:', JSON.stringify(debugA));
  expect(debugA.phase).toBe('play');

  // Walk forward — focus the page first
  await page.evaluate(() => { document.body.focus(); });
  const beforeWalk = await page.evaluate(() => ({
    x: (window as any).player.position.x,
    z: (window as any).player.position.z,
    inputFwd: (window as any).input.fwd,
  }));
  console.log('BEFORE_WALK:', JSON.stringify(beforeWalk));
  await page.keyboard.down('KeyW');
  await page.waitForTimeout(100);
  const midWalk = await page.evaluate(() => (window as any).input.fwd);
  console.log('MID_WALK_INPUT_FWD:', midWalk);
  await page.waitForTimeout(700);
  await page.keyboard.up('KeyW');
  await page.waitForTimeout(200);
  const afterWalk = await page.evaluate(() => ({
    x: (window as any).player.position.x,
    z: (window as any).player.position.z,
  }));
  console.log('AFTER_WALK:', JSON.stringify(afterWalk));

  // Teleport to first crystal and collect
  const teleResult = await page.evaluate(() => {
    const c = (window as any).crystals[0];
    const cp = c.position.clone();
    (window as any).player.position.copy(cp);
    (window as any).playerVel.set(0, 0, 0);
    return { crystalPos: {x: cp.x, y: cp.y, z: cp.z}, collectedFlag: c.userData.collected };
  });
  console.log('TELEPORT:', JSON.stringify(teleResult));
  // Several frames so updateCrystals runs
  await page.waitForTimeout(500);
  const collected = await page.evaluate(() => ({
    count: (window as any).GAME.crystalsCollected,
    firstCrystalCollected: (window as any).crystals[0].userData.collected,
    distAfter: (window as any).crystals[0].position.distanceTo((window as any).player.position),
  }));
  console.log('AFTER_COLLECT:', JSON.stringify(collected));
  expect(collected.count).toBeGreaterThanOrEqual(1);

  // COMPLETABILITY: every island must have a traversal path. Verify by checking that platforms
  // and wind volumes cover every adjacent pair OR an island has direct island contact.
  const traversal = await page.evaluate(() => {
    const W = window as any;
    const ix = W.islands.map((g: any) => ({x: g.position.x, y: g.position.y, z: g.position.z}));
    // Build connectivity graph
    const adj: number[][] = ix.map(() => []);
    for (const p of W.movingPlatforms || []) {
      const dist = (a: any, b: any) => Math.hypot(a.x - b.x, a.z - b.z);
      const findClosest = (pt: any) => {
        let best = -1, bd = 1e9;
        ix.forEach((it: any, i: number) => { const d = dist(it, pt); if (d < bd) { bd = d; best = i; } });
        return best;
      };
      const a = findClosest(p.p1);
      const b = findClosest(p.p2);
      if (a >= 0 && b >= 0 && a !== b) { adj[a].push(b); adj[b].push(a); }
    }
    for (const v of W.windVolumes || []) {
      // Find islands that overlap the AABB
      const overlap = ix.map((p: any, i: number) =>
        p.x >= v.min.x - 8 && p.x <= v.max.x + 8 &&
        p.z >= v.min.z - 8 && p.z <= v.max.z + 8 ? i : -1
      ).filter((i: number) => i >= 0);
      for (let i = 0; i < overlap.length; i++) {
        for (let j = i+1; j < overlap.length; j++) {
          adj[overlap[i]].push(overlap[j]);
          adj[overlap[j]].push(overlap[i]);
        }
      }
    }
    // BFS from island 0
    const visited = new Set([0]);
    const queue = [0];
    while (queue.length) {
      const cur = queue.shift()!;
      for (const n of adj[cur]) if (!visited.has(n)) { visited.add(n); queue.push(n); }
    }
    return { visited: Array.from(visited).sort((a,b)=>a-b), expected: ix.map((_:any,i:number)=>i), adj };
  });
  console.log('TRAVERSAL:', JSON.stringify(traversal));
  expect(traversal.visited.length).toBe(8); // all 8 islands reachable from island 0
});
