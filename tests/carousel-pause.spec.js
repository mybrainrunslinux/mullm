const { test, expect } = require('@playwright/test');

test('carousel: 6 cards visible, pause stops slide, card 5 has content', async ({ page }) => {
  await page.goto('/bench');
  await page.waitForSelector('#bench-trophy-case', { timeout: 10000 });
  await page.waitForTimeout(800);

  const cardCount = await page.evaluate(() => document.querySelectorAll('.trophy-card').length);
  console.log('Card count:', cardCount);
  expect(cardCount).toBe(6);

  const card6Text = await page.evaluate(() => {
    const c = document.querySelector('[data-idx="5"]');
    return c ? c.textContent.trim().substring(0, 150) : 'NOT FOUND';
  });
  console.log('Card 6 text:', card6Text);
  expect(card6Text).not.toBe('NOT FOUND');
  expect(card6Text.length).toBeGreaterThan(10);

  // Pause
  await page.click('#trophy-pause-btn');
  await page.waitForTimeout(300);

  const btnText = await page.evaluate(() => document.getElementById('trophy-pause-btn')?.textContent?.trim());
  console.log('Button after pause:', btnText);
  expect(btnText).toContain('Play');

  const animState = await page.evaluate(() => {
    const fill = document.getElementById('trophy-progress-fill');
    return fill ? getComputedStyle(fill).animationPlayState : 'NOT FOUND';
  });
  console.log('Animation play state:', animState);
  expect(animState).toBe('paused');

  const cardBefore = await page.evaluate(() => document.querySelector('.trophy-card.tc-active')?.dataset.idx);
  await page.waitForTimeout(8000);
  const cardAfter = await page.evaluate(() => document.querySelector('.trophy-card.tc-active')?.dataset.idx);
  console.log(`Card held: ${cardBefore} -> ${cardAfter}`);
  expect(cardAfter).toBe(cardBefore);

  // Resume
  await page.click('#trophy-pause-btn');
  await page.waitForTimeout(200);
  const btnAfterResume = await page.evaluate(() => document.getElementById('trophy-pause-btn')?.textContent?.trim());
  console.log('Button after resume:', btnAfterResume);
  expect(btnAfterResume).toContain('Pause');
});
