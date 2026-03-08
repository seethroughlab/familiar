/* @vitest-environment jsdom */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { PlaylistTrackList } from '../PlaylistTrackList';

vi.mock('../../../stores/playerStore', () => ({
  usePlayerStore: (selector: (state: { currentTrack: null; isPlaying: false }) => unknown) =>
    selector({ currentTrack: null, isPlaying: false }),
}));

vi.mock('../../../stores/columnStore', () => ({
  useColumnStore: (selector: (state: { columns: never[] }) => unknown) =>
    selector({ columns: [] }),
  getVisibleColumns: () => [],
}));

vi.mock('../PlaylistColumns', () => ({
  useLocalSort: () => ({ sortBy: null, sortOrder: 'asc', toggleSort: vi.fn() }),
  useSortedTracks: <T,>(items: T[]) => items,
  buildGridColumns: () => '3rem 1fr 3rem 4.5rem',
}));

vi.mock('../useClientAlphabetBar', () => ({
  useClientAlphabetBar: () => ({
    letterIndex: new Map(),
    activeLetter: null,
    isVisible: false,
    jumpToLetter: vi.fn(),
  }),
}));

vi.mock('../../../hooks/useTrackContextMenu', () => ({
  useTrackContextMenu: () => ({
    handleContextMenu: vi.fn(),
    contextMenuElement: null,
  }),
}));
vi.mock('../../../hooks/useOfflineStatus', () => ({
  useOfflineStatus: () => ({ isOnline: true, isOffline: false, offlineModeActive: false, reachabilityState: 'reachable', lastRecoveryAt: null }),
}));
vi.mock('../../../hooks/useOfflineTrack', () => ({
  useOfflineTrackIds: () => ({ offlineIds: new Set<string>(), refresh: vi.fn() }),
}));

vi.mock('../../Library/columnDefinitions', () => ({
  getColumnDef: vi.fn(() => null),
}));

vi.mock('../PlaylistColumnHeader', () => ({
  PlaylistColumnHeader: () => <div data-testid="playlist-header" />,
}));

vi.mock('../../Library/AlphabetBar', () => ({
  AlphabetBar: () => null,
}));

function makeTrack(id: string) {
  return {
    id,
    title: `Track ${id}`,
    artist: 'Artist',
    album: 'Album',
    album_artist: null,
    album_type: 'album' as const,
    track_number: 1,
    disc_number: 1,
    year: 2024,
    genre: 'Genre',
    duration_seconds: 120,
    format: 'mp3',
    file_path: `/music/${id}.mp3`,
    analysis_version: 1,
  };
}

describe('PlaylistTrackList row interactions', () => {
  it('keeps desktop click as selection instead of playback', () => {
    const onPlay = vi.fn();

    render(
      <PlaylistTrackList
        items={[makeTrack('1'), makeTrack('2')]}
        getTrack={(item) => item}
        onPlay={onPlay}
        renderDesktopTrailing={() => null}
        renderMobileTrailing={() => null}
      />
    );

    fireEvent.click(screen.getAllByTestId('playlist-track-row-desktop')[0]);

    expect(onPlay).not.toHaveBeenCalled();
    expect(screen.getByText('1 track selected')).toBeTruthy();
  });

  it('does not play when a mobile trailing action stops propagation', () => {
    const onPlay = vi.fn();

    render(
      <PlaylistTrackList
        items={[makeTrack('1')]}
        getTrack={(item) => item}
        onPlay={onPlay}
        renderDesktopTrailing={() => null}
        renderMobileTrailing={() => (
          <button
            data-testid="mobile-trailing-action"
            onClick={(e) => e.stopPropagation()}
          >
            action
          </button>
        )}
      />
    );

    fireEvent.click(screen.getByTestId('mobile-trailing-action'));

    expect(onPlay).not.toHaveBeenCalled();
  });
});
