const { test, expect } = require('@playwright/test');

test('carousel debug', async ({ page }) => {
  page.on('console', msg => console.log('BROWSER:', msg.text()));
  page.on('pageerror', err => console.log('PAGE ERROR:', err.message));
  
  await page.goto('/bench');
  await page.waitForSelector('#bench-trophy-case', { timeout: 10000 });
  await page.waitForTimeout(1000);

  // Check if function is global
  const isFn = await page.evaluate(() => typeof window.trophyPauseToggle);
  console.log('trophyPauseToggle type:', isFn);

  // Try calling it directly
  const result = await page.evaluate(() => {
    try {
      window.trophyPauseToggle();
      return 'called ok';
    } catch(e) {
      return 'error: ' + e.message;
    }
  });
  console.log('Direct call result:', result);

  const btnText = await page.evaluate(() => document.getElementById('trophy-pause-btn')?.textContent?.trim());
  console.log('Button text after direct call:', btnText);
});
