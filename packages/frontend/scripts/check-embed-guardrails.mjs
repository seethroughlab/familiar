/**
 * Guards the two properties the embedded surfaces depend on and nothing else can see.
 *
 * This replaces `check-audio-guardrails.mjs`, which read `player/useAudioEngine.ts` and
 * `player/queueStore.ts` by path and asserted things about the *text* inside them — so it broke
 * outright when those files went with the fallback player, and it could only ever have caught a
 * regression in the two files it happened to name.
 *
 * What matters now is a property rather than a phrasing: `/embed` and `/visualizer` are separate
 * documents rendered inside `WKWebView`s by the Mac and iPhone apps (ADR-0016, ADR-0017), and
 * **nothing automated covers them**. So the checks here are about what those entry points are
 * allowed to reach.
 *
 * Deliberately a reachability walk over imports rather than a text match: an import is the thing
 * that actually pulls code into the document, and it cannot be satisfied by a comment.
 */
import fs from 'node:fs';
import path from 'node:path';

const repoRoot = path.resolve(import.meta.dirname, '..');
const webSrc = path.resolve(repoRoot, '..', 'web', 'src');
const frontendSrc = path.join(repoRoot, 'src');

const ENTRY_POINTS = [
  path.join(webSrc, 'embed.tsx'),
  path.join(webSrc, 'visualizer.tsx'),
];

/** Modules an embedded document must never pull in, and why. */
const FORBIDDEN = [
  { match: /(^|\/)db(\/index)?\.tsx?$/, why: 'IndexedDB: the embedded surfaces store nothing (ADR-0071)' },
  { match: /WebAudioEngine\.tsx?$/, why: 'a real audio engine: the embed registers a null one (ADR-0017)' },
  { match: /(^|\/)audioEffects(\/|$)/, why: 'the effects chain, which needs an AudioContext (ADR-0017 point 2)' },
];

/** Bare specifiers an embedded document must never import. */
const FORBIDDEN_PACKAGES = [
  { name: 'dexie', why: 'IndexedDB: the embedded surfaces store nothing (ADR-0071)' },
];

const failures = [];

function resolveImport(fromFile, spec) {
  if (spec.startsWith('@familiar/frontend/src/')) {
    return tryExtensions(path.join(frontendSrc, spec.slice('@familiar/frontend/src/'.length)));
  }
  if (spec.startsWith('.')) {
    return tryExtensions(path.resolve(path.dirname(fromFile), spec));
  }
  return null; // bare specifier — handled separately
}

function tryExtensions(base) {
  for (const candidate of [base, `${base}.ts`, `${base}.tsx`, path.join(base, 'index.ts'), path.join(base, 'index.tsx')]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  }
  return null;
}

function importsOf(file) {
  const source = fs.readFileSync(file, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '');
  const specs = [];
  for (const m of source.matchAll(/(?:from|import)\s*\(?\s*['"]([^'"]+)['"]/g)) {
    specs.push(m[1]);
  }
  return specs;
}

const seen = new Set();
const queue = [];

for (const entry of ENTRY_POINTS) {
  if (!fs.existsSync(entry)) {
    failures.push(`Entry point is missing: ${path.relative(repoRoot, entry)}`);
    continue;
  }
  queue.push({ file: entry, from: [path.basename(entry)] });
}

while (queue.length > 0) {
  const { file, from } = queue.shift();
  if (seen.has(file)) continue;
  seen.add(file);

  for (const spec of importsOf(file)) {
    const forbiddenPackage = FORBIDDEN_PACKAGES.find((p) => spec === p.name || spec.startsWith(`${p.name}/`));
    if (forbiddenPackage) {
      failures.push(`${from.join(' → ')} imports '${spec}' — ${forbiddenPackage.why}`);
      continue;
    }

    const resolved = resolveImport(file, spec);
    if (!resolved) continue;

    const rel = path.relative(frontendSrc, resolved);
    const forbidden = FORBIDDEN.find((f) => f.match.test(rel) || f.match.test(resolved));
    if (forbidden) {
      failures.push(`${[...from, path.basename(resolved)].join(' → ')} — ${forbidden.why}`);
      continue;
    }

    queue.push({ file: resolved, from: [...from, path.basename(resolved)] });
  }
}

if (failures.length > 0) {
  console.error('Embed guardrails FAILED:\n');
  for (const failure of failures) console.error(`  - ${failure}`);
  console.error('\nThese surfaces are rendered inside the Mac and iPhone apps and nothing else tests them.');
  process.exit(1);
}

console.log(`Embed guardrails OK: ${seen.size} modules reachable from /embed and /visualizer, none forbidden`);
