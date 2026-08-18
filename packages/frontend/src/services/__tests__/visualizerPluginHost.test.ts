/**
 * ADR-0034: the half that fetches and evaluates.
 *
 * The bundles here are written the way the samples are built — an IIFE reading `window.Familiar` at
 * its top level and registering as a side effect — because "does this loader run the artifacts that
 * actually exist" is the only question worth asking of it.
 */
// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { loadVisualizerPlugins, installFamiliarGlobal } from '../visualizerPluginHost';
import { useVisualizerPluginStore } from '../../stores/visualizerPluginStore';
import { visualizerRegistry } from '../../components/Visualizer/types';

const manifest = (over: Record<string, unknown> = {}) => ({
  id: 'demo',
  name: 'Demo',
  version: '1.0.0',
  type: 'visualizer',
  main: 'dist/index.js',
  familiar: { apiVersion: 1 },
  ...over,
});

/** An IIFE of the shape rollup emits for these plugins. */
const bundleFor = (id: string) => `
  (function () {
    var F = window.Familiar;
    F.registerVisualizer({ id: ${JSON.stringify(id)}, name: 'Demo', description: 'd', usesMetadata: false },
      function () { return null; });
  })();
`;

/** Serves an index and a set of bundles; anything else 404s. */
function server(plugins: unknown[], bundles: Record<string, string>) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const path = new URL(String(input)).pathname;
    if (path.endsWith('/plugins/index.json')) {
      return new Response(JSON.stringify({ plugins }), { status: 200 });
    }
    const match = /\/plugins\/(shipped|local)\/([^/]+)\/bundle\.js$/.exec(path);
    if (match && bundles[match[2]] !== undefined) {
      return new Response(bundles[match[2]], { status: 200 });
    }
    return new Response('not found', { status: 404 });
  });
}

describe('loadVisualizerPlugins', () => {
  beforeEach(() => {
    visualizerRegistry.clear();
    useVisualizerPluginStore.setState({ records: [], scanned: false });
    delete window.Familiar;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('installs the global the sample bundles destructure', () => {
    installFamiliarGlobal();
    // Named exactly as the built `dist/index.js` files read them. A rename here is a breaking
    // change to every plugin already built, which is what `apiVersion` exists to announce.
    expect(window.Familiar).toMatchObject({
      React: expect.anything(),
      THREE: expect.anything(),
      ReactThreeFiber: expect.anything(),
      Drei: expect.anything(),
      registerVisualizer: expect.any(Function),
      apiVersion: 1,
    });
    expect(window.Familiar?.hooks.useAudioAnalyser).toBeInstanceOf(Function);
  });

  it('does not hand out registerBrowser — browsers are out of scope (point 9)', () => {
    installFamiliarGlobal();
    expect(window.Familiar).not.toHaveProperty('registerBrowser');
  });

  it('loads a plugin and registers it', async () => {
    vi.stubGlobal('fetch', server([{ source: 'local', manifest: manifest() }], { demo: bundleFor('demo') }));

    await loadVisualizerPlugins([]);

    expect(visualizerRegistry.has('demo')).toBe(true);
    expect(useVisualizerPluginStore.getState().records).toEqual([
      { id: 'demo', name: 'Demo', source: 'local', status: 'loaded' },
    ]);
  });

  it('never fetches the bundle of a plugin refused on its manifest', async () => {
    const fetchMock = server(
      [{ source: 'local', manifest: manifest({ familiar: { apiVersion: 99 } }) }],
      { demo: bundleFor('demo') }
    );
    vi.stubGlobal('fetch', fetchMock);

    await loadVisualizerPlugins([]);

    const requested = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(requested.filter((u) => u.includes('bundle.js'))).toHaveLength(0);
    expect(visualizerRegistry.has('demo')).toBe(false);
  });

  it('records a bundle that throws instead of letting it take the page down', async () => {
    vi.stubGlobal('fetch', server([{ source: 'local', manifest: manifest() }], { demo: 'throw new Error("boom");' }));

    await expect(loadVisualizerPlugins([])).resolves.toBeUndefined();

    expect(useVisualizerPluginStore.getState().records[0]).toMatchObject({
      status: 'refused',
      refusal: 'threw',
    });
  });

  it('catches a bundle that registers nothing — the silent failure', async () => {
    vi.stubGlobal('fetch', server([{ source: 'local', manifest: manifest() }], { demo: '(function(){})();' }));

    await loadVisualizerPlugins([]);

    expect(useVisualizerPluginStore.getState().records[0]).toMatchObject({
      status: 'refused',
      refusal: 'registered-nothing',
    });
  });

  it('catches an id that does not match what the bundle registered', async () => {
    vi.stubGlobal('fetch', server([{ source: 'local', manifest: manifest() }], { demo: bundleFor('something-else') }));

    await loadVisualizerPlugins([]);

    expect(useVisualizerPluginStore.getState().records[0]).toMatchObject({
      refusal: 'registered-nothing',
    });
  });

  it('records a bundle that cannot be read', async () => {
    vi.stubGlobal('fetch', server([{ source: 'local', manifest: manifest() }], {}));

    await loadVisualizerPlugins([]);

    expect(useVisualizerPluginStore.getState().records[0]).toMatchObject({
      status: 'refused',
      refusal: 'fetch-failed',
    });
  });

  it('treats a host with no plugin index as having none — that is every browser', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('not found', { status: 404 }))
    );

    await loadVisualizerPlugins([]);

    const state = useVisualizerPluginStore.getState();
    expect(state.records).toEqual([]);
    expect(state.scanned).toBe(true);
  });

  it('survives a host that is not there at all', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      })
    );

    await expect(loadVisualizerPlugins([])).resolves.toBeUndefined();
    expect(useVisualizerPluginStore.getState().records).toEqual([]);
  });

  it('refuses a plugin that would overwrite a built-in', async () => {
    vi.stubGlobal('fetch', server([{ source: 'local', manifest: manifest({ id: 'lyrics' }) }], { lyrics: bundleFor('lyrics') }));

    await loadVisualizerPlugins(['lyrics']);

    expect(visualizerRegistry.has('lyrics')).toBe(false);
    expect(useVisualizerPluginStore.getState().records[0]).toMatchObject({ refusal: 'reserved-id' });
  });
});

