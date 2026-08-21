/**
 * What visualizers exist, and where their documents are (ADR-0087, ADR-0088).
 *
 * **This replaces `visualizerPluginHost`, and the difference is that it evaluates nothing.** That
 * module installed `window.Familiar` with React, THREE, `@react-three/fiber` and drei on it, then
 * ran each plugin's bundle with `new Function` inside this page so it could call
 * `registerVisualizer`. A plugin is now a document loaded in a sandboxed iframe, so the host's only
 * job is to say which folders exist and what their manifests claim.
 *
 * Nothing here can run plugin code. That is the point, and it is why this file is a quarter the
 * size of the one it replaces.
 */
import { useVisualizerPluginStore, type VisualizerPluginRecord } from '../stores/visualizerPluginStore';
import type { VisualizerPluginSource } from './visualizerPlugins';
import { createLogger } from '../utils/logger';

const log = createLogger('Visualizers');

/** The event contract's version, not any library's (ADR-0087 point 9). */
export const VISUALIZER_API_VERSION = 1;

export interface VisualizerAffinity {
  tags?: string[];
  ranges?: Array<{ feature: string; minimum?: number; maximum?: number }>;
}

/** A visualizer this host can show. */
export interface CatalogEntry {
  id: string;
  name: string;
  description?: string;
  icon?: string;
  affinity?: VisualizerAffinity;
  /** `shipped` (in the app bundle) or `local` (the user's drop-in folder) — ADR-0034 point 4. */
  source: VisualizerPluginSource;
  /** Absolute URL of the plugin's document. What the iframe is pointed at. */
  url: string;
}

interface RawManifest {
  id?: unknown;
  name?: unknown;
  description?: unknown;
  icon?: unknown;
  affinity?: unknown;
  main?: unknown;
  source?: unknown;
  folder?: unknown;
  familiar?: { apiVersion?: unknown };
}

/**
 * Where a listing might be, most specific first.
 *
 * The native host serves `plugins/index.json` from `VisualizerSchemeHandler`, which enumerates real
 * directories. A browser has no directory to enumerate, so the web build generates
 * `visualizers/index.json` beside the folders. One consumer, two producers — the shapes agree
 * because both are the manifests plus where they were found.
 */
const INDEX_URLS = ['plugins/index.json', '/visualizers/index.json'];

function resolve(path: string): string {
  return new URL(path, window.location.href).toString();
}

async function fetchIndex(): Promise<{ plugins: RawManifest[]; base: string } | null> {
  for (const candidate of INDEX_URLS) {
    try {
      // Not the API client: these are the app's own assets, and the client would rewrite the URL
      // onto the server's origin and fetch a route that does not exist.
      // eslint-disable-next-line no-restricted-globals -- see above
      const response = await fetch(resolve(candidate), { cache: 'no-store' });
      if (!response.ok) continue;
      const body = (await response.json()) as { plugins?: unknown };
      if (!Array.isArray(body.plugins)) continue;
      return { plugins: body.plugins as RawManifest[], base: candidate };
    } catch {
      // Try the next one. A browser with no drop-in directory is not an error.
    }
  }
  return null;
}

/**
 * Where a plugin's document lives, given how it was listed.
 *
 * Derived rather than carried in the index, so the native side keeps splicing manifests through
 * verbatim (`VisualizerPlugins.indexJSON`) without learning about URLs.
 */
function documentURL(manifest: RawManifest, base: string): string | null {
  const id = typeof manifest.id === 'string' ? manifest.id : null;
  const main = typeof manifest.main === 'string' ? manifest.main : 'index.html';
  if (!id) return null;

  if (base.startsWith('plugins/')) {
    const source = typeof manifest.source === 'string' ? manifest.source : 'local';
    return resolve(`plugins/${source}/${id}/${main}`);
  }
  return resolve(`/visualizers/${id}/${main}`);
}

/**
 * Read the listing and turn it into what the picker and the ranking need.
 *
 * A manifest that cannot be used is *reported*, not dropped: `visualizerPluginStore` keeps the
 * refusals so the picker can show a named row saying why, which is ADR-0034 point 7's rule that a
 * refused plugin says so rather than vanishing.
 */
export async function loadVisualizerCatalog(): Promise<CatalogEntry[]> {
  const listing = await fetchIndex();
  if (!listing) {
    useVisualizerPluginStore.getState().setRecords([]);
    return [];
  }

  const entries: CatalogEntry[] = [];
  const records: VisualizerPluginRecord[] = [];

  for (const manifest of listing.plugins) {
    const id = typeof manifest.id === 'string' ? manifest.id : null;
    const name = typeof manifest.name === 'string' ? manifest.name : ((manifest.folder as string) ?? 'a plugin');
    const source: VisualizerPluginSource = manifest.source === 'shipped' ? 'shipped' : 'local';

    const declared = manifest.familiar?.apiVersion;
    if (typeof declared === 'number' && declared !== VISUALIZER_API_VERSION) {
      records.push({
        id, name, source, status: 'refused', refusal: 'api-version',
        detail: `declares apiVersion ${declared}; this host implements ${VISUALIZER_API_VERSION}`,
      });
      continue;
    }

    const url = documentURL(manifest, listing.base);
    if (!id || !url) {
      records.push({
        id, name, source, status: 'refused', refusal: 'malformed',
        detail: 'the manifest has no usable id',
      });
      continue;
    }

    entries.push({
      id,
      name,
      description: typeof manifest.description === 'string' ? manifest.description : undefined,
      icon: typeof manifest.icon === 'string' ? manifest.icon : undefined,
      affinity: (manifest.affinity as VisualizerAffinity) ?? undefined,
      source,
      url,
    });
    records.push({ id, name, source, status: 'loaded' });
  }

  const refused = records.filter((r) => r.status !== 'loaded');
  log.info(`${entries.length} visualizer(s) available${refused.length ? `, ${refused.length} refused` : ''}`);
  for (const record of refused) log.warn(`Refused ${record.id ?? 'a plugin'}: ${record.detail}`);

  useVisualizerPluginStore.getState().setRecords(records);
  return entries;
}

/** The function name the native host calls to find out what this page can draw. */
const CATALOG_NAME = '__familiarVisualizers';

/**
 * Publish the catalog for a native host to read (ADR-0034 point 7).
 *
 * Unchanged in shape from the version that read the registry: embedded, the picker is a native
 * menu, and a menu that does not know what is installed makes a working plugin unreachable. What
 * changed is where the list comes from — a manifest listing rather than whatever managed to
 * register itself.
 */
export function publishCatalog(entries: CatalogEntry[]): void {
  const records = useVisualizerPluginStore.getState().records;
  const payload = {
    apiVersion: VISUALIZER_API_VERSION,
    visualizers: entries.map((entry) => ({
      id: entry.id,
      name: entry.name,
      description: entry.description,
      source: entry.source,
      // What each suits (ADR-0064). The server cannot know what is installed on a device, so the
      // candidates and their declarations travel from here.
      affinity: entry.affinity,
    })),
    problems: records
      .filter((r) => r.status !== 'loaded')
      .map((r) => ({ id: r.id, name: r.name, detail: r.detail ?? '' })),
  };

  (window as unknown as Record<string, unknown>)[CATALOG_NAME] = () => JSON.stringify(payload);
}
