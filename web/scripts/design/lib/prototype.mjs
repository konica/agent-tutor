// Opens the prototype in headless Chromium to read its state index and render states (design spec §5, §5.1).
import { chromium } from 'playwright';
import { pathToFileURL } from 'node:url';

export const VIEWPORT = { width: 1440, height: 900 };

// Fallback for prototypes that ignore ?shot=1: hide the design-review chrome and give its height back to the app.
const HIDE_REVIEW_CHROME = '.review-bar { display: none !important; } :root, [data-theme] { --review-h: 0px !important; }';

export async function withBrowser(fn) {
  const browser = await chromium.launch();
  try {
    return await fn(browser);
  } finally {
    await browser.close();
  }
}

export async function readRawStates(browser, indexHtml, timeout = 10_000) {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  try {
    await page.goto(pathToFileURL(indexHtml).href);
    await page.waitForFunction(() => Array.isArray(window.ST?.STATES), null, { timeout }).catch(() => {
      const detail = errors.length ? `; page errors: ${errors.join('; ')}` : '';
      throw new Error(`window.ST.STATES never appeared in ${indexHtml}${detail}`);
    });
    return await page.evaluate(() =>
      window.ST.STATES.map((s) => ({ id: s.id, group: s.group, ref: s.ref, desc: s.desc, release: s.release ?? null })),
    );
  } finally {
    await page.close();
  }
}

export async function shootState(browser, indexHtml, id, theme, outFile) {
  const context = await browser.newContext({ viewport: VIEWPORT, colorScheme: theme });
  // The Smart Tutor prototype reads its theme from localStorage key st_theme (index.html).
  await context.addInitScript((t) => {
    try {
      localStorage.setItem('st_theme', t);
    } catch {}
  }, theme);
  try {
    const page = await context.newPage();
    await page.goto(`${pathToFileURL(indexHtml).href}?shot=1#/${id}`);
    await page.addStyleTag({ content: HIDE_REVIEW_CHROME });
    await page.waitForTimeout(400);
    await page.screenshot({ path: outFile });
  } finally {
    await context.close();
  }
}
