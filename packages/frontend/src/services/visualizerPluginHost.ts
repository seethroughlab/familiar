/**
 * Loads drop-in visualizer bundles into the page (ADR-0034).
 *
 * The impure half of `visualizerPlugins.ts`: it imports React, three.js, `@react-three/fiber` and
 * `@react-three/drei` so it can hand them to a plugin on `window.Familiar` (point 3), fetches what
 * the native host lists, and evaluates the bundles that survive review.
 *
 * **Where the bundles come from is not this file's business.** It asks the document's own origin
 * for `plugins/index.json` and gets whatever the host chose to list — shipped resources, a local
 * `Visualizers/` directory, or on a plain web page nothing at all, because a browser has no such
 * directory and ADR-0034 point 4 admits no third source. A 404 here is the ordinary case, not an
 * error.
 */
import React from 'react';
import * as THREE from 'three';
import * as ReactThreeFiber from '@react-three/fiber';
// **This one import costs 1.59 MB on top of what drei already costs**, measured: the inlined
// visualizer document is 1,782 kB without it and 3,375 kB with it.
//
// The earlier version of this comment said "nothing pulls drei in", and that was wrong.
// `ScrollingLyrics` — registered as `lyrics` — renders `LyricWordField`, which imports drei's
// `Text`; `LyricStorm` now renders the same field. So drei ships either way. What `import *` adds
// is the *rest* of the library, because a namespace import cannot be tree-shaken, and ADR-0034
// point 3 promises plugins the whole of drei rather than the one component this repo happens to
// use.
import * as Drei from '@react-three/drei';

import { createLogger } from '../utils/logger';
import {
  registerVisualizer,
  getVisualizer,
  getVisualizers,
  visualizerRegistry,
} from '../components/Visualizer/types';
import { useAudioAnalyser, getAudioData } from '../hooks/useAudioAnalyser';
import { useArtworkPalette } from '../components/Visualizer/hooks/useArtworkPalette';
import { useBeatSync, getBeatPhase, getBeatSine } from '../components/Visualizer/hooks/useBeatSync';
import { useLyricTiming, getUpcomingLyrics, getWordTiming } from '../components/Visualizer/hooks/useLyricTiming';
import { useVisualizerPluginStore, type VisualizerPluginRecord } from '../stores/visualizerPluginStore';
import {
  reviewPlugins,
  VISUALIZER_API_VERSION,
  type DiscoveredPlugin,
  type VisualizerPluginManifest,
  type VisualizerPluginSource,
} from './visualizerPlugins';

const log = createLogger('VisualizerPlugins');

/**
 * The global a bundle reads at its top level.
 *
 * **Matches the shelved loader's shape**, because the sample bundles destructure it by name and
 * `dist/` is what gets loaded — renaming a key here is a breaking change to every built plugin, and
 * the version that would announce it is `VISUALIZER_API_VERSION`.
 *
 * `registerBrowser` and the API client are the two things that are *not* carried over. Library
 * browsers are out of scope (ADR-0034 point 9) and are refused before their bundle is ever
 * evaluated, so nothing that runs here can want either.
 */
export interface FamiliarVisualizerAPI {
  React: typeof React;
  THREE: typeof THREE;
  ReactThreeFiber: typeof ReactThreeFiber;
  Drei: typeof Drei;
  registerVisualizer: typeof registerVisualizer;
  hooks: {
    useAudioAnalyser: typeof useAudioAnalyser;
    getAudioData: typeof getAudioData;
    useArtworkPalette: typeof useArtworkPalette;
    useBeatSync: typeof useBeatSync;
    getBeatPhase: typeof getBeatPhase;
    getBeatSine: typeof getBeatSine;
    useLyricTiming: typeof useLyricTiming;
    getUpcomingLyrics: typeof getUpcomingLyrics;
    getWordTiming: typeof getWordTiming;
  };
  apiVersion: number;
}

declare global {
  interface Window {
    Familiar?: FamiliarVisualizerAPI;
  }
}

/** Installed once. Idempotent because the loader may be invoked again on a rescan. */
export function installFamiliarGlobal(): void {
  if (window.Familiar) return;
  window.Familiar = {
    React,
    THREE,
    ReactThreeFiber,
    Drei,
    registerVisualizer,
    hooks: {
      useAudioAnalyser,
      getAudioData,
      useArtworkPalette,
      useBeatSync,
      getBeatPhase,
      getBeatSine,
      useLyricTiming,
      getUpcomingLyrics,
      getWordTiming,
    },
    apiVersion: VISUALIZER_API_VERSION,
  };
}