describe('markFailed', () => {
  it('marks a loaded plugin that crashed, and ignores an id it does not know', () => {
    useVisualizerPluginStore.setState({
      records: [{ id: 'demo', name: 'Demo', source: 'local', status: 'loaded' }],
      scanned: true,
    });

    useVisualizerPluginStore.getState().markFailed('reactive-terrain', 'a built-in crashed');
    expect(useVisualizerPluginStore.getState().records[0].status).toBe('loaded');

    useVisualizerPluginStore.getState().markFailed('demo', 'null is not an object');
    expect(useVisualizerPluginStore.getState().records[0]).toMatchObject({
      status: 'failed',
      detail: 'null is not an object',
    });
  });
});

/**
 * ADR-0064: affinity has to survive the trip from a plugin's manifest to the catalog the native
 * host reads. Nothing tested `publishCatalog` at all before this.
 */
describe('publishCatalog', () => {
  beforeEach(() => {
    visualizerRegistry.clear();
    useVisualizerPluginStore.setState({ records: [], scanned: false });
    delete window.Familiar;
    delete (window as unknown as Record<string, unknown>).__familiarVisualizers;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function catalog() {
    const read = (window as unknown as Record<string, () => string>).__familiarVisualizers;
    expect(read).toBeInstanceOf(Function);
    return JSON.parse(read());
  }

  const AFFINITY = { tags: ['ambient'], ranges: [{ feature: 'energy', maximum: 0.4 }] };

  it('carries a plugin affinity declared in its manifest', async () => {
    vi.stubGlobal(
      'fetch',
      server([{ source: 'local', manifest: manifest({ affinity: AFFINITY }) }], {
        demo: bundleFor('demo'),
      })
    );

    await loadVisualizerPlugins([]);

    const entry = catalog().visualizers.find((v: { id: string }) => v.id === 'demo');
    // **The asymmetry this covers:** the bundle calls `registerVisualizer` with its own metadata
    // and cannot see its manifest, so without an explicit merge the affinity would be parsed,
    // stored, and never reach the catalog — every plugin ranking neutral for ever.
    expect(entry.affinity).toEqual(AFFINITY);
  });

  it('leaves affinity absent for a plugin that declares none', async () => {
    vi.stubGlobal(
      'fetch',
      server([{ source: 'local', manifest: manifest() }], { demo: bundleFor('demo') })
    );

    await loadVisualizerPlugins([]);

    const entry = catalog().visualizers.find((v: { id: string }) => v.id === 'demo');
    expect(entry.affinity).toBeUndefined();
    expect(entry.source).toBe('local');
  });

  it('records an unusable affinity block as ignored, and still loads the plugin', async () => {
    vi.stubGlobal(
      'fetch',
      server([{ source: 'local', manifest: manifest({ affinity: { tags: [7] } }) }], {
        demo: bundleFor('demo'),
      })
    );

    await loadVisualizerPlugins([]);

    const record = useVisualizerPluginStore
      .getState()
      .records.find((r) => r.id === 'demo');
    expect(record?.status).toBe('loaded');
    expect(record?.ignored?.length).toBeGreaterThan(0);
  });
});
