import fs from 'node:fs';
import path from 'node:path';
import { gzipSync } from 'node:zlib';

function readBudgetEnv(name, fallback) {
  const raw = process.env[name];
  if (!raw) return fallback;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : fallback;
}

const BUDGETS = {
  entryGzipTargetKb: readBudgetEnv('BUNDLE_ENTRY_GZIP_TARGET_KB', 300),
  entryGzipHardKb: readBudgetEnv('BUNDLE_ENTRY_GZIP_HARD_KB', 350),
  lazyGzipTargetKb: readBudgetEnv('BUNDLE_LAZY_GZIP_TARGET_KB', 120),
  lazyGzipHardKb: readBudgetEnv('BUNDLE_LAZY_GZIP_HARD_KB', 180),
  mainCssGzipTargetKb: readBudgetEnv('BUNDLE_CSS_GZIP_TARGET_KB', 18),
  mainCssGzipHardKb: readBudgetEnv('BUNDLE_CSS_GZIP_HARD_KB', 25),
};

function toKb(bytes) {
  return Number((bytes / 1024).toFixed(2));
}

function gzipSize(filePath) {
  const raw = fs.readFileSync(filePath);
  return gzipSync(raw, { level: 9 }).length;
}

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function fail(message) {
  console.error(`[bundle-budget] ${message}`);
  process.exitCode = 1;
}

const webDir = process.cwd();
const distDir = path.join(webDir, 'dist');
const manifestPath = path.join(distDir, '.vite', 'manifest.json');
const repoRoot = path.resolve(webDir, '..', '..');
const perfArtifactsDir = path.join(repoRoot, 'artifacts', 'perf');

if (!fs.existsSync(manifestPath)) {
  console.error(`[bundle-budget] Missing manifest: ${manifestPath}`);
  console.error('[bundle-budget] Run `vite build` first (manifest is required).');
  process.exit(1);
}

const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
const manifestEntries = Object.values(manifest);

// `entry` stays the app's, so the headline metric means the same thing it always did and the
// numbers in `bundle-metrics.json` remain comparable across builds.
//
// **But it is no longer the only one measured.** There are three documents now — the app, the
// embedded Discover surface, and the embedded visualizer — and this script checked whichever came
// first, which was fine while there was one. `allEntries` below carries the rest into the report,
// because the visualizer is the entry that pulls `vendor-three`, the largest chunk in the build,
// and leaving the heaviest surface unwatched is precisely backwards.
const entries = manifestEntries.filter((entryMeta) => entryMeta.isEntry);
const entry = entries.find((entryMeta) => entryMeta.src === 'index.html') ?? entries[0];

if (!entry || !entry.file) {
  console.error('[bundle-budget] Could not resolve entry chunk from manifest.');
  process.exit(1);
}

const entryPath = path.join(distDir, entry.file);
const entryGzipBytes = gzipSize(entryPath);

const lazyEntries = manifestEntries.filter((entryMeta) => entryMeta.isDynamicEntry && entryMeta.file?.endsWith('.js'));
let largestLazy = null;
for (const lazyEntry of lazyEntries) {
  const lazyPath = path.join(distDir, lazyEntry.file);
  const gzipBytes = gzipSize(lazyPath);
  if (!largestLazy || gzipBytes > largestLazy.gzipBytes) {
    largestLazy = {
      file: lazyEntry.file,
      gzipBytes,
    };
  }
}

const entryCssFiles = Array.isArray(entry.css) ? entry.css : [];
const mainCss = entryCssFiles[0] ?? null;
const mainCssGzipBytes = mainCss ? gzipSize(path.join(distDir, mainCss)) : 0;

const jsAssets = new Set();
for (const entryMeta of manifestEntries) {
  if (entryMeta.file?.endsWith('.js')) {
    jsAssets.add(entryMeta.file);
  }
}

const topJsAssets = Array.from(jsAssets)
  .map((file) => {
    const filePath = path.join(distDir, file);
    const rawBytes = fs.statSync(filePath).size;
    const gzipBytes = gzipSize(filePath);
    return { file, rawBytes, gzipBytes };
  })
  .sort((a, b) => b.gzipBytes - a.gzipBytes)
  .slice(0, 10);

// Every entry, measured. Reported rather than budgeted: the visualizer surface legitimately pulls
// three.js and would fail the app's budget on day one, so a number to watch is honest where a
// threshold picked today would just be turned off later.
const allEntries = entries
  .map((entryMeta) => {
    const filePath = path.join(distDir, entryMeta.file);
    const gzipBytes = gzipSize(filePath);
    return { src: entryMeta.src ?? entryMeta.file, file: entryMeta.file, gzipBytes, gzipKb: toKb(gzipBytes) };
  })
  .sort((a, b) => b.gzipBytes - a.gzipBytes);

for (const measured of allEntries) {
  console.log(`[bundle-budget] Entry ${measured.src}: ${measured.gzipKb} kB gzip (${measured.file})`);
}

