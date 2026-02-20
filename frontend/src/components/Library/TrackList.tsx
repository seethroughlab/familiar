import { useState, useMemo, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Download, Check, Loader2, Heart, Music, FolderOpen } from 'lucide-react';
import { tracksApi } from '../../api';
import { useFavorites } from '../../hooks/useFavorites';
import { usePlayerStore } from '../../stores/playerStore';
import { PlayIndicator } from '../common/PlayIndicator';
import { useColumnStore, getVisibleColumns } from '../../stores/columnStore';
import { useVisibleTracksStore } from '../../stores/visibleTracksStore';
import { COLUMN_DEFINITIONS, getColumnDef, getAnalysisColumns } from './columnDefinitions';
import { useOfflineTrack } from '../../hooks/useOfflineTrack';
import type { Track } from '../../types';

interface TrackRowProps {
  track: Track;
  index: number;
  isCurrentTrack: boolean;
  isPlaying: boolean;
  onPlay: () => void;
  visibleColumnIds: string[];
  gridColumns: string;
}

// Mobile card component for small screens
function MobileTrackCard({
  track,
  index,
  isCurrentTrack,
  isPlaying,
  onPlay,
}: {
  track: Track;
  index: number;
  isCurrentTrack: boolean;
  isPlaying: boolean;
  onPlay: () => void;
}) {
  const formatDuration = (seconds: number | null) => {
    if (!seconds) return '--:--';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div
      data-testid="track-row"
      onClick={onPlay}
      className={`group flex items-center gap-3 px-4 py-3 hover:bg-zinc-800/50 cursor-pointer border-b border-zinc-800/30 ${
        isCurrentTrack ? 'bg-zinc-800/50' : ''
      }`}
    >
      {/* Play button / index */}
      <div className="w-8 flex-shrink-0 flex items-center justify-center">
        <PlayIndicator isCurrent={isCurrentTrack} isPlaying={isPlaying} index={index + 1} />
      </div>

      {/* Track info */}
      <div className="flex-1 min-w-0">
        <div className={`truncate font-medium ${isCurrentTrack ? 'text-green-500' : 'text-white'}`}>
          {track.title || 'Unknown'}
        </div>
        <div className="text-sm text-zinc-400 truncate">
          {track.artist || 'Unknown Artist'}
          {track.album && <span className="text-zinc-500"> • {track.album}</span>}
        </div>
      </div>

      {/* Duration */}
      <div className="text-sm text-zinc-400 flex-shrink-0">
        {formatDuration(track.duration_seconds)}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1 flex-shrink-0">
        <FavoriteButton trackId={track.id} />
        <OfflineButton trackId={track.id} />
      </div>
    </div>
  );
}

function OfflineButton({ trackId }: { trackId: string }) {
  const { isOffline, isDownloading, downloadProgress, download, remove } = useOfflineTrack(trackId);

  if (isDownloading) {
    return (
      <div
        className="relative p-1 text-purple-400"
        title={`Downloading... ${downloadProgress}%`}
      >
        <Loader2 className="w-4 h-4 animate-spin" />
        {downloadProgress > 0 && downloadProgress < 100 && (
          <span className="absolute -bottom-1 left-1/2 -translate-x-1/2 text-[8px] font-medium">
            {downloadProgress}%
          </span>
        )}
      </div>
    );
  }

  if (isOffline) {
    return (
      <button
        onClick={(e) => {
          e.stopPropagation();
          remove();
        }}
        className="p-1 text-green-500 hover:text-red-400 transition-colors"
        title="Remove offline copy"
      >
        <Check className="w-4 h-4" />
      </button>
    );
  }

  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        download();
      }}
      className="p-1 text-zinc-500 hover:text-white transition-colors opacity-100 sm:opacity-0 sm:group-hover:opacity-100"
      title="Download for offline"
    >
      <Download className="w-4 h-4" />
    </button>
  );
}

function FavoriteButton({ trackId }: { trackId: string }) {
  const { isFavorite, toggle } = useFavorites();
  const favorited = isFavorite(trackId);

  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        toggle(trackId);
      }}
      className={`p-1 transition-colors ${
        favorited
          ? 'text-pink-500 hover:text-pink-400'
          : 'text-zinc-500 hover:text-pink-400 opacity-100 sm:opacity-0 sm:group-hover:opacity-100'
      }`}
      title={favorited ? 'Remove from favorites' : 'Add to favorites'}
    >
      <Heart className="w-4 h-4" fill={favorited ? 'currentColor' : 'none'} />
    </button>
  );
}

