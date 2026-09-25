// Renders architecture.html to docs/img/architecture.png (2x, the #diagram element only).
// Needs Playwright:  npm i playwright && npx playwright install chromium
// Run:               node docs/diagram/export.js
const path = require('path');
const { chromium } = require('playwright');

const src = path.join(__dirname, 'architecture.html');
const out = path.join(__dirname, '..', 'img', 'architecture.png');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1600, height: 930 }, deviceScaleFactor: 2 });
  await page.goto('file://' + src);
  // the page sets data-ready once the arrows are drawn
  await page.waitForFunction(() => document.body.dataset.ready === '1', null, { timeout: 20000 });
  await page.waitForTimeout(300);
  await page.locator('#diagram').screenshot({ path: out });
  await browser.close();
  console.log('wrote ' + out);
})().catch((e) => { console.error(e); process.exit(1); });