interface PluginIndex {
  plugins?: unknown;
}

function url(path: string): string {
  return new URL(path, window.location.href).toString();
}

/**
 * Ask the host what it has. Returns an empty list rather than throwing when there is no host —
 * which is every plain browser, and is not a failure.
 */
async function discover(): Promise<DiscoveredPlugin[] | null> {
  let response: Response;
  try {
    // Not the API client: this is the app's own custom URL scheme, served from the app bundle by
    // `VisualizerSchemeHandler`. The api client would rewrite it onto the server's origin and fetch
    // a route that does not exist.
    // eslint-disable-next-line no-restricted-globals -- see above
    response = await fetch(url('plugins/index.json'), { cache: 'no-store' });
  } catch {
    return null;
  }
  if (!response.ok) return null;

  let body: PluginIndex;
  try {
    body = (await response.json()) as PluginIndex;
  } catch {
    log.warn('The plugin index is not valid JSON. Treating it as empty.');
    return null;
  }

  if (!Array.isArray(body.plugins)) return null;

  return body.plugins.flatMap((entry): DiscoveredPlugin[] => {
    if (typeof entry !== 'object' || entry === null) return [];
    const record = entry as { source?: unknown; manifest?: unknown; folder?: unknown; problem?: unknown };
    const source: VisualizerPluginSource = record.source === 'local' ? 'local' : 'shipped';
    return [
      {
        source,
        manifest: record.manifest,
        folder: typeof record.folder === 'string' ? record.folder : undefined,
        problem: typeof record.problem === 'string' ? record.problem : undefined,
      },
    ];
  });
}

/**
 * Fetch and evaluate one bundle.
 *
 * `new Function` rather than `import()`: the bundles are IIFEs that read `window.Familiar` at their
 * top level and register as a side effect (ADR-0034 point 1). Dynamic import would need an ES
 * module, which is not what any of them build to.
 *
 * The isolation this buys over `eval` is nominal — the bundle runs with full access to the
 * document. That is accepted rather than defended against: ADR-0034's tradeoff section says the app
 * executes code it did not ship, and the actual containment is the web view, which has a null audio
 * engine and no credentials beyond a server URL and profile id.
 */
async function evaluate(
  manifest: VisualizerPluginManifest,
  source: VisualizerPluginSource
): Promise<VisualizerPluginRecord> {
  const base = { id: manifest.id, name: manifest.name, source } as const;

  let code: string;
  try {
    // Same reason as the index above: the app's own scheme, not the server. Also a text body rather
    // than JSON, which the api client's interceptors are not shaped for.
    // eslint-disable-next-line no-restricted-globals -- see above
    const response = await fetch(url(`plugins/${source}/${manifest.id}/bundle.js`), { cache: 'no-store' });
    if (!response.ok) {
      return { ...base, status: 'refused', refusal: 'fetch-failed', detail: `Could not read ${manifest.main} (HTTP ${response.status}).` };
    }
    code = await response.text();
  } catch (error) {
    return {
      ...base,
      status: 'refused',
      refusal: 'fetch-failed',
      detail: `Could not read ${manifest.main}: ${error instanceof Error ? error.message : String(error)}`,
    };
  }

  try {
    new Function(code)();
  } catch (error) {
    return {
      ...base,
      status: 'refused',
      refusal: 'threw',
      detail: `The bundle threw while loading: ${error instanceof Error ? error.message : String(error)}`,
    };
  }

  // **Checked, because a bundle that registers nothing fails silently otherwise.** It evaluates
  // cleanly, the picker shows no new entry, and there is no error anywhere to explain it — which is
  // the exact failure shape this codebase keeps producing. The usual cause is a manifest whose `id`
  // does not match the id the bundle passes to `registerVisualizer`.
  const registered = getVisualizer(manifest.id);
  if (!registered) {
    return {
      ...base,
      status: 'refused',
      refusal: 'registered-nothing',
      detail: `The bundle loaded but registered no visualizer with the id "${manifest.id}".`,
    };
  }

  // **The manifest declares affinity; the bundle registers metadata; neither knows the other**
  // (ADR-0064 point 1). A plugin's `registerVisualizer` call is written against the same API a
  // built-in uses and has no access to its own manifest, so the two halves are joined here — after
  // the bundle has run, which is the first moment both exist. Without this the catalog would carry
  // affinity for the built-ins only, and every plugin would rank neutral for ever.
  if (manifest.affinity) {
    visualizerRegistry.set(manifest.id, {
      ...registered,
      metadata: { ...registered.metadata, affinity: manifest.affinity },
    });
  }

  return { ...base, status: 'loaded' };
}

