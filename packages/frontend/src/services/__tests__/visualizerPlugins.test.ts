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
