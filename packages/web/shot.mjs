import { chromium } from '@playwright/test';
const out = '/private/tmp/claude-501/-Users-jeff-Developer-familiar/7ee6e137-6610-4b1b-a7e1-ac2202e096d8/scratchpad';
const b = await chromium.launch();
const errs = [];
const p = await b.newPage({ viewport: { width: 1280, height: 800 } });
p.on('pageerror', e => errs.push('pageerror: ' + e.message));
p.on('console', m => { if (m.type() === 'error') errs.push('console: ' + m.text()); });

await p.goto('http://localhost:3000/', { waitUntil: 'domcontentloaded' });
await p.waitForTimeout(3500);
// Dismiss profile selector if present
const btn = p.locator('button', { hasText: /Continue|Select|Create/ }).first();
if (await btn.isVisible({ timeout: 1500 }).catch(() => false)) { await btn.click(); await p.waitForTimeout(2000); }
await p.screenshot({ path: `${out}/topbar-library.png` });

for (const [label, file] of [['Tools','topbar-tools.png'], ['Server','topbar-server.png']]) {
  const link = p.getByRole('link', { name: label, exact: true }).first();
  console.log(label, 'link visible:', await link.isVisible({ timeout: 4000 }).catch(() => false));
  await link.click();
  await p.waitForTimeout(2500);
  await p.screenshot({ path: `${out}/${file}` });
}

// A settings URL must land on the dashboard
await p.goto('http://localhost:3000/settings', { waitUntil: 'domcontentloaded' });
await p.waitForTimeout(2000);
console.log('after /settings -> url:', p.url());
console.log('Library heading visible:', await p.getByRole('heading', { name: 'Library', exact: true }).first().isVisible().catch(() => false));

// Narrow viewport
await p.setViewportSize({ width: 390, height: 780 });
await p.goto('http://localhost:3000/', { waitUntil: 'domcontentloaded' });
await p.waitForTimeout(2500);
await p.screenshot({ path: `${out}/topbar-narrow.png` });

console.log('--- errors ---');
console.log(errs.slice(0, 12).join('\n') || 'none');
await b.close();
