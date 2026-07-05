import { chromium } from 'playwright';
const URL = 'https://127.0.0.1:8100/code/ready/rampartillery-3d.html';
(async()=>{
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ ignoreHTTPSErrors:true, viewport:{width:1280,height:800} });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(`PAGEERROR: ${e.message}`));
  page.on('console', m=>{ if (m.type()==='error') errors.push(`CONERR: ${m.text()}`); });

  async function gotoLevel(weaponIdx, levelIdx){
    await page.evaluate(()=>{
      const s = JSON.parse(localStorage.getItem('ramp3d_prog_v1')||'{}');
      s.debug = true; localStorage.setItem('ramp3d_prog_v1', JSON.stringify(s));
    });
    await page.reload(); await page.waitForTimeout(800);
    await page.click('#start-btn'); await page.waitForTimeout(300);
    await page.locator('#weapon-select .wc').nth(weaponIdx).click();
    await page.waitForTimeout(300);
    await page.locator('#level-select .lb').nth(levelIdx).click();
    await page.waitForSelector('#loader', { state:'hidden', timeout:45000 });
    await page.waitForTimeout(1000);
  }
  async function fire(yawPx, powerPx){
    const box = await page.locator('#gl').boundingBox();
    const cx = box.x + box.width/2, cy = box.y + box.height/2;
    await page.mouse.move(cx, cy); await page.mouse.down();
    await page.mouse.move(cx + yawPx, cy + powerPx, { steps:10 });
    await page.mouse.up();
    await page.waitForTimeout(3500);
  }

  await page.goto(URL, { waitUntil:'domcontentloaded' });
  await page.waitForTimeout(1500);

  // ─── TEST 1: BALLISTA GLB ───
  console.log('=== T1: BALLISTA GLB ===');
  await gotoLevel(0, 0);
  await page.screenshot({ path:'/tmp/r3d-T1-ballista.png', fullPage:false });
  let glbErr = errors.filter(e=>e.includes('ballista.glb'));
  console.log('  ballista.glb errors:', glbErr.length);

  // ─── TEST 2: BALLISTA L4 (hp=2 each chain, 2 chains) ───
  console.log('=== T2: BALLISTA L4 multi-hit ===');
  await gotoLevel(0, 3);
  // 2 chains hp=2 → need 4 ballista hits (damage=1)
  for (let i=0;i<6;i++){
    const yaw = i<3 ? -22 : 22;
    await fire(yaw, 180);
    const c = await page.locator('#chains-chip').innerText();
    const s = await page.locator('#shots-chip').innerText();
    console.log(`  fire ${i+1}: ${s} | ${c}`);
    if (await page.isVisible('#end-screen')){
      console.log('  end:', await page.locator('#end-title').innerText());
      break;
    }
  }
  await page.screenshot({ path:'/tmp/r3d-T2-multihit.png', fullPage:false });

  // ─── TEST 3: CATAPULT GLB + winding ───
  console.log('=== T3: CATAPULT GLB + winding ===');
  await gotoLevel(1, 0);
  glbErr = errors.filter(e=>e.includes('catapult.glb'));
  console.log('  catapult.glb errors:', glbErr.length);
  await page.screenshot({ path:'/tmp/r3d-T3-catapult.png', fullPage:false });
  // tap 3 times (no drag)
  const box = await page.locator('#gl').boundingBox();
  const cx = box.x + box.width/2, cy = box.y + box.height/2;
  for (let i=0;i<3;i++){
    await page.mouse.move(cx, cy); await page.mouse.down(); await page.mouse.up();
    await page.waitForTimeout(250);
  }
  // verify wind toast says 3/3
  const toastTxt = await page.locator('#toast').innerText().catch(()=>'');
  console.log('  toast after 3 taps:', toastTxt);
  // now fire
  await fire(0, 195);
  const cChip = await page.locator('#chains-chip').innerText();
  const cShots = await page.locator('#shots-chip').innerText();
  console.log(`  catapult after 3 wind+1 fire: ${cShots} | ${cChip}`);

  // ─── TEST 4: TREBUCHET (40MB GLB) ───
  console.log('=== T4: TREBUCHET 40MB GLB ===');
  const trebStart = Date.now();
  await gotoLevel(2, 0);
  const trebMs = Date.now() - trebStart;
  console.log(`  trebuchet load+init time: ${trebMs}ms`);
  glbErr = errors.filter(e=>e.includes('trebuchet.glb'));
  console.log('  trebuchet.glb errors:', glbErr.length);
  await page.screenshot({ path:'/tmp/r3d-T4-trebuchet.png', fullPage:false });

  // ─── TEST 5: ONAGER ───
  console.log('=== T5: ONAGER GLB ===');
  await gotoLevel(3, 0);
  glbErr = errors.filter(e=>e.includes('onager.glb'));
  console.log('  onager.glb errors:', glbErr.length);
  await page.screenshot({ path:'/tmp/r3d-T5-onager.png', fullPage:false });

  console.log('\n=== ALL ERRORS ===');
  console.log('Total:', errors.length);
  errors.slice(0,8).forEach(e=>console.log(' ', e.slice(0,180)));
  await browser.close();
})().catch(e=>{ console.error('FATAL', e); process.exit(1); });
