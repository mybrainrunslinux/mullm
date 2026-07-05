import { test, expect } from '@playwright/test';
import * as path from 'path';
import * as fs from 'fs';

// Resolve the game locally so specs work on any checkout; skip when the
// game HTML is not shipped in this tree.
function gameUrl(name: string): string | null {
  const p = path.resolve(__dirname, '..', 'code', 'ready', name);
  return fs.existsSync(p) ? 'file://' + p : null;
}


test('tower — puzzle solve → stair beacon → ascend → floor advances', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (err) => errors.push('PAGEERROR: ' + err.message));
  page.on('console', (msg) => {
    if (msg.type() === 'error' && !msg.text().includes('file://')) errors.push(msg.text());
  });

  const __url = gameUrl('clockwork-tower-3d.html');
  test.skip(!__url, 'clockwork-tower-3d.html not shipped in this tree');
  await page.goto(__url! + '?test=1');
  await page.waitForTimeout(2000);

  // Click start
  await page.locator('#start-btn').click();
  await page.waitForTimeout(800);

  // Sanity: hook exposed
  const hookExists = await page.evaluate(() => !!(window as any).__towerTest);
  expect(hookExists).toBeTruthy();

  // Initial state: floor 0
  const initial = await page.evaluate(() => {
    const T = (window as any).__towerTest;
    return { floor: T.state.currentFloor, solved: [...T.state.puzzleSolved] };
  });
  console.log('Initial state:', JSON.stringify(initial));
  expect(initial.floor).toBe(0);
  expect(initial.solved[0]).toBe(false);

  // Force-solve floor 0 puzzle
  await page.evaluate(() => {
    const T = (window as any).__towerTest;
    T.state.puzzleSolved[0] = true;
    T.state.doorOpen[0] = true;
  });

  // Wait one frame for animate() to update beacon opacity
  await page.waitForTimeout(200);

  // Check beacon now glows (opacity > 0.3 for the floor 0 beacon)
  const beaconState = await page.evaluate(() => {
    const T = (window as any).__towerTest;
    const stairsInter = T.interactables.find((i: any) => i.type === 'stairs' && i.floor === 0);
    return {
      hasStairsInter: !!stairsInter,
      beaconOpacity: stairsInter?.mesh?.material?.opacity,
      beaconEmissive: stairsInter?.mesh?.material?.emissiveIntensity,
    };
  });
  console.log('Beacon state:', JSON.stringify(beaconState));
  expect(beaconState.hasStairsInter).toBeTruthy();
  expect(beaconState.beaconOpacity).toBeGreaterThan(0.25);

  // Teleport player to stair beacon (NE corner of floor 0)
  await page.evaluate(() => {
    const T = (window as any).__towerTest;
    T.playerPos.set(7, T.PLAYER_HEIGHT, -7);
  });

  // Wait a frame so proximity check picks up nearest interactable
  await page.waitForTimeout(150);

  // Now press E to trigger interact() — should ascend to floor 1
  await page.evaluate(() => {
    const T = (window as any).__towerTest;
    T.interact();
  });

  await page.waitForTimeout(300);

  const afterAscend = await page.evaluate(() => {
    const T = (window as any).__towerTest;
    return {
      floor: T.state.currentFloor,
      playerY: T.playerPos.y,
    };
  });
  console.log('After ascend:', JSON.stringify(afterAscend));
  expect(afterAscend.floor).toBe(1);
  expect(afterAscend.playerY).toBeGreaterThan(11); // FLOOR_HEIGHT=12, so floor 1 is at y>=12

  // Verify Floor 2 banner shown (floor display updated)
  const floorText = await page.locator('#floor-num').textContent();
  expect(floorText).toBe('2');

  console.log('Errors:', errors.join('\n'));
  expect(errors.length).toBe(0);
});

test('tower — showVictory function is callable and shows the win screen', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (err) => errors.push('PAGEERROR: ' + err.message));

  const __url = gameUrl('clockwork-tower-3d.html');
  test.skip(!__url, 'clockwork-tower-3d.html not shipped in this tree');
  await page.goto(__url! + '?test=1');
  await page.waitForTimeout(2000);
  await page.locator('#start-btn').click();
  await page.waitForTimeout(500);

  // Directly invoke showVictory (this is what triggers when final floor puzzle is solved)
  await page.evaluate(() => {
    const T = (window as any).__towerTest;
    T.showVictory();
  });
  await page.waitForTimeout(300);

  const victoryShown = await page.evaluate(() => {
    const overlay = document.getElementById('overlay');
    return {
      hasOverlay: !!overlay,
      visible: overlay && !overlay.classList.contains('overlay-hidden'),
      textIncludesRestored: overlay && overlay.textContent?.includes('Restored'),
      textIncludesAscended: overlay && overlay.textContent?.includes('ascended'),
    };
  });
  console.log('Victory state:', JSON.stringify(victoryShown));
  expect(victoryShown.visible).toBeTruthy();
  expect(victoryShown.textIncludesRestored).toBeTruthy();

  expect(errors.length).toBe(0);
});
