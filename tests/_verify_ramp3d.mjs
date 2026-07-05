import { chromium } from 'playwright';
const URL = 'https://127.0.0.1:8100/code/ready/rampartillery-3d.html';
(async()=>{
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ ignoreHTTPSErrors:true, viewport:{width:1200,height:800} });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(`PAGEERROR: ${e.message}`));
  page.on('console', m=>{ if (m.type()==='error') errors.push(`CONERR: ${m.text()}`); });

  await page.goto(URL, { waitUntil:'domcontentloaded' });
  await page.waitForTimeout(1500);
  await page.click('#start-btn');
  await page.waitForTimeout(400);

  // ─── TEST 1: Ballista GLB actually loads ───
  console.log('=== TEST 1: Ballista GLB load ===');
  await page.locator('.wc').nth(0).click();
  await page.waitForTimeout(400);
  await page.locator('.lb').first().click();
  // wait for loader to disappear (GLB loaded successfully) or timeout
  try{
    await page.waitForSelector('#loader', { state:'hidden', timeout:30000 });
    console.log('  Loader hidden — GLB loaded OR fallback triggered');
  }catch(e){ console.log('  Loader still visible after 30s'); }
  await page.waitForTimeout(800);
  // Check: if the GLB loaded, there should be no console error for ballista.glb
  const ballistaErrs = errors.filter(e => e.includes('ballista.glb'));
  console.log('  Ballista GLB errors:', ballistaErrs.length, ballistaErrs[0] || '');

  // Inspect weaponGroup — is currentWeaponMeta.isFallback?
  const isFallback = await page.evaluate(()=>{
    // Try to sniff via the scene — count meshes under weaponGroup
    // Not accessible — but we can check if #loader is hidden and no errors
    return null;
  });

  await page.screenshot({ path:'/tmp/r3d-ballista-live.png', fullPage:false });
  // Fire a shot
  const canvas = await page.locator('#gl');
  const box = await canvas.boundingBox();
  const cx = box.x + box.width/2, cy = box.y + box.height/2;
  await page.mouse.move(cx, cy); await page.mouse.down();
  await page.mouse.move(cx - 22, cy + 185, { steps:10 });
  await page.mouse.up();
  await page.waitForTimeout(3500);
  await page.mouse.move(cx, cy); await page.mouse.down();
  await page.mouse.move(cx + 22, cy + 185, { steps:10 });
  await page.mouse.up();
  await page.waitForTimeout(4500);
  const endVis = await page.isVisible('#end-screen');
  console.log('  Ballista L1 won?', endVis);

  // ─── TEST 2: Ballista L4 (hp=2 chains, multi-hit) ───
  console.log('=== TEST 2: Ballista L4 (multi-hit hp=2) ===');
  if (endVis){ await page.click('#end-levels'); await page.waitForTimeout(300); }
  // Unlock L4: we need prior levels clear. Enable debug unlock
  await page.evaluate(()=>{
    const s = JSON.parse(localStorage.getItem('ramp3d_prog_v1')||'{}');
    s.debug = true; localStorage.setItem('ramp3d_prog_v1', JSON.stringify(s));
  });
  await page.reload();
  await page.waitForTimeout(1000);
  await page.click('#start-btn'); await page.waitForTimeout(300);
  await page.locator('.wc').nth(0).click(); await page.waitForTimeout(300);
  await page.locator('.lb').nth(3).click();  // L4
  await page.waitForSelector('#loader', { state:'hidden', timeout:30000 });
  await page.waitForTimeout(800);
  // L4: 2 chains hp=2 each, par=4, shots=7
  // Fire 4 shots (2 per chain): left, left, right, right
  for (let i=0;i<5;i++){
    const dragX = i<2 ? -24 : 24;
    await page.mouse.move(cx, cy); await page.mouse.down();
    await page.mouse.move(cx + dragX, cy + 180, { steps:10 });
    await page.mouse.up();
    await page.waitForTimeout(3500);
    const chainsChip = await page.locator('#chains-chip').innerText();
    console.log(`  L4 fire ${i+1}: ${chainsChip}`);
    if (await page.isVisible('#end-screen')){
      const title = await page.locator('#end-title').innerText();
      console.log(`  L4 result: ${title}`);
      break;
    }
  }

  // ─── TEST 3: Catapult winding flow ───
  console.log('=== TEST 3: Catapult winding ===');
  await page.evaluate(()=>{
    const s = JSON.parse(localStorage.getItem('ramp3d_prog_v1')||'{}');
    s.debug = true; localStorage.setItem('ramp3d_prog_v1', JSON.stringify(s));
  });
  await page.reload();
  await page.waitForTimeout(1000);
  await page.click('#start-btn'); await page.waitForTimeout(300);
  await page.locator('.wc').nth(1).click(); // CATAPULT
  await page.waitForTimeout(300);
  await page.locator('.lb').first().click(); // L1
  await page.waitForSelector('#loader', { state:'hidden', timeout:30000 });
  await page.waitForTimeout(800);
  // Tap 3 times to wind (pointerDown+Up, no drag)
  for (let i=0;i<3;i++){
    await page.mouse.move(cx, cy);
    await page.mouse.down();
    await page.mouse.up();
    await page.waitForTimeout(200);
  }
  // Now drag to fire
  await page.mouse.move(cx, cy); await page.mouse.down();
  await page.mouse.move(cx, cy + 190, { steps:10 });
  await page.mouse.up();
  await page.waitForTimeout(4500);
  const catChains = await page.locator('#chains-chip').innerText();
  const catShots = await page.locator('#shots-chip').innerText();
  console.log(`  Catapult L1 after 3 winds + 1 fire: ${catShots} | ${catChains}`);

  // ─── TEST 4: Trebuchet (big GLB) ───
  console.log('=== TEST 4: Trebuchet (40MB GLB) ===');
  // Back to menu
  if (await page.isVisible('#end-screen')) await page.click('#end-levels');
  else await page.click('#back-btn');
  await page.waitForTimeout(500);
  await page.locator('.wc').nth(2).click(); // TREBUCHET
  await page.waitForTimeout(300);
  await page.locator('.lb').first().click();
  const trebStart = Date.now();
  try{
    await page.waitForSelector('#loader', { state:'hidden', timeout:45000 });
    console.log(`  Trebuchet loaded in ${Date.now()-trebStart}ms`);
  }catch(e){ console.log(`  Trebuchet NOT loaded after 45s`); }
  await page.waitForTimeout(800);
  const trebErrs = errors.filter(e=>e.includes('trebuchet.glb'));
  console.log(`  Trebuchet GLB errors: ${trebErrs.length}`);
  await page.screenshot({ path:'/tmp/r3d-trebuchet.png' });

  console.log('\n=== SUMMARY ===');
  console.log('Total errors:', errors.length);
  errors.slice(0,10).forEach(e=>console.log(' ', e.slice(0,200)));
  await browser.close();
})().catch(e=>{ console.error('FATAL', e); process.exit(1); });
