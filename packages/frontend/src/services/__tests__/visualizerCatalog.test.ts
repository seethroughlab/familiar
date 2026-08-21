import { describe, it, expect, beforeEach, vi } from 'vitest';
import { loadVisualizerCatalog, normaliseEntry } from '../visualizerCatalog';
import { useVisualizerPluginStore } from '../../stores/visualizerPluginStore';

/**
 * The catalog reads two listings written by two different producers, and **assuming they had the
 * same shape emptied the picker on every Apple client**.
 *
 * The native host (`VisualizerPlugins.indexJSON`) splices each manifest through without parsing it,
 * so its rows *wrap* the manifest: `{source, folder, manifest: {…}}`, or
 * `{source, folder, problem: "…"}` when the folder could not be read. The web build generates a
 * listing that *is* an array of manifests. Reading `id` off the row gave `undefined` for every
 * native entry, every visualizer was refused as malformed, and the app said
 * "No visualizer available" for all seven.
 *
 * Nothing covered this. `/embed` and `/visualizer` have no automated coverage at all, so a shape
 * mismatch between the two repos could only be found by opening the app — which is how it was.
 * These fixtures are copied from real output on both sides.
 */

/** Real rows from `VisualizerPlugins.indexJSON`, captured from the macOS app's own folder. */
const NATIVE_INDEX = {
  apiVersion: 1,
  plugins: [
    {
      source: 'local',
      folder: 'beat-tiles',
      manifest: {
        name: 'Beat Tiles',
        id: 'beat-tiles',
        version: '1.0.0',
        type: 'visualizer',
        description: 'Reflective tiles pulsing with the beat, over the album cover.',
        main: 'index.html',
        familiar: { apiVersion: 1 },
        icon: 'Grid3x3',
        affinity: { tags: ['danceable', 'drums'], ranges: [] },
      },
    },
    {
      source: 'local',
      folder: 'spectrum',
      manifest: {
        name: 'Spectrum',
        id: 'spectrum',
        version: '1.0.0',
        type: 'visualizer',
        main: 'index.html',
        familiar: { apiVersion: 1 },
      },
    },
    // A folder the host could not read. It must still be reported, by folder name.
    { source: 'local', folder: 'half-unzipped', problem: 'half-unzipped: the manifest is not valid JSON.' },
  ],
};

/** The web build's listing: an array of manifests, no wrapper. */
const WEB_INDEX = {
  plugins: [
    {
      name: 'Beat Tiles',
      id: 'beat-tiles',
      version: '1.0.0',
      type: 'visualizer',
      main: 'index.html',
      familiar: { apiVersion: 1 },
      icon: 'Grid3x3',
      affinity: { tags: ['danceable'], ranges: [] },
    },
  ],
};

function serve(url: string, body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (requested: string) =>
      String(requested).includes(url)
        ? { ok: true, json: async () => body }
        : { ok: false, json: async () => ({}) }
    )
  );
}

describe('normaliseEntry', () => {
  it('unwraps a native row', () => {
    const { manifest, folder, problem } = normaliseEntry(NATIVE_INDEX.plugins[0]);
    expect(manifest?.id).toBe('beat-tiles');
    expect(folder).toBe('beat-tiles');
    expect(problem).toBeNull();
  });

  it('takes a web row as the manifest itself', () => {
    const { manifest, problem } = normaliseEntry(WEB_INDEX.plugins[0]);
    expect(manifest?.id).toBe('beat-tiles');
    expect(problem).toBeNull();
  });

  it('carries a native problem through, with the folder as its only label', () => {
    const { manifest, folder, problem } = normaliseEntry(NATIVE_INDEX.plugins[2]);
    expect(manifest).toBeNull();
    expect(folder).toBe('half-unzipped');
    expect(problem).toContain('not valid JSON');
  });
});

describe('loadVisualizerCatalog', () => {
  beforeEach(() => {
    useVisualizerPluginStore.getState().setRecords([]);
    vi.unstubAllGlobals();
  });

  it('reads the native listing — the case that was broken', async () => {
    serve('plugins/index.json', NATIVE_INDEX);

    const catalog = await loadVisualizerCatalog();

    // The regression: this was [] and the app rendered "No visualizer available".
    expect(catalog.map((entry) => entry.id)).toEqual(['beat-tiles', 'spectrum']);
    expect(catalog[0].name).toBe('Beat Tiles');
    expect(catalog[0].affinity?.tags).toContain('danceable');
    expect(catalog[0].url).toContain('plugins/local/beat-tiles/index.html');
  });

  it('reports an unreadable folder rather than dropping it', async () => {
    serve('plugins/index.json', NATIVE_INDEX);
    await loadVisualizerCatalog();

    // ADR-0034 point 7: a refused plugin says so, by name, rather than vanishing.
    const refused = useVisualizerPluginStore.getState().records.filter((r) => r.status !== 'loaded');
    expect(refused).toHaveLength(1);
    expect(refused[0].name).toBe('half-unzipped');
    expect(refused[0].detail).toContain('not valid JSON');
  });

  it('reads the web listing', async () => {
    serve('/visualizers/index.json', WEB_INDEX);

    const catalog = await loadVisualizerCatalog();

    expect(catalog.map((entry) => entry.id)).toEqual(['beat-tiles']);
    expect(catalog[0].url).toContain('/visualizers/beat-tiles/index.html');
  });

  it('refuses a manifest declaring an apiVersion this host does not implement', async () => {
    serve('plugins/index.json', {
      apiVersion: 1,
      plugins: [
        { source: 'local', folder: 'future', manifest: { id: 'future', name: 'Future', familiar: { apiVersion: 99 } } },
      ],
    });

    expect(await loadVisualizerCatalog()).toEqual([]);
    const [record] = useVisualizerPluginStore.getState().records;
    expect(record.refusal).toBe('api-version');
    expect(record.detail).toContain('99');
  });
});