function TrackRow({ track, index, isCurrentTrack, isPlaying, onPlay, visibleColumnIds, gridColumns }: TrackRowProps) {
  return (
    <div
      data-testid="track-row"
      onClick={onPlay}
      className={`group grid gap-4 px-4 py-2 rounded-md hover:bg-zinc-800/50 cursor-pointer ${
        isCurrentTrack ? 'bg-zinc-800/50' : ''
      }`}
      style={{ gridTemplateColumns: gridColumns }}
    >
      {/* Index / Play button column */}
      <div className="flex items-center justify-center"
        onClick={(e) => { e.stopPropagation(); onPlay(); }}
        role="button"
      >
        <PlayIndicator isCurrent={isCurrentTrack} isPlaying={isPlaying} index={index + 1} />
      </div>

      {/* Title column (always visible) */}
      <div className="min-w-0">
        <div className={`truncate ${isCurrentTrack ? 'text-green-500' : ''}`}>
          {track.title || 'Unknown'}
        </div>
      </div>

      {/* Dynamic columns */}
      {visibleColumnIds.map((colId) => {
        const colDef = getColumnDef(colId);
        if (!colDef) return null;

        const rawValue = colDef.getValue(track);
        const displayValue = colDef.format && rawValue != null
          ? colDef.format(rawValue)
          : rawValue ?? '-';

        return (
          <div
            key={colId}
            className={`text-zinc-400 truncate ${
              colDef.align === 'right' ? 'text-right' :
              colDef.align === 'center' ? 'text-center' : ''
            }`}
          >
            {displayValue}
          </div>
        );
      })}

      {/* Favorite button */}
      <div className="flex items-center justify-center">
        <FavoriteButton trackId={track.id} />
      </div>

      {/* Offline button */}
      <div className="flex items-center justify-center">
        <OfflineButton trackId={track.id} />
      </div>
    </div>
  );
}

interface TrackListProps {
  search?: string;
  artist?: string;
  album?: string;
}

