/**
 * LibraryView - Main container for library browsing.
 *
 * Manages browser selection, track selection, and filters.
 * Renders the selected browser with BrowserProps.
 * Persists view state in URL for reload support.
 */
import { useCallback, useMemo, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Download } from 'lucide-react';
import { useLibraryViewStore } from '../../stores/libraryViewStore';
import { useSelectionStore } from '../../stores/selectionStore';
import { useOfflineTrackIds } from '../../hooks/useOfflineTrack';
import { BrowserPicker } from './BrowserPicker';
import { SelectionIndicator } from './SelectionIndicator';
import { ArtistDetail } from './ArtistDetail';
import { AlbumDetail } from './AlbumDetail';
import {
  getBrowser,
  DEFAULT_BROWSER_ID,
  type LibraryFilters,
  type ArtistSummary,
  type AlbumSummary,
} from './types';

// Import browsers to register them
import './browsers';

interface LibraryViewProps {
  /** Initial search query from parent */
  initialSearch?: string;
}

export function LibraryView({ initialSearch }: LibraryViewProps) {
  const { selectedBrowserId, setSelectedBrowserId } = useLibraryViewStore();
  const {
    selectedIds: selectedTrackIds,
    toggleSelection,
    clearSelection,
    setEditingTrackId,
  } = useSelectionStore();
  const { offlineIds } = useOfflineTrackIds();
  const [searchParams, setSearchParams] = useSearchParams();

  // Browser selection - read from URL, fall back to persisted preference
  const currentBrowserId = searchParams.get('browser') || selectedBrowserId;

  const setCurrentBrowserId = useCallback(
    (browserId: string) => {
      // Persist the selection to localStorage
      setSelectedBrowserId(browserId);

      // Also update the URL
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        if (browserId === DEFAULT_BROWSER_ID) {
          next.delete('browser');
        } else {
          next.set('browser', browserId);
        }
        return next;
      });
    },
    [setSearchParams, setSelectedBrowserId]
  );

  // Filters - read from URL
  const filters: LibraryFilters = useMemo(() => {
    return {
      search: initialSearch || searchParams.get('search') || undefined,
      artist: searchParams.get('artist') || undefined,
      album: searchParams.get('album') || undefined,
      genre: searchParams.get('genre') || undefined,
      yearFrom: searchParams.get('yearFrom') ? Number(searchParams.get('yearFrom')) : undefined,
      yearTo: searchParams.get('yearTo') ? Number(searchParams.get('yearTo')) : undefined,
      energyMin: searchParams.get('energyMin') ? Number(searchParams.get('energyMin')) : undefined,
      energyMax: searchParams.get('energyMax') ? Number(searchParams.get('energyMax')) : undefined,
      valenceMin: searchParams.get('valenceMin') ? Number(searchParams.get('valenceMin')) : undefined,
      valenceMax: searchParams.get('valenceMax') ? Number(searchParams.get('valenceMax')) : undefined,
      downloadedOnly: searchParams.get('downloadedOnly') === 'true',
    };
  }, [searchParams, initialSearch]);

  const setFilters = useCallback(
    (newFilters: LibraryFilters) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        // Clear old filter params
        next.delete('artist');
        next.delete('album');
        next.delete('genre');
        next.delete('yearFrom');
        next.delete('yearTo');
        next.delete('energyMin');
        next.delete('energyMax');
        next.delete('valenceMin');
        next.delete('valenceMax');
        next.delete('downloadedOnly');
        // Set new ones
        if (newFilters.artist) next.set('artist', newFilters.artist);
        if (newFilters.album) next.set('album', newFilters.album);
        if (newFilters.genre) next.set('genre', newFilters.genre);
        if (newFilters.yearFrom) next.set('yearFrom', String(newFilters.yearFrom));
        if (newFilters.yearTo) next.set('yearTo', String(newFilters.yearTo));
        if (newFilters.energyMin !== undefined) next.set('energyMin', String(newFilters.energyMin));
        if (newFilters.energyMax !== undefined) next.set('energyMax', String(newFilters.energyMax));
        if (newFilters.valenceMin !== undefined) next.set('valenceMin', String(newFilters.valenceMin));
        if (newFilters.valenceMax !== undefined) next.set('valenceMax', String(newFilters.valenceMax));
        if (newFilters.downloadedOnly) next.set('downloadedOnly', 'true');
        return next;
      });
    },
    [setSearchParams]
  );

  // Auto-switch to artist detail when artist filter is active and Artists view is selected
  // This provides a more intuitive UX: "I'm looking at this artist, show me their page"
  useEffect(() => {
    const artistFilter = searchParams.get('artist');
    if (artistFilter && currentBrowserId === 'artist-list') {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set('artistDetail', artistFilter);
        return next;
      }, { replace: true });
    }
  }, [currentBrowserId, searchParams, setSearchParams]);

  // Artist detail view state - read from URL
  const selectedArtist = searchParams.get('artistDetail');

  // Album detail view state - read from URL
  const selectedAlbum = useMemo(() => {
    const artistParam = searchParams.get('albumDetailArtist');
    const albumParam = searchParams.get('albumDetailAlbum');
    if (artistParam && albumParam) {
      return { artist: artistParam, album: albumParam };
    }
    return null;
  }, [searchParams]);

  const selectTrack = useCallback((trackId: string, multi: boolean) => {
    if (multi) {
      // Toggle individual track (Cmd/Ctrl+click)
      toggleSelection(trackId);
    } else {
      // Single select - clear others and select this one
      // Use clearSelection + toggleSelection to select only this track
      clearSelection();
      toggleSelection(trackId);
    }
  }, [toggleSelection, clearSelection]);

  const selectAll = useCallback(() => {
    // This would need track data from the browser - for now, it's a no-op
    // The browser can implement its own select-all
  }, []);

  // Navigation handlers - switch to track list and apply filter
  // Note: Must update both filters AND view in a single setSearchParams call
  // to avoid React batching issues where one overwrites the other
  const handleGoToArtist = useCallback(
    (artistName: string) => {
      // Open artist detail view - persist in URL
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set('artistDetail', artistName);
        return next;
      });
    },
    [setSearchParams]
  );

  const handleBackFromArtist = useCallback(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete('artistDetail');
      // Also clear artist filter to prevent auto-switch useEffect from
      // immediately re-opening the artist detail view
      next.delete('artist');
      return next;
    });
  }, [setSearchParams]);

  const handleGoToAlbum = useCallback(
    (artistName: string, albumName: string) => {
      // Open album detail view - persist in URL
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        // Clear other detail/filter views
        next.delete('artistDetail');
        next.delete('artist');
        next.delete('album');
        next.delete('browser');
        next.delete('yearFrom');
        next.delete('yearTo');
        next.delete('energyMin');
        next.delete('energyMax');
        next.delete('valenceMin');
        next.delete('valenceMax');
        // Set album detail params
        next.set('albumDetailArtist', artistName);
        next.set('albumDetailAlbum', albumName);
        return next;
      });
    },
    [setSearchParams]
  );

  const handleBackFromAlbum = useCallback(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete('albumDetailArtist');
      next.delete('albumDetailAlbum');
      return next;
    });
  }, [setSearchParams]);

  const handleGoToYear = useCallback(
    (year: number) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.delete('artist');
        next.delete('album');
        next.delete('yearFrom');
        next.delete('yearTo');
        next.delete('energyMin');
        next.delete('energyMax');
        next.delete('valenceMin');
        next.delete('valenceMax');
        // Explicitly switch to track-list to show filtered tracks
        next.set('browser', 'track-list');
        next.set('yearFrom', String(year));
        next.set('yearTo', String(year));
        return next;
      });
    },
    [setSearchParams]
  );

  const handleGoToYearRange = useCallback(
    (yearFrom: number, yearTo: number) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.delete('artist');
        next.delete('album');
        next.delete('yearFrom');
        next.delete('yearTo');
        next.delete('energyMin');
        next.delete('energyMax');
        next.delete('valenceMin');
        next.delete('valenceMax');
        // Explicitly switch to track-list to show filtered tracks
        next.set('browser', 'track-list');
        next.set('yearFrom', String(yearFrom));
        next.set('yearTo', String(yearTo));
        return next;
      });
    },
    [setSearchParams]
  );

  const handleGoToMood = useCallback(
    (energyMin: number, energyMax: number, valenceMin: number, valenceMax: number) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        // Clear old filter params
        next.delete('artist');
        next.delete('album');
        next.delete('yearFrom');
        next.delete('yearTo');
        next.delete('energyMin');
        next.delete('energyMax');
        next.delete('valenceMin');
        next.delete('valenceMax');
        // Explicitly switch to track-list to show filtered tracks
        next.set('browser', 'track-list');
        // Set mood filters
        next.set('energyMin', String(energyMin));
        next.set('energyMax', String(energyMax));
        next.set('valenceMin', String(valenceMin));
        next.set('valenceMax', String(valenceMax));
        return next;
      });
    },
    [setSearchParams]
  );

  const handleGoToGenre = useCallback(
    (genre: string) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        // Clear other filters but keep genre
        next.delete('artist');
        next.delete('album');
        next.delete('genre');
        next.delete('yearFrom');
        next.delete('yearTo');
        next.delete('energyMin');
        next.delete('energyMax');
        next.delete('valenceMin');
        next.delete('valenceMax');
        next.delete('albumDetailArtist');
        next.delete('albumDetailAlbum');
        next.delete('artistDetail');
        // Explicitly switch to track-list to show filtered tracks
        next.set('browser', 'track-list');
        next.set('genre', genre);
        return next;
      });
    },
    [setSearchParams]
  );

  const handleFilterChange = useCallback(
    (newFilters: Partial<LibraryFilters>) => {
      setFilters({ ...filters, ...newFilters });
    },
    [filters, setFilters]
  );

  // Playback handlers
  const handlePlayTrack = useCallback((_trackId: string) => {
    // This is handled by the browser component directly
  }, []);

  const handlePlayTrackAt = useCallback((_trackId: string, _index: number) => {
    // This is handled by the browser component directly
  }, []);

  const handleQueueTrack = useCallback((_trackId: string) => {
    // TODO: Implement queue functionality
  }, []);

  const handleEditTrack = useCallback((trackId: string) => {
    setEditingTrackId(trackId);
  }, [setEditingTrackId]);

  // Get the current browser component
  const currentBrowser = getBrowser(currentBrowserId);
  const BrowserComponent = currentBrowser?.component;

  // Placeholder data for artists/albums (Phase 2 will populate these)
  const artists: ArtistSummary[] = [];
  const albums: AlbumSummary[] = [];

  // Show artist detail view if an artist is selected
  if (selectedArtist) {
    return (
      <div className="flex flex-col h-full">
        <div className="flex-1 overflow-y-auto p-4">
          <ArtistDetail
            artistName={selectedArtist}
            onBack={handleBackFromArtist}
            onGoToAlbum={handleGoToAlbum}
            onGoToGenre={handleGoToGenre}
            onGoToYear={handleGoToYear}
          />
        </div>
      </div>
    );
  }

  // Show album detail view if an album is selected
  if (selectedAlbum) {
    return (
      <div className="flex flex-col h-full">
        <div className="flex-1 overflow-y-auto p-4">
          <AlbumDetail
            artistName={selectedAlbum.artist}
            albumName={selectedAlbum.album}
            onBack={handleBackFromAlbum}
            onGoToArtist={handleGoToArtist}
            onGoToAlbum={handleGoToAlbum}
            onGoToYear={handleGoToYear}
            onGoToGenre={handleGoToGenre}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col md:h-full md:min-h-0">
      {/* Browser picker toolbar */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-zinc-800/50">
        <BrowserPicker
          currentBrowserId={currentBrowserId}
          onSelectBrowser={setCurrentBrowserId}
        />

        {/* Downloaded only filter toggle */}
        <button
          onClick={() => setFilters({ ...filters, downloadedOnly: !filters.downloadedOnly })}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors ${
            filters.downloadedOnly
              ? 'bg-green-600 text-white'
              : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-white'
          }`}
          title={filters.downloadedOnly ? 'Show all tracks' : 'Show only downloaded tracks'}
        >
          <Download className="w-4 h-4" />
          <span className="hidden sm:inline">Downloaded</span>
          {filters.downloadedOnly && offlineIds.size > 0 && (
            <span className="text-xs opacity-75">({offlineIds.size})</span>
          )}
        </button>
      </div>

      {/* Filter breadcrumbs */}
      {(filters.artist || filters.album || filters.genre || filters.yearFrom || filters.energyMin !== undefined) && (
        <div className="flex items-center gap-2 px-4 py-2 text-sm bg-zinc-800/50">
          <span className="text-zinc-400">Viewing:</span>
          {filters.artist && (
            <button
              onClick={() => setFilters({ artist: filters.artist })}
              className="px-2 py-0.5 bg-zinc-700 hover:bg-zinc-600 rounded text-white"
            >
              {filters.artist}
            </button>
          )}
          {filters.album && (
            <>
              <span className="text-zinc-500">/</span>
              <span className="px-2 py-0.5 bg-zinc-700 rounded text-white">
                {filters.album}
              </span>
            </>
          )}
          {filters.genre && (
            <span className="px-2 py-0.5 bg-zinc-700 rounded text-white">
              {filters.genre}
            </span>
          )}
          {filters.yearFrom && (
            <span className="px-2 py-0.5 bg-zinc-700 rounded text-white">
              {filters.yearFrom === filters.yearTo
                ? filters.yearFrom
                : `${filters.yearFrom}-${filters.yearTo}`}
            </span>
          )}
          {filters.energyMin !== undefined && (
            <span className="px-2 py-0.5 bg-purple-700 rounded text-white">
              Energy {Math.round(filters.energyMin * 100)}-{Math.round((filters.energyMax ?? 1) * 100)}%
              {' / '}
              Valence {Math.round((filters.valenceMin ?? 0) * 100)}-{Math.round((filters.valenceMax ?? 1) * 100)}%
            </span>
          )}
          <button
            onClick={() => setFilters({ search: filters.search })}
            className="ml-2 text-zinc-400 hover:text-white text-xs"
          >
            Clear
          </button>
        </div>
      )}

      {/* Browser content */}
      <div className="md:flex-1 md:overflow-y-auto md:min-h-0">
        {BrowserComponent ? (
          <BrowserComponent
            key={`browser-${currentBrowserId}`}
            tracks={[]}
            artists={artists}
            albums={albums}
            isLoading={false}
            selectedTrackIds={selectedTrackIds}
            onSelectTrack={selectTrack}
            onSelectAll={selectAll}
            onClearSelection={clearSelection}
            onGoToArtist={handleGoToArtist}
            onGoToAlbum={handleGoToAlbum}
            onGoToYear={handleGoToYear}
            onGoToYearRange={handleGoToYearRange}
            onGoToGenre={handleGoToGenre}
            onGoToMood={handleGoToMood}
            onPlayTrack={handlePlayTrack}
            onPlayTrackAt={handlePlayTrackAt}
            onQueueTrack={handleQueueTrack}
            onEditTrack={handleEditTrack}
            filters={filters}
            onFilterChange={handleFilterChange}
            offlineTrackIds={offlineIds}
          />
        ) : (
          <div className="flex items-center justify-center py-20 text-zinc-500">
            Browser not found: {currentBrowserId}
          </div>
        )}
      </div>

      {/* Selection indicator pill */}
      <SelectionIndicator
        selectedCount={selectedTrackIds.size}
        onClear={clearSelection}
      />
    </div>
  );
}
