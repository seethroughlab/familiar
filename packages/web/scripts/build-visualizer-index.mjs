/**
 * Build `public/visualizers/index.json` from the plugin folders beside it.
 *
 * The native host has `VisualizerSchemeHandler` to enumerate plugin folders on disk; a browser has
 * no directory listing, so the same information has to be a file. Generated rather than written by
 * hand for the reason ADR-0034 gives about the two sources: a list maintained separately from the
 * folders drifts, and a visualizer that is present but unlisted is unreachable.
 */
import { readdirSync, readFileSync, writeFileSync, statSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', 'public', 'visualizers');

const plugins = readdirSync(root)
  .filter((name) => statSync(join(root, name)).isDirectory())
  .map((folder) => {
    const manifest = JSON.parse(readFileSync(join(root, folder, 'familiar-plugin.json'), 'utf8'));
    return { ...manifest, folder, source: 'shipped' };
  })
  .sort((a, b) => a.id.localeCompare(b.id));

writeFileSync(join(root, 'index.json'), JSON.stringify({ plugins }, null, 2) + '\n');
console.log(`[visualizer-index] ${plugins.length} plugins: ${plugins.map((p) => p.id).join(', ')}`);