export function TrackList({ search, artist, album }: TrackListProps) {
  const currentTrack = usePlayerStore((s) => s.currentTrack);
  const isPlaying = usePlayerStore((s) => s.isPlaying);
  const setIsPlaying = usePlayerStore((s) => s.setIsPlaying);
  const setQueue = usePlayerStore((s) => s.setQueue);
  const columns = useColumnStore((state) => state.columns);
  const reorderColumns = useColumnStore((state) => state.reorderColumns);

  // Drag & drop state
  const [draggedColId, setDraggedColId] = useState<string | null>(null);
  const [dropTargetId, setDropTargetId] = useState<string | null>(null);

  // Get visible column IDs in order
  const visibleColumnIds = useMemo(() => getVisibleColumns(columns), [columns]);

  // Check if any analysis columns are visible
  const analysisColumnIds = useMemo(
    () => new Set(getAnalysisColumns().map((c) => c.id)),
    []
  );
  const needsFeatures = useMemo(
    () => visibleColumnIds.some((id) => analysisColumnIds.has(id)),
    [visibleColumnIds, analysisColumnIds]
  );

  // Build grid template columns
  const gridColumns = useMemo(() => {
    const cols: string[] = ['3rem']; // Index column
    cols.push('1fr'); // Title (always visible)

    for (const colId of visibleColumnIds) {
      const colDef = COLUMN_DEFINITIONS.find((d) => d.id === colId);
      cols.push(colDef?.width || '1fr');
    }

    cols.push('3rem', '3rem'); // Favorite, Offline
    return cols.join(' ');
  }, [visibleColumnIds]);

  // Drag handlers for column reordering
  const handleDragStart = (colId: string) => {
    setDraggedColId(colId);
  };

  const handleDragOver = (e: React.DragEvent, colId: string) => {
    e.preventDefault();
    if (draggedColId && draggedColId !== colId) {
      setDropTargetId(colId);
    }
  };

  const handleDragLeave = () => {
    setDropTargetId(null);
  };

  const handleDrop = (e: React.DragEvent, targetColId: string) => {
    e.preventDefault();
    if (draggedColId && draggedColId !== targetColId) {
      // Find indices in the full columns array (not just visible)
      const fromIndex = columns.findIndex((c) => c.id === draggedColId);
      const toIndex = columns.findIndex((c) => c.id === targetColId);
      if (fromIndex !== -1 && toIndex !== -1) {
        reorderColumns(fromIndex, toIndex);
      }
    }
    setDraggedColId(null);
    setDropTargetId(null);
  };

  const handleDragEnd = () => {
    setDraggedColId(null);
    setDropTargetId(null);
  };

  const { data, isLoading, error } = useQuery({
    queryKey: ['tracks', { search, artist, album, include_features: needsFeatures }],
    queryFn: () => tracksApi.list({
      search,
      artist,
      album,
      page_size: 100,
      include_features: needsFeatures,
    }),
  });

  // Update visible tracks store when data changes (for LLM context)
  const setVisibleTracks = useVisibleTracksStore((state) => state.setVisibleTracks);
  useEffect(() => {
    if (data?.items) {
      const visibleTracks = data.items.map((t) => ({
        id: t.id,
        title: t.title || 'Unknown Title',
        artist: t.artist || 'Unknown Artist',
        album: t.album || 'Unknown Album',
      }));

      // Build filter description for LLM context
      const filterParts: string[] = [];
      if (search) filterParts.push(`search: "${search}"`);
      if (artist) filterParts.push(`artist: "${artist}"`);
      if (album) filterParts.push(`album: "${album}"`);
      const filterDescription = filterParts.length > 0
        ? `Filtered by ${filterParts.join(', ')}`
        : 'All tracks';

      setVisibleTracks(visibleTracks, data.total, filterDescription);
    }
  }, [data, search, artist, album, setVisibleTracks]);

  const handlePlayTrack = (track: Track, index: number) => {
    if (currentTrack?.id === track.id) {
      setIsPlaying(!isPlaying);
    } else if (data) {
      setQueue(data.items, index);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-zinc-500">Loading tracks...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-red-500">Error loading tracks</div>
      </div>
    );
  }

  if (!data?.items.length) {
    // Different messages based on whether there's a filter applied
    const hasFilters = search || artist || album;
    return (
      <div className="flex flex-col items-center justify-center py-20 text-zinc-500">
        {hasFilters ? (
          <>
            <Music className="w-12 h-12 mb-4 opacity-50" />
            <p>No tracks match your search</p>
            <p className="text-sm mt-1">Try adjusting your filters</p>
          </>
        ) : (
          <>
            <FolderOpen className="w-12 h-12 mb-4 opacity-50" />
            <p>Your library is empty</p>
            <p className="text-sm mt-1">Add music folders in Settings to get started</p>
          </>
        )}
      </div>
    );
  }

  return (
    <div>
      {/* Mobile view - card layout (visible below md breakpoint) */}
      <div className="md:hidden">
        {data.items.map((track, index) => (
          <MobileTrackCard
            key={track.id}
            track={track}
            index={index}
            isCurrentTrack={currentTrack?.id === track.id}
            isPlaying={currentTrack?.id === track.id && isPlaying}
            onPlay={() => handlePlayTrack(track, index)}
          />
        ))}
        {/* Mobile footer */}
        <div className="px-4 py-4 text-sm text-zinc-500">
          {data.total} tracks
        </div>
      </div>

      {/* Desktop view - grid layout (visible at md and above) */}
      <div className="hidden md:block">
        {/* Header */}
        <div
          className="grid gap-4 px-4 py-2 text-sm text-zinc-400 border-b border-zinc-800"
          style={{ gridTemplateColumns: gridColumns }}
        >
          <div>#</div>
          <div>Title</div>
          {visibleColumnIds.map((colId) => {
            const colDef = getColumnDef(colId);
            if (!colDef) return null;
            const isDragging = draggedColId === colId;
            const isDropTarget = dropTargetId === colId;
            return (
              <div
                key={colId}
                draggable
                onDragStart={() => handleDragStart(colId)}
                onDragOver={(e) => handleDragOver(e, colId)}
                onDragLeave={handleDragLeave}
                onDrop={(e) => handleDrop(e, colId)}
                onDragEnd={handleDragEnd}
                className={`cursor-grab select-none ${
                  colDef.align === 'right' ? 'text-right' :
                  colDef.align === 'center' ? 'text-center' : ''
                } ${isDragging ? 'opacity-50' : ''} ${
                  isDropTarget ? 'border-l-2 border-green-500' : ''
                }`}
                title={`${colDef.label} (drag to reorder)`}
              >
                {colDef.shortLabel || colDef.label}
              </div>
            );
          })}
          <div></div>
          <div></div>
        </div>

        {/* Tracks */}
        <div className="mt-2">
          {data.items.map((track, index) => (
            <TrackRow
              key={track.id}
              track={track}
              index={index}
              isCurrentTrack={currentTrack?.id === track.id}
              isPlaying={currentTrack?.id === track.id && isPlaying}
              onPlay={() => handlePlayTrack(track, index)}
              visibleColumnIds={visibleColumnIds}
              gridColumns={gridColumns}
            />
          ))}
        </div>

        {/* Desktop footer */}
        <div className="px-4 py-4 text-sm text-zinc-500">
          {data.total} tracks
        </div>
      </div>
    </div>
  );
}