const metrics = {
  generatedAt: new Date().toISOString(),
  budgets: BUDGETS,
  entries: allEntries,
  entry: {
    file: entry.file,
    rawBytes: fs.statSync(entryPath).size,
    gzipBytes: entryGzipBytes,
    gzipKb: toKb(entryGzipBytes),
  },
  largestLazy: largestLazy
    ? {
      file: largestLazy.file,
      gzipBytes: largestLazy.gzipBytes,
      gzipKb: toKb(largestLazy.gzipBytes),
    }
    : null,
  mainCss: mainCss
    ? {
      file: mainCss,
      gzipBytes: mainCssGzipBytes,
      gzipKb: toKb(mainCssGzipBytes),
    }
    : null,
  topJsAssets: topJsAssets.map((asset) => ({
    file: asset.file,
    rawBytes: asset.rawBytes,
    rawKb: toKb(asset.rawBytes),
    gzipBytes: asset.gzipBytes,
    gzipKb: toKb(asset.gzipBytes),
  })),
};

const warnings = [];
const failures = [];

if (toKb(entryGzipBytes) > BUDGETS.entryGzipHardKb) {
  failures.push(`Entry gzip ${toKb(entryGzipBytes)} kB exceeds hard limit ${BUDGETS.entryGzipHardKb} kB`);
} else if (toKb(entryGzipBytes) > BUDGETS.entryGzipTargetKb) {
  warnings.push(`Entry gzip ${toKb(entryGzipBytes)} kB exceeds target ${BUDGETS.entryGzipTargetKb} kB`);
}

if (largestLazy) {
  if (toKb(largestLazy.gzipBytes) > BUDGETS.lazyGzipHardKb) {
    failures.push(`Largest lazy chunk gzip ${toKb(largestLazy.gzipBytes)} kB exceeds hard limit ${BUDGETS.lazyGzipHardKb} kB`);
  } else if (toKb(largestLazy.gzipBytes) > BUDGETS.lazyGzipTargetKb) {
    warnings.push(`Largest lazy chunk gzip ${toKb(largestLazy.gzipBytes)} kB exceeds target ${BUDGETS.lazyGzipTargetKb} kB`);
  }
}

if (mainCss) {
  if (toKb(mainCssGzipBytes) > BUDGETS.mainCssGzipHardKb) {
    failures.push(`Main CSS gzip ${toKb(mainCssGzipBytes)} kB exceeds hard limit ${BUDGETS.mainCssGzipHardKb} kB`);
  } else if (toKb(mainCssGzipBytes) > BUDGETS.mainCssGzipTargetKb) {
    warnings.push(`Main CSS gzip ${toKb(mainCssGzipBytes)} kB exceeds target ${BUDGETS.mainCssGzipTargetKb} kB`);
  }
}

ensureDir(perfArtifactsDir);
const jsonPath = path.join(perfArtifactsDir, 'bundle-metrics.json');
const mdPath = path.join(perfArtifactsDir, 'bundle-metrics.md');
fs.writeFileSync(jsonPath, JSON.stringify(metrics, null, 2));

const mdLines = [
  '# Bundle Metrics',
  '',
  `Generated: ${metrics.generatedAt}`,
  '',
  '## Summary',
  '',
  `- Entry: \`${metrics.entry.file}\` (${metrics.entry.gzipKb} kB gzip)`,
  `- Largest Lazy: ${metrics.largestLazy ? `\`${metrics.largestLazy.file}\` (${metrics.largestLazy.gzipKb} kB gzip)` : 'N/A'}`,
  `- Main CSS: ${metrics.mainCss ? `\`${metrics.mainCss.file}\` (${metrics.mainCss.gzipKb} kB gzip)` : 'N/A'}`,
  '',
  '## Top JS Assets (gzip)',
  '',
  '| File | Raw (kB) | Gzip (kB) |',
  '|---|---:|---:|',
  ...metrics.topJsAssets.map((asset) => `| ${asset.file} | ${asset.rawKb} | ${asset.gzipKb} |`),
  '',
  '## Budget Results',
  '',
  ...(warnings.length === 0 && failures.length === 0 ? ['- All budgets within target thresholds.'] : []),
  ...warnings.map((warning) => `- Warning: ${warning}`),
  ...failures.map((failure) => `- Fail: ${failure}`),
  '',
];
fs.writeFileSync(mdPath, mdLines.join('\n'));

console.log('[bundle-budget] Entry gzip:', `${toKb(entryGzipBytes)} kB`, `(${entry.file})`);
if (largestLazy) {
  console.log('[bundle-budget] Largest lazy gzip:', `${toKb(largestLazy.gzipBytes)} kB`, `(${largestLazy.file})`);
}
if (mainCss) {
  console.log('[bundle-budget] Main CSS gzip:', `${toKb(mainCssGzipBytes)} kB`, `(${mainCss})`);
}
console.log(`[bundle-budget] Wrote metrics: ${jsonPath}`);
console.log(`[bundle-budget] Wrote report: ${mdPath}`);

for (const warning of warnings) {
  console.warn(`[bundle-budget][warning] ${warning}`);
}
for (const failure of failures) {
  fail(failure);
}
