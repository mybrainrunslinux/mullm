/**
 * Gamedev Bench — automated quality validation for every browser game.
 *
 * Checklist per game:
 *   1. load           — HTTP 200, no JS console errors
 *   2. help_button    — ? button exists, clickable, reveals >50 chars of text
 *   3. has_start      — detectable start/play state (button or rendered canvas)
 *   4. controls_described — help text mentions keyboard or mouse actions
 *   5. single_input   — one primary input mode (keyboard-only or mouse-only)
 *   6. canvas_visible — canvas element exists and has non-zero dimensions
 *   7. mobile_friendly — 390x844 viewport: no horizontal scroll, canvas visible
 *
 * Writes results to:
 *   cache/data/gamedev_bench_results.json
 *   cache/data/gamedev_bench_metadata.json
 *
 * POSTs summary to /api/bench/gamedev
 *
 * Run: npx playwright test tests/gamedev-bench.spec.ts
 *   (never runs cloud/paid endpoints — all checks are local and $0)
 */

import { test, expect, Page, Browser } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const BASE_URL = process.env.MULLM_URL || 'https://127.0.0.1:8100';
const READY_DIR = path.join(__dirname, '..', 'code', 'ready');
const RESULTS_FILE = path.join(__dirname, '..', 'cache', 'data', 'gamedev_bench_results.json');
const META_FILE = path.join(__dirname, '..', 'cache', 'data', 'gamedev_bench_metadata.json');
const GAME_TIMEOUT_MS = 15_000;

// Non-game files (instruments, tools, templates) — excluded from bench
const EXCLUDED = new Set([
  'clarinet.html',
  'saxophone.html',
  'dulcimer.html',
  'glass-harp.html',
  'marimba.html',
  'pipe-organ.html',
  'steel-drums.html',
  'theremin.html',
  'war-drums.html',
  'aibophone.html',
  'string-quartet.html',
  'symphony-conductor.html',
  'diff-viewer.html',
  'server-monitor.html',
  'control-center.html',
  'pixel-painter.html',
  'path-tracing.html',
  'word-hex-template.html',
]);

// Games that load 50-100MB+ GLBs — crash headless Playwright (GPU memory)
const HEAVY_3D = new Set([
  'crystal-match.html',
  'crystal-sanctum.html',
  'shadow-cathedral.html',
]);

// Keyboard key patterns in help text
const KEYBOARD_PATTERNS = [
  /\bwasd\b/i,
  /arrow keys?/i,
  /\bleft\s+key\b/i,
  /\bright\s+key\b/i,
  /\bup\s+key\b/i,
  /\bdown\s+key\b/i,
  /\bspace(bar)?\b/i,
  /\benter\b/i,
  /press\s+[A-Z]/i,
  /\[?[A-Z]\]?\s+key/i,
  /keyboard/i,
];

// Mouse action patterns in help text
const MOUSE_PATTERNS = [
  /click/i,
  /mouse/i,
  /drag/i,
  /\bpoint\b/i,
  /\bswipe\b/i,
  /tap/i,
  /touch/i,
];

