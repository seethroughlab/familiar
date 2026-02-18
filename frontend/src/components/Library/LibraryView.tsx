/**
 * LibraryView - Main container for library browsing.
 *
 * Manages track selection and filters.
 * Renders the selected browser with BrowserProps.
 * Browser selection is controlled by the route via browserId prop.
 */
import { useCallback, useMemo } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { Download } from 'lucide-react';
import { useSelectionStore } from '../../stores/selectionStore';
import { useOfflineTrackIds } from '../../hooks/useOfflineTrack';
import { SelectionIndicator } from './SelectionIndicator';
import {
  getBrowser,
  type LibraryFilters,
  type ArtistSummary,
  type AlbumSummary,
} from './types';

// Import browsers to register them
import './browsers';

interface LibraryViewProps {
  /** Browser ID to display - from route */
  browserId: string;
}

export function LibraryView({ browserId }: LibraryViewProps) {
  const navigate = useNavigate();
  const {
    selectedIds: selectedTrackIds,
    toggleSelection,
    clearSelection,
    setEditingTrackId,
  } = useSelectionStore();
  const { offlineIds } = useOfflineTrackIds();
  const [searchParams, setSearchParams] = useSearchParams();

  // Filters - read from URL query params
  const filters: LibraryFilters = useMemo(() => {
    return {
      search: searchParams.get('search') || undefined,
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
  }, [searchParams]);

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
      }, { replace: true });
    },
    [setSearchParams]
  );

  const selectTrack = useCallback((trackId: string, multi: boolean) => {
    if (multi) {
      toggleSelection(trackId);
    } else {
      clearSelection();
      toggleSelection(trackId);
    }
  }, [toggleSelection, clearSelection]);

  const selectAll = useCallback(() => {
    // The browser can implement its own select-all
  }, []);

  // Navigation handlers - use path-based routing
  const handleGoToArtist = useCallback(
    (artistName: string) => {
      navigate(`/library/artists/${encodeURIComponent(artistName)}`);
    },
    [navigate]
  );

  const handleGoToAlbum = useCallback(
    (artistName: string, albumName: string) => {
      navigate(`/library/albums/${encodeURIComponent(artistName)}/${encodeURIComponent(albumName)}`);
    },
    [navigate]
  );

  const handleGoToYear = useCallback(
    (year: number) => {
      navigate(`/library/tracks?yearFrom=${year}&yearTo=${year}`);
    },
    [navigate]
  );

  const handleGoToYearRange = useCallback(
    (yearFrom: number, yearTo: number) => {
      navigate(`/library/tracks?yearFrom=${yearFrom}&yearTo=${yearTo}`);
    },
    [navigate]
  );

  const handleGoToMood = useCallback(
    (energyMin: number, energyMax: number, valenceMin: number, valenceMax: number) => {
      navigate(`/library/tracks?energyMin=${energyMin}&energyMax=${energyMax}&valenceMin=${valenceMin}&valenceMax=${valenceMax}`);
    },
    [navigate]
  );

  const handleGoToGenre = useCallback(
    (genre: string) => {
      navigate(`/library/tracks?genre=${encodeURIComponent(genre)}`);
    },
    [navigate]
  );

  const handleFilterChange = useCallback(
    (newFilters: Partial<LibraryFilters>) => {
      setFilters({ ...filters, ...newFilters });
    },
    [filters, setFilters]
  );

  const handlePlayTrack = useCallback((_trackId: string) => {
    // Handled by the browser component directly
  }, []);

  const handlePlayTrackAt = useCallback((_trackId: string, _index: number) => {
    // Handled by the browser component directly
  }, []);

  const handleQueueTrack = useCallback((_trackId: string) => {
    // TODO: Implement queue functionality
  }, []);

  const handleEditTrack = useCallback((trackId: string) => {
    setEditingTrackId(trackId);
  }, [setEditingTrackId]);

  // Get the current browser component
  const currentBrowser = getBrowser(browserId);
  const BrowserComponent = currentBrowser?.component;

  const artists: ArtistSummary[] = [];
  const albums: AlbumSummary[] = [];

  return (
    <div className="flex flex-col md:h-full md:min-h-0">
      {/* Filter toolbar */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-zinc-800/50">
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
            key={`browser-${browserId}`}
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
            Browser not found: {browserId}
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
