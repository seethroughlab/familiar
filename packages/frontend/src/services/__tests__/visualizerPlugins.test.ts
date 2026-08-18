/**
 * ADR-0034: what gets loaded, and what gets refused before it can run.
 *
 * The manifests here are the real shape — copied from `familiar-plugin-non-places` and
 * `familiar-plugin-lyric-pulse` — because a test against an invented shape would pass while the
 * actual sample plugins failed.
 */
import { describe, it, expect } from 'vitest';
import {
  parseManifest,
  reviewPlugins,
  VISUALIZER_API_VERSION,
  type DiscoveredPlugin,
} from '../visualizerPlugins';

const nonPlaces = {
  name: 'Non-Places',
  id: 'non-places',
  version: '0.1.0-alpha.1',
  type: 'visualizer',
  description: "Surreal 3D models drifting through fog, inspired by the game 'Islands: Non-Places'",
  author: { name: 'Familiar', url: 'https://github.com/jeffweisbein' },
  main: 'dist/index.js',
  familiar: { apiVersion: 1 },
  icon: 'Building2',
};

const timeline = {
  name: 'Timeline',
  id: 'timeline',
  version: '0.1.0-alpha.1',
  type: 'browser',
  main: 'dist/index.js',
  familiar: { apiVersion: 1 },
  icon: 'Calendar',
};

function local(manifest: unknown): DiscoveredPlugin {
  return { source: 'local', manifest };
}
function shipped(manifest: unknown): DiscoveredPlugin {
  return { source: 'shipped', manifest };
}

describe('parseManifest', () => {
  it('accepts a real sample manifest', () => {
    const result = parseManifest(nonPlaces);
    expect(result).toEqual({
      manifest: expect.objectContaining({
        id: 'non-places',
        name: 'Non-Places',
        type: 'visualizer',
        main: 'dist/index.js',
        familiar: { apiVersion: 1 },
        icon: 'Building2',
      }),
      // A real sample manifest predates `affinity` and declares none — which is not a problem,
      // so nothing is ignored (ADR-0064 point 2: the block is optional and its absence is silent).
      ignored: [],
    });
  });

  it.each([
    ['not an object', 'nope'],
    ['an array', []],
    ['no id', { name: 'X', type: 'visualizer', main: 'a.js', version: '1' }],
    ['no name', { id: 'x', type: 'visualizer', main: 'a.js', version: '1' }],
    ['no main', { id: 'x', name: 'X', type: 'visualizer', version: '1' }],
    ['no type', { id: 'x', name: 'X', main: 'a.js', version: '1' }],
  ])('refuses a manifest with %s', (_label, raw) => {
    expect(parseManifest(raw)).toHaveProperty('error');
  });

  it.each(['../escape', 'Has Spaces', 'UPPER', 'trailing/'])(
    'refuses %s as an id, because the id becomes part of a URL',
    (id) => {
      expect(parseManifest({ ...nonPlaces, id })).toHaveProperty('error');
    }
  );

  it('defaults a missing version rather than refusing — it is never acted on', () => {
    const { version } = nonPlaces;
    expect(version).toBeTruthy();
    const result = parseManifest({ ...nonPlaces, version: undefined });
    expect(result).toHaveProperty('manifest');
    expect((result as { manifest: { version: string } }).manifest.version).toBe('0.0.0');
  });
});

describe('reviewPlugins', () => {
  it('accepts a visualizer declaring the implemented api version', () => {
    const [verdict] = reviewPlugins([local(nonPlaces)]);
    expect(verdict.ok).toBe(true);
  });

  it('refuses a library browser — ADR-0034 point 9', () => {
    const [verdict] = reviewPlugins([local(timeline)]);
    expect(verdict).toMatchObject({ ok: false, refusal: 'not-a-visualizer', id: 'timeline' });
  });

  it('refuses a newer api version than the host implements — point 7', () => {
    const [verdict] = reviewPlugins([
      local({ ...nonPlaces, familiar: { apiVersion: VISUALIZER_API_VERSION + 1 } }),
    ]);
    expect(verdict).toMatchObject({ ok: false, refusal: 'api-version' });
    expect((verdict as { detail: string }).detail).toContain(String(VISUALIZER_API_VERSION + 1));
  });

  it('refuses an older api version too — a downgrade is still a mismatch', () => {
    const [verdict] = reviewPlugins([local(nonPlaces)], { hostApiVersion: 2 });
    expect(verdict).toMatchObject({ ok: false, refusal: 'api-version' });
  });

  it('refuses a manifest that declares no api version rather than assuming 1', () => {
    const [verdict] = reviewPlugins([local({ ...nonPlaces, familiar: undefined })]);
    expect(verdict).toMatchObject({ ok: false, refusal: 'api-version' });
  });

  it('refuses a plugin claiming a built-in id instead of letting it overwrite one', () => {
    const [verdict] = reviewPlugins([local({ ...nonPlaces, id: 'lyrics' })], {
      builtInIds: ['reactive-terrain', 'beat-tiles', 'lyrics', 'music-video'],
    });
    expect(verdict).toMatchObject({ ok: false, refusal: 'reserved-id' });
  });

  it('lets a local bundle win a collision with a shipped one, and says the shipped one lost', () => {
    const verdicts = reviewPlugins([shipped(nonPlaces), local(nonPlaces)]);

    const winner = verdicts.find((v) => v.ok);
    expect(winner).toMatchObject({ ok: true, source: 'local' });

    const loser = verdicts.find((v) => !v.ok);
    expect(loser).toMatchObject({ ok: false, source: 'shipped', refusal: 'shadowed' });
  });

  it('reviews every entry, so one bad manifest does not hide the rest', () => {
    const verdicts = reviewPlugins([local('garbage'), local(nonPlaces), local(timeline)]);
    expect(verdicts).toHaveLength(3);
    expect(verdicts.filter((v) => v.ok)).toHaveLength(1);
  });

  it('gives a malformed manifest a row with no id, rather than dropping it silently', () => {
    const [verdict] = reviewPlugins([local({ name: 'Broken' })]);
    expect(verdict).toMatchObject({ ok: false, refusal: 'malformed', id: null });
    expect((verdict as { detail: string }).detail).toBeTruthy();
  });
});