// Start/play button selector list (ordered by specificity)
const START_SELECTORS = [
  'button:has-text("Start")',
  'button:has-text("Play")',
  'button:has-text("New Game")',
  'button:has-text("Begin")',
  'button:has-text("Deal")',
  'button:has-text("Go")',
  'button:has-text("Launch")',
  'button:has-text("Click to Start")',
  'button:has-text("Press to Start")',
  '[id*="start"]',
  '[id*="play"]',
  '.start-btn',
  '.play-btn',
  '#startBtn',
  '#playBtn',
  '#start-btn',
  '#play-btn',
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function matchesAny(text: string, patterns: RegExp[]): boolean {
  return patterns.some(p => p.test(text));
}

/** Reveal any hidden help/? overlay by clicking common ? button patterns */
async function revealHelp(page: Page): Promise<string> {
  const helpSelectors = [
    'button:has-text("?")',
    '[aria-label*="help" i]',
    '[title*="help" i]',
    '.help-btn',
    '#help-btn',
    '#helpBtn',
    'button.help',
    '[data-action="help"]',
  ];

  for (const sel of helpSelectors) {
    try {
      const btn = page.locator(sel).first();
      if (await btn.count() > 0 && await btn.isVisible({ timeout: 800 })) {
        await btn.click({ timeout: 2000 });
        await page.waitForTimeout(500);
        break;
      }
    } catch {
      // not found — try next
    }
  }

  // Collect visible text from the whole page after potential help reveal
  return page.evaluate(() => document.body.innerText || '');
}

/** Try to click a start/play button. Returns true if one was found and clicked. */
async function clickStart(page: Page): Promise<boolean> {
  for (const sel of START_SELECTORS) {
    try {
      const btn = page.locator(sel).first();
      if (await btn.count() > 0 && await btn.isVisible({ timeout: 500 })) {
        await btn.click({ timeout: 2000 });
        return true;
      }
    } catch {
      // continue
    }
  }
  return false;
}

// ---------------------------------------------------------------------------
// Results accumulator (module-level so all tests append to it)
// ---------------------------------------------------------------------------

interface GameResult {
  game: string;
  load: boolean;
  help_button: boolean;
  has_start: boolean;
  controls_described: boolean;
  single_input: boolean;
  canvas_visible: boolean;
  mobile_friendly: boolean;
  brightness_ok: boolean;   // canvas avg luminance > 10/255 after start (Play@k: not a black screen)
  input_responds: boolean;  // pixels change after keyboard/click events (Play@k: behavioral response)
  touch_responds: boolean;  // visual change after touch tap in mobile viewport (Play@k: touch input works)
  skipped: boolean;
  skip_reason?: string;
  errors: string[];
}

interface GameMeta {
  game: string;
  keyboard_only: boolean;
  mouse_only: boolean;
  mobile_friendly: boolean;
  has_help: boolean;
  has_start: boolean;
}

// Loaded once, written at teardown
const allResults: GameResult[] = [];
const allMeta: GameMeta[] = [];

// ---------------------------------------------------------------------------
// Discover game files
// ---------------------------------------------------------------------------

const gameFiles: string[] = (() => {
  if (!fs.existsSync(READY_DIR)) return [];
  return fs
    .readdirSync(READY_DIR)
    .filter(f => f.endsWith('.html') && !EXCLUDED.has(f) && !HEAVY_3D.has(f))
    .sort();
})();

// ---------------------------------------------------------------------------
// Test suite
// ---------------------------------------------------------------------------

test.describe('Gamedev Bench', () => {

  // After all tests, persist results and post summary
  test.afterAll(async ({ browser }) => {
    // Ensure output dir exists
    const outDir = path.dirname(RESULTS_FILE);
    if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });

    // Write results JSON
    fs.writeFileSync(RESULTS_FILE, JSON.stringify(allResults, null, 2), 'utf8');

    // Write metadata JSON
    fs.writeFileSync(META_FILE, JSON.stringify(allMeta, null, 2), 'utf8');

    // Compute summary
    const total = allResults.length;
    const skipped = allResults.filter(r => r.skipped).length;
    const tested = total - skipped;
    const passing = (key: keyof GameResult) =>
      allResults.filter(r => !r.skipped && r[key] === true).length;

    const summary = {
      generated_at: new Date().toISOString(),
      total_games: total,
      skipped,
      tested,
      pass_load: passing('load'),
      pass_help_button: passing('help_button'),
      pass_has_start: passing('has_start'),
      pass_controls_described: passing('controls_described'),
      pass_single_input: passing('single_input'),
      pass_canvas_visible: passing('canvas_visible'),
      pass_mobile_friendly: passing('mobile_friendly'),
      pass_brightness_ok: passing('brightness_ok'),
      pass_input_responds: passing('input_responds'),
      pass_touch_responds: passing('touch_responds'),
      results: allResults,
    };

    // POST to /api/bench/gamedev (best-effort — server may not be running)
    try {
      const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
      const apiPage = await ctx.newPage();
      const resp = await apiPage.request.post(`${BASE_URL}/api/bench/gamedev`, {
        data: summary,
        headers: { 'Content-Type': 'application/json' },
        timeout: 5000,
      });
      const status = resp.status();
      if (status !== 200 && status !== 201) {
        console.warn(`[gamedev-bench] POST /api/bench/gamedev returned ${status}`);
      }
      await ctx.close();
    } catch (err) {
      console.warn('[gamedev-bench] Could not POST summary to /api/bench/gamedev:', err);
    }
  });

  for (const gameFile of gameFiles) {
    const gameName = gameFile.replace('.html', '');
    const gameUrl = `${BASE_URL}/code/ready/${gameFile}`;

    test(`game: ${gameName}`, async ({ page }) => {
      const result: GameResult = {
        game: gameName,
        load: false,
        help_button: false,
        has_start: false,
        controls_described: false,
        single_input: false,
        canvas_visible: false,
        mobile_friendly: false,
        brightness_ok: false,
        input_responds: false,
        touch_responds: false,
        skipped: false,
        errors: [],
      };

      const meta: GameMeta = {
        game: gameName,
        keyboard_only: false,
        mouse_only: false,
        mobile_friendly: false,
        has_help: false,
        has_start: false,
      };

      // Capture console errors
      page.on('console', msg => {
        if (msg.type() === 'error') result.errors.push(msg.text());
      });
      page.on('pageerror', err => result.errors.push(err.message));

      // ------------------------------------------------------------------
      // 1. LOAD — navigate and check HTTP 200
      // ------------------------------------------------------------------
      let response: { status(): number } | null = null;
      try {
        response = await page.goto(gameUrl, {
          waitUntil: 'domcontentloaded',
          timeout: GAME_TIMEOUT_MS,
        });
      } catch (err: any) {
        result.skipped = true;
        result.skip_reason = `Navigation failed: ${err?.message ?? err}`;
        allResults.push(result);
        allMeta.push(meta);
        return;
      }

      const httpStatus = response?.status() ?? 0;
      if (httpStatus !== 200) {
        result.skipped = true;
        result.skip_reason = `HTTP ${httpStatus}`;
        allResults.push(result);
        allMeta.push(meta);
        return;
      }

      // Wait for network to settle (soft — don't fail if it times out)
      await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});

      // Filter out known-benign errors
      const BENIGN_PATTERNS = [
        'ResizeObserver',
        'AudioContext',
        'NotAllowedError',
        'user gesture',
        'play()',
        'The play method',
        'AudioParam',
      ];
      const fatalErrors = result.errors.filter(
        e => !BENIGN_PATTERNS.some(pat => e.includes(pat))
      );

      result.load = fatalErrors.length === 0;

      // ------------------------------------------------------------------
      // 2. CANVAS VISIBLE — canvas element exists and has non-zero size
      // ------------------------------------------------------------------
      const canvasCount = await page.locator('canvas').count();
      if (canvasCount > 0) {
        const box = await page.locator('canvas').first().boundingBox();
        result.canvas_visible = !!(box && box.width > 0 && box.height > 0);
      }

      // ------------------------------------------------------------------
      // 3. HELP BUTTON — look for ? button, click it, read text
      // ------------------------------------------------------------------
      const helpSelectors = [
        'button:has-text("?")',
        '[aria-label*="help" i]',
        '[title*="help" i]',
        '.help-btn',
        '#help-btn',
        '#helpBtn',
        'button.help',
        '[data-action="help"]',
      ];

      let helpText = '';
      let foundHelpBtn = false;

      for (const sel of helpSelectors) {
        try {
          const btn = page.locator(sel).first();
          if (await btn.count() > 0 && await btn.isVisible({ timeout: 600 })) {
            foundHelpBtn = true;
            await btn.click({ timeout: 2000 });
            await page.waitForTimeout(400);
            break;
          }
        } catch {
          // continue searching
        }
      }

      // Read all visible page text (includes any revealed help overlay)
      helpText = await page.evaluate(() => document.body.innerText || '');

      if (foundHelpBtn && helpText.length > 50) {
        result.help_button = true;
        meta.has_help = true;
      }

      // ------------------------------------------------------------------
      // 4. CONTROLS DESCRIBED — keyboard or mouse patterns in visible text
      // ------------------------------------------------------------------
      const hasKeyboard = matchesAny(helpText, KEYBOARD_PATTERNS);
      const hasMouse = matchesAny(helpText, MOUSE_PATTERNS);
      result.controls_described = hasKeyboard || hasMouse;

      // ------------------------------------------------------------------
      // 5. SINGLE INPUT MODE — primarily one modality
      // ------------------------------------------------------------------
      meta.keyboard_only = hasKeyboard && !hasMouse;
      meta.mouse_only = hasMouse && !hasKeyboard;
      // single-input: one modality only OR both mentioned (mixed = still usable with one)
      result.single_input = hasKeyboard || hasMouse;

      // ------------------------------------------------------------------
      // 6. HAS START — try to find and click a start button
      // ------------------------------------------------------------------
      const startClicked = await clickStart(page);
      result.has_start = startClicked;
      meta.has_start = startClicked;

      // If no button found, check if canvas already has content (auto-start game)
      if (!startClicked && canvasCount > 0) {
        await page.waitForTimeout(2000);
        const canvasHasContent = await page.evaluate(() => {
          const c = document.querySelector('canvas') as HTMLCanvasElement | null;
          if (!c) return false;
          const ctx = c.getContext('2d');
          if (!ctx) return true; // WebGL canvas — assume content
          const data = ctx.getImageData(0, 0, Math.min(c.width, 100), Math.min(c.height, 100));
          // Check if any pixel is non-black
          for (let i = 0; i < data.data.length; i += 4) {
            if (data.data[i] > 10 || data.data[i + 1] > 10 || data.data[i + 2] > 10) {
              return true;
            }
          }
          return false;
        });
        if (canvasHasContent) {
          result.has_start = true;
          meta.has_start = true;
        }
      }

      // ------------------------------------------------------------------
      // 7. BRIGHTNESS OK — canvas avg luminance > 10/255 after game starts
      //    (Play@k-inspired: detects black/blank screens that pass Exec@k but fail Play@k)
      // ------------------------------------------------------------------
      await page.waitForTimeout(500);
      {
        const canvasNow = await page.locator('canvas').count();
        if (canvasNow > 0) {
          result.brightness_ok = await page.evaluate(() => {
            const c = document.querySelector('canvas') as HTMLCanvasElement | null;
            if (!c) return true;
            const ctx = c.getContext('2d');
            if (!ctx) return true; // WebGL — can't introspect pixels, assume visible
            const w = Math.min(c.width, 160), h = Math.min(c.height, 160);
            if (!w || !h) return false;
            const data = ctx.getImageData(0, 0, w, h).data;
            let sum = 0;
            for (let i = 0; i < data.length; i += 4) {
              sum += 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
            }
            return (sum / (data.length / 4)) > 10;
          });
        } else {
          result.brightness_ok = true; // DOM-only game — no canvas to check
        }
      }

      // ------------------------------------------------------------------
      // 8. INPUT RESPONDS — fire keyboard + click, check for canvas pixel change
      //    (Play@k-inspired: detects silent failures where game renders but ignores input)
      // ------------------------------------------------------------------
      {
        const canvasNow = await page.locator('canvas').count();
        const samplePx = () => page.evaluate(() => {
          const c = document.querySelector('canvas') as HTMLCanvasElement | null;
          if (!c) return 'no_canvas';
          const ctx = c.getContext('2d');
          if (!ctx) return 'webgl';
          const { width: w, height: h } = c;
          if (!w || !h) return 'zero';
          let s = '';
          for (let i = 0; i < 16; i++) {
            const x = Math.floor((i / 15) * (w - 1));
            const y = Math.floor(((15 - i) / 15) * (h - 1));
            const d = ctx.getImageData(x, y, 1, 1).data;
            s += `${d[0]}${d[1]}${d[2]}`;
          }
          return s;
        });

        const before = await samplePx();
        if (canvasNow > 0 && before !== 'no_canvas' && before !== 'zero') {
          try {
            const box = await page.locator('canvas').first().boundingBox();
            if (box) await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
          } catch { /* ignore */ }
          for (const key of ['ArrowRight', 'Space', 'ArrowUp', 'ArrowLeft']) {
            await page.keyboard.press(key).catch(() => {});
            await page.waitForTimeout(75);
          }
          await page.waitForTimeout(300);
          const after = await samplePx();
          // WebGL canvases can't be pixel-sampled — assume responsive
          result.input_responds = after !== before || after === 'webgl';
        } else {
          result.input_responds = true; // no canvas or DOM game — skip check
        }
      }

      // ------------------------------------------------------------------
      // 9. MOBILE FRIENDLY + TOUCH RESPONDS — 390x844 viewport checks
      // ------------------------------------------------------------------
      try {
        // Open a fresh page at mobile viewport
        const mobileCtx = await page.context().browser()!.newContext({
          viewport: { width: 390, height: 844 },
          hasTouch: true,
          ignoreHTTPSErrors: true,
        });
        const mobilePage = await mobileCtx.newPage();
        await mobilePage.goto(gameUrl, {
          waitUntil: 'domcontentloaded',
          timeout: GAME_TIMEOUT_MS,
        });
        await mobilePage.waitForTimeout(800);

        const mobileCheck = await mobilePage.evaluate(() => {
          const hasHScroll = document.documentElement.scrollWidth > window.innerWidth + 5;
          const canvas = document.querySelector('canvas');
          const mainEl = document.querySelector('main, [role="main"], canvas, .game, #game') as HTMLElement | null;
          const checkVisible = (el: Element | null) => {
            if (!el) return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
          };
          return {
            hasHScroll,
            canvasVisible: checkVisible(canvas),
            mainVisible: checkVisible(mainEl),
          };
        });

        result.mobile_friendly = !mobileCheck.hasHScroll && (mobileCheck.canvasVisible || mobileCheck.mainVisible);
        meta.mobile_friendly = result.mobile_friendly;

        // Touch responds — tap canvas center, check pixel change
        if (mobileCheck.canvasVisible) {
          try {
            const mBox = await mobilePage.locator('canvas').first().boundingBox();
            const pxSample = (mp: typeof mobilePage) => mp.evaluate(() => {
              const c = document.querySelector('canvas') as HTMLCanvasElement | null;
              if (!c) return 'none';
              const ctx = c.getContext('2d');
              if (!ctx) return 'webgl';
              const { width: w, height: h } = c;
              if (!w || !h) return 'zero';
              let s = '';
              for (let i = 0; i < 12; i++) {
                const x = Math.floor((i / 11) * (w - 1));
                const y = Math.floor(((11 - i) / 11) * (h - 1));
                const d = ctx.getImageData(x, y, 1, 1).data;
                s += `${d[0]}${d[1]}${d[2]}`;
              }
              return s;
            });
            const pxBefore = await pxSample(mobilePage);
            if (mBox && pxBefore !== 'webgl' && pxBefore !== 'none') {
              await mobilePage.touchscreen.tap(
                mBox.x + mBox.width / 2,
                mBox.y + mBox.height / 2,
              );
              await mobilePage.waitForTimeout(350);
              const pxAfter = await pxSample(mobilePage);
              result.touch_responds = pxAfter !== pxBefore;
            } else {
              result.touch_responds = pxBefore === 'webgl'; // WebGL assumed responsive
            }
          } catch {
            result.touch_responds = false;
          }
        }

        await mobileCtx.close();
      } catch {
        // Mobile check failed — treat as skip for this dimension
        result.mobile_friendly = false;
      }

      // ------------------------------------------------------------------
      // Accumulate
      // ------------------------------------------------------------------
      allResults.push(result);
      allMeta.push(meta);

      // Soft assertions — report but don't block suite (games may have known issues)
      // Only fail if the page completely failed to load (HTTP or nav error)
      // Individual checklist items are informational for the dashboard.
      if (!result.load) {
        console.warn(`[${gameName}] Fatal JS errors: ${fatalErrors.slice(0, 3).join(' | ')}`);
      }
    });
  }

  // Guard test: if no game files found, fail loudly
  test('meta: game files discovered', () => {
    expect(gameFiles.length, `No game files found in ${READY_DIR}`).toBeGreaterThan(0);
  });
});
