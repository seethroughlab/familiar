/**
 * A green E2E run means the named workflows ran (ADR-0174 points 1 and 2).
 *
 * Until ADR-0174 a spec could `test.skip()` when its data or controls were missing, so a broken
 * selector and an unsupported environment looked the same, and both looked like a pass. The
 * playlist spec did this for every test: the web app had stopped having a playlist screen
 * (ADR-0058), and CI reported "5 skipped" beside "15 passed" for months.
 *
 * This reads Playwright's JSON report and fails on any skipped test, except one skipped for a
 * capability declared before the suite starts: `test.skip(condition, 'capability: <name> — why')`
 * with `<name>` listed in `CAPABILITIES` below. Those are reported on their own line, so the budget
 * is visible rather than folded into "passed".
 *
 *   node scripts/check-e2e-skips.mjs [playwright-report/results.json]
 */
import fs from 'node:fs';

/** Environment capabilities a test may declare it needs. Empty: nothing in CI skips today. */
const CAPABILITIES = new Set([]);

const file = process.argv[2] ?? 'playwright-report/results.json';
if (!fs.existsSync(file)) {
  console.error(`No Playwright report at ${file}; the E2E step did not produce one.`);
  process.exit(1);
}
const report = JSON.parse(fs.readFileSync(file, 'utf8'));

function* specs(suite, path = []) {
  const here = suite.title ? [...path, suite.title] : path;
  for (const spec of suite.specs ?? []) yield { spec, path: here };
  for (const child of suite.suites ?? []) yield* specs(child, here);
}

const unexplained = [];
const declared = [];
for (const top of report.suites ?? []) {
  for (const { spec, path } of specs(top)) {
    for (const t of spec.tests ?? []) {
      const skipped = t.status === 'skipped' || t.results?.at(-1)?.status === 'skipped';
      if (!skipped) continue;
      const reason = (t.annotations ?? []).find((a) => a.type === 'skip')?.description ?? '';
      const name = [...path, spec.title].join(' › ');
      const capability = /^capability:\s*([\w-]+)/.exec(reason)?.[1];
      if (capability && CAPABILITIES.has(capability)) declared.push(`${name} (${capability})`);
      else unexplained.push(`${name}${reason ? ` — "${reason}"` : ''}`);
    }
  }
}

if (declared.length) {
  console.log(`Skipped for a declared capability (${declared.length}):\n  ${declared.join('\n  ')}`);
}
if (unexplained.length) {
  console.log(
    `::error::${unexplained.length} E2E test(s) skipped without a declared capability (ADR-0174). ` +
      `Seed what the test needs, or fix the selector:\n  ${unexplained.join('\n  ')}`,
  );
  process.exit(1);
}
console.log('No unexplained E2E skips.');