/**
 * Install the global, review what the host lists, and load what survives.
 *
 * Resolves once every plugin has been settled one way or the other, so the caller can mount after
 * it and have the picker already complete. Never rejects: a plugin failing is a row in the picker,
 * not an error the page has to handle.
 */
export async function loadVisualizerPlugins(builtInIds: Iterable<string>): Promise<void> {
  installFamiliarGlobal();

  const discovered = await discover();
  if (discovered === null) {
    // No host listing them. Not an error — a browser has no drop-in directory.
    useVisualizerPluginStore.getState().setRecords([]);
    return;
  }

  const verdicts = reviewPlugins(discovered, { builtInIds });
  const records: VisualizerPluginRecord[] = [];

  // **Sequential, not `Promise.all`.** `reviewPlugins` decided which id belongs to which plugin
  // assuming they load in that order; two bundles racing to `registerVisualizer` could land in the
  // other order and the picker would describe the one that lost.
  for (const verdict of verdicts) {
    if (verdict.ok) {
      const record = await evaluate(verdict.manifest, verdict.source);
      // Carried whatever the outcome: a plugin refused for an unrelated reason still had its
      // affinity read, and an author fixing one problem should see the other already listed.
      records.push(verdict.ignored.length > 0 ? { ...record, ignored: verdict.ignored } : record);
    } else {
      records.push({
        id: verdict.id,
        name: verdict.name,
        source: verdict.source,
        status: 'refused',
        refusal: verdict.refusal,
        detail: verdict.detail,
      });
    }
  }

  const loaded = records.filter((r) => r.status === 'loaded').length;
  if (records.length > 0) {
    log.info(`${loaded} of ${records.length} visualizer plugin(s) loaded`);
    for (const record of records) {
      if (record.status !== 'loaded') log.warn(`Refused ${record.id ?? 'a plugin'}: ${record.detail}`);
    }
  }

  useVisualizerPluginStore.getState().setRecords(records);
  publishCatalog();
}

/** The function name the native host calls to find out what this page can actually draw. */
const CATALOG_NAME = '__familiarVisualizers';

/**
 * Publish what is in the registry, for a native host to read (ADR-0034 point 7).
 *
 * **Why this exists at all.** Embedded, the picker is a native menu, and that menu was a fixed list
 * of the four compile-time visualizers — so a plugin could load perfectly and still be unreachable,
 * which is the same defect as an affordance with no destination, pointing the other way. The menu
 * has to be told.
 *
 * **A function on `window`, read with `evaluateJavaScript` — not a `WKScriptMessageHandler`.** The
 * visualizer surface deliberately registers no message handler: it draws what it is sent and has
 * nothing to say unprompted (ADR-0033). That is still true. This is the host *asking*, over exactly
 * the channel it already uses to probe for the analysis sink, so no new seam is opened and the
 * two-message cap ADR-0020 point 2 sets on the *other* bridge is untouched.
 *
 * Returns a JSON string rather than an object: `evaluateJavaScript` bridges a string losslessly,
 * and a dictionary of dictionaries arrives as `Any` that has to be picked apart by hand.
 */
export function publishCatalog(): void {
  const records = useVisualizerPluginStore.getState().records;
  const bySource = new Map(records.filter((r) => r.id).map((r) => [r.id as string, r]));

  const payload = {
    apiVersion: VISUALIZER_API_VERSION,
    visualizers: getVisualizers().map(({ metadata }) => ({
      id: metadata.id,
      name: metadata.name,
      description: metadata.description,
      // Absent for the compile-time visualizers, which is how the host tells them apart without
      // being given the list twice.
      source: bySource.get(metadata.id)?.source,
      // What each visualizer suits (ADR-0064). The native host cannot ask the server to rank
      // without this: the server has no way to know what is installed on a device, so the
      // candidates and their declarations travel from here.
      affinity: metadata.affinity,
    })),
    problems: records
      .filter((r) => r.status !== 'loaded')
      .map((r) => ({ id: r.id, name: r.name, detail: r.detail ?? '' })),
  };

  (window as unknown as Record<string, unknown>)[CATALOG_NAME] = () => JSON.stringify(payload);
}
