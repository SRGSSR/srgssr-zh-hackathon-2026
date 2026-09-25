// The example letters as A4 PDFs, for the "Upload a photo or PDF" button (a mock: the app
// matches the file name to the example letter). Needs Playwright:
//   npm i playwright && npx playwright install chromium && node samples/pdf/make.js
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const samples = path.join(__dirname, '..');
const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const page = (text) => `<!doctype html><html lang="de"><head><meta charset="utf-8"><style>
  @page { size: A4; margin: 22mm 24mm 24mm; }
  body { font: 10.5pt/1.5 "Helvetica Neue", Arial, sans-serif; color: #1b2433; margin: 0; }
  header { display: flex; align-items: center; gap: 10px; margin-bottom: 14mm; }
  header b { font-size: 13pt; }
  pre { font: inherit; white-space: pre-wrap; margin: 0; }
</style></head><body>
  <header><svg width="22" height="26" viewBox="0 0 32 38"><path d="M2 2h28v17c0 9-6.5 14.5-14 17C8.5 33.5 2 28 2 19z" fill="#2b44c9"/>
    <path d="M5 22c3-2.5 5.5-2.5 8 0s5 2.5 8 0 5-2.5 6 0" stroke="#fff" stroke-width="2.2" fill="none" stroke-linecap="round"/>
    <circle cx="16" cy="11" r="3.2" fill="#fff"/></svg><b>Gemeinde Musterstadt</b></header>
  <pre>${esc(text)}</pre></body></html>`;

(async () => {
  const browser = await chromium.launch();
  const tab = await browser.newPage();
  for (const file of fs.readdirSync(samples).filter((f) => f.endsWith('.txt'))) {
    const text = fs.readFileSync(path.join(samples, file), 'utf8').replace(/^Gemeinde Musterstadt\n/, '');
    await tab.setContent(page(text));
    const out = path.join(__dirname, file.replace(/\.txt$/, '.pdf'));
    await tab.pdf({ path: out, format: 'A4', printBackground: true });
    console.log('wrote ' + out);
  }
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
