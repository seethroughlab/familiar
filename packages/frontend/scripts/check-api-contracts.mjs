/**
 * No new handwritten response contracts (ADR-0173 points 5 and 7).
 *
 * `@familiar/api-client` is generated from `backend/openapi.json` (ADR-0129) and owns the browser's
 * wire contract. The feature adapters in `src/api/` predate it and still declare their own response
 * shapes: 2026-11-08's audit found `LibraryDiscoverResponse` naming a `RediscoverySuggestion` nobody
 * had defined, which compiled only because nothing type-checked the package (ADR-0170). Two owners
 * of one contract drift apart, and nothing notices until a field is missing at runtime.
 *
 * So: an exported `interface`, or an exported `type` whose body contains an object literal, in
 * `src/api/` is a handwritten contract, and it must be listed in `api-contracts.allowlist.json`.
 *
 * - `migrating`: the ones that exist today, by file, each removed when its domain moves to
 *   generated types (discovery/library, then tracks, then playlists). The list ratchets: an entry
 *   whose type no longer exists, or is no longer handwritten, fails, so it can only shrink.
 * - `viewModels`: shapes that are not a response at all (UI state, a deliberate transformed view,
 *   a request built by the client), each with a reason. Permanent by design.
 *
 * An alias of a generated type (`export type PhaseQueue = WirePhaseQueue`) is not a contract and is
 * never listed. Read with the TypeScript parser, not a regex, so a comment cannot satisfy it.
 *
 *   node scripts/check-api-contracts.mjs            # check
 *   node scripts/check-api-contracts.mjs --list     # print what it finds, to seed or audit the list
 */
import fs from 'node:fs';
import path from 'node:path';
import ts from 'typescript';

const root = path.resolve(import.meta.dirname, '..');
const apiDir = path.join(root, 'src', 'api');
const allowlistPath = path.join(root, 'api-contracts.allowlist.json');

function containsTypeLiteral(node) {
  if (!node) return false;
  if (ts.isTypeLiteralNode(node) || ts.isMappedTypeNode(node)) return true;
  let found = false;
  ts.forEachChild(node, (child) => {
    // A generic argument (`Record<string, Foo>`, `Pick<Wire, ...>`) is a use, not a declaration of
    // a new shape, unless an object literal is written inline.
    if (!found && containsTypeLiteral(child)) found = true;
  });
  return found;
}

function isExported(node) {
  return node.modifiers?.some((m) => m.kind === ts.SyntaxKind.ExportKeyword) ?? false;
}

/** `{ file: [TypeName, ...] }` for every handwritten exported contract in src/api. */
export function findContracts() {
  const found = {};
  for (const name of fs.readdirSync(apiDir).sort()) {
    if (!name.endsWith('.ts') || name.endsWith('.test.ts')) continue;
    const text = fs.readFileSync(path.join(apiDir, name), 'utf8');
    const source = ts.createSourceFile(name, text, ts.ScriptTarget.Latest, true);
    const names = [];
    for (const statement of source.statements) {
      if (!isExported(statement)) continue;
      if (ts.isInterfaceDeclaration(statement)) names.push(statement.name.text);
      else if (ts.isTypeAliasDeclaration(statement) && containsTypeLiteral(statement.type)) {
        names.push(statement.name.text);
      }
    }
    if (names.length) found[name] = names.sort();
  }
  return found;
}

function main() {
  const found = findContracts();
  if (process.argv.includes('--list')) {
    console.log(JSON.stringify(found, null, 2));
    return 0;
  }

  const allow = JSON.parse(fs.readFileSync(allowlistPath, 'utf8'));
  const listed = new Map();
  for (const [file, entry] of Object.entries(allow.migrating ?? {})) {
    for (const type of entry.types) listed.set(`${file}:${type}`, `migrating (${entry.until})`);
  }
  for (const [key, reason] of Object.entries(allow.viewModels ?? {})) listed.set(key, reason);

  const problems = [];
  const present = new Set();
  for (const [file, types] of Object.entries(found)) {
    for (const type of types) {
      const key = `${file}:${type}`;
      present.add(key);
      if (!listed.has(key)) {
        problems.push(
          `src/api/${file}: \`${type}\` is a new handwritten response contract. Use the generated ` +
            `type from @familiar/api-client (pnpm generate:api if it is missing), or, if it is UI ` +
            `state rather than a response, list it under "viewModels" with the reason.`,
        );
      }
    }
  }
  for (const key of listed.keys()) {
    if (!present.has(key)) {
      problems.push(
        `api-contracts.allowlist.json: \`${key}\` is listed but is no longer a handwritten contract ` +
          `there. Remove the entry, so the list only shrinks.`,
      );
    }
  }

  if (problems.length) {
    console.error(`API contract check failed (ADR-0173):\n  ${problems.join('\n  ')}`);
    return 1;
  }
  const migrating = [...listed.values()].filter((v) => v.startsWith('migrating')).length;
  console.log(
    `API contracts OK: ${present.size} handwritten, ${migrating} of them waiting to migrate (ADR-0173).`,
  );
  return 0;
}

process.exit(main());
