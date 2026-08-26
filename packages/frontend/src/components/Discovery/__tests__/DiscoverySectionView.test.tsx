/* @vitest-environment jsdom */
import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { DiscoverySectionView } from '../DiscoverySectionView';
import type { DiscoverySection } from '../types';

/**
 * **Every layout must be able to start playback.**
 *
 * `DiscoverTrackList` stopped reading `playerStore` under ADR-0083 and began taking a callback, but
 * this parent kept passing one only to the `grid` and `list` branches. `onPlayTracks?.()` is
 * optional, so the `tracklist` branch failed silently: clicking play in "Unheard in Your Library"
 * or "Deep Cuts" did nothing at all, on the Mac and the phone, with no error anywhere.
 *
 * Nothing covered this path — the only test in this directory was `ExternalAlbumCard`.
 *
 * **The children are mocked on purpose.** Driving a real row would mean rendering a virtualised
 * list, which measures zero height in jsdom and renders no rows to click; the test would then fail
 * for a reason that has nothing to do with the defect. What went wrong here was a *prop that was
 * never passed*, so that is what these assert.
 */
const captured: Record<string, Record<string, unknown>> = {};

vi.mock('../DiscoverTrackList', () => ({
  DiscoverTrackList: (props: Record<string, unknown>) => {
    captured.tracklist = props;
    return null;
  },
}));
vi.mock('../DiscoveryGrid', () => ({
  DiscoveryGrid: (props: Record<string, unknown>) => {
    captured.grid = props;
    return null;
  },
}));
vi.mock('../DiscoveryList', () => ({
  DiscoveryList: (props: Record<string, unknown>) => {
    captured.list = props;
    return null;
  },
}));

const TRACK = { id: 'track-1', title: 'A Song', artist: 'An Artist', duration_seconds: 100 };

function sectionFor(layout: string): DiscoverySection {
  return {
    id: 'unheard-tracks',
    title: 'Unheard in Your Library',
    entityType: 'track',
    layout,
    items: [
      {
        id: TRACK.id,
        entityType: 'track',
        name: TRACK.title,
        subtitle: TRACK.artist,
        inLibrary: true,
        playbackContext: { artist: TRACK.artist, trackId: TRACK.id },
      },
    ],
    rawTracks: [TRACK],
  } as unknown as DiscoverySection;
}

describe('DiscoverySectionView can start playback from every layout', () => {
  it('the tracklist layout is given a way to play, and it reaches onItemPlay', () => {
    const onItemPlay = vi.fn();
    render(<DiscoverySectionView section={sectionFor('tracklist')} onItemPlay={onItemPlay} />);

    const onPlayTracks = captured.tracklist?.onPlayTracks as
      | ((tracks: unknown[], startId: string) => void)
      | undefined;

    // The defect: this was `undefined`, so every click was swallowed by optional chaining.
    expect(onPlayTracks, 'the tracklist layout was given no way to play').toBeTypeOf('function');

    onPlayTracks!([TRACK], TRACK.id);
    expect(onItemPlay).toHaveBeenCalledTimes(1);
    expect(onItemPlay.mock.calls[0][0]).toMatchObject({ playbackContext: { trackId: TRACK.id } });
  });

  it('the list layout is given a way to play', () => {
    const onItemPlay = vi.fn();
    render(<DiscoverySectionView section={sectionFor('list')} onItemPlay={onItemPlay} />);
    expect(captured.list?.onItemPlay).toBe(onItemPlay);
  });

  it('the grid layout is given a way to play', () => {
    const onItemPlay = vi.fn();
    render(<DiscoverySectionView section={sectionFor('grid')} onItemPlay={onItemPlay} />);
    expect(captured.grid?.onItemPlay).toBe(onItemPlay);
  });

  it('a parent with no player passes nothing, and that stays harmless', () => {
    render(<DiscoverySectionView section={sectionFor('tracklist')} />);
    // ADR-0083: the admin app has no transport, so absent is correct rather than broken.
    expect(captured.tracklist?.onPlayTracks).toBeUndefined();
  });
});