/**
 * ADR-0064: the optional `affinity` block.
 *
 * The vocabulary check is deliberately **not** here. Whether `"dreamy"` is a tag the server knows
 * is decided where the analysis lives; duplicating the 48 descriptors into TypeScript is the
 * "two copies of that rule in two languages" ADR-0034 warns about. These cover structure only.
 */
describe('parseAffinity', () => {
  function affinityOf(block: unknown) {
    const result = parseManifest({ ...nonPlaces, affinity: block });
    if ('error' in result) throw new Error(`unexpected refusal: ${result.error}`);
    return result;
  }

  it('reads tags and ranges', () => {
    const { manifest, ignored } = affinityOf({
      tags: ['ambient', 'dreamy'],
      ranges: [{ feature: 'energy', minimum: 0.1, maximum: 0.4 }],
    });
    expect(manifest.affinity).toEqual({
      tags: ['ambient', 'dreamy'],
      ranges: [{ feature: 'energy', minimum: 0.1, maximum: 0.4 }],
    });
    expect(ignored).toEqual([]);
  });

  it('keeps an open-ended range', () => {
    const { manifest } = affinityOf({ ranges: [{ feature: 'bpm', minimum: 120 }] });
    expect(manifest.affinity?.ranges).toEqual([{ feature: 'bpm', minimum: 120 }]);
  });

  // The reason this had to be parsed rather than copied: `parseManifest` rebuilds the object field
  // by field, so a block it does not name never reaches anyone.
  it('survives parseManifest, which drops anything it does not name', () => {
    const { manifest } = affinityOf({ tags: ['calm'] });
    expect(manifest.affinity).toBeDefined();
  });

  it('is absent, and silent, when not declared', () => {
    const result = parseManifest(nonPlaces);
    if ('error' in result) throw new Error('unexpected refusal');
    expect(result.manifest.affinity).toBeUndefined();
    expect(result.ignored).toEqual([]);
  });

  it.each([
    ['not an object', 'nope'],
    ['an array', ['ambient']],
    ['a number', 7],
  ])('reports a block that is %s', (_label, block) => {
    const { manifest, ignored } = affinityOf(block);
    expect(manifest.affinity).toBeUndefined();
    expect(ignored.length).toBeGreaterThan(0);
  });

  it('drops a non-string tag and says so', () => {
    const { manifest, ignored } = affinityOf({ tags: ['ambient', 42] });
    expect(manifest.affinity?.tags).toEqual(['ambient']);
    expect(ignored.join(' ')).toContain('42');
  });

  it('drops a range with no feature', () => {
    const { manifest, ignored } = affinityOf({ ranges: [{ minimum: 1 }] });
    expect(manifest.affinity).toBeUndefined();
    expect(ignored.join(' ')).toContain('feature');
  });

  it('drops a range bounded by nothing numeric', () => {
    const { manifest, ignored } = affinityOf({
      ranges: [{ feature: 'energy', minimum: 'loud' }],
    });
    expect(manifest.affinity).toBeUndefined();
    expect(ignored.join(' ')).toContain('energy');
  });

  // The point of ADR-0064 point 3, at the parse layer: a bad optional field must never cost the
  // author a working visualizer.
  it('never refuses the plugin over an unusable affinity block', () => {
    const [verdict] = reviewPlugins([local({ ...nonPlaces, affinity: 'rubbish' })]);
    expect(verdict.ok).toBe(true);
    expect((verdict as { ignored: string[] }).ignored.length).toBeGreaterThan(0);
  });
});
