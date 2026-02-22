import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Music,
  Loader2,
  ChevronDown,
  ChevronUp,
  ShoppingCart,
  Clock,
} from 'lucide-react';
import { spotifyApi } from '../../api';
import type { UnmatchedTrack } from '../../api';
import { StoreSearchLinks } from '../shared/StoreSearchLinks';

interface Props {
  onImportClick?: () => void;
}

export function MissingTracks({ onImportClick }: Props) {
  const [expanded, setExpanded] = useState(true);
  const [limit, setLimit] = useState(20);

  const { data: tracks, isLoading, error } = useQuery({
    queryKey: ['spotify-unmatched', limit],
    queryFn: () => spotifyApi.getUnmatched({ sort_by: 'added_at', limit }),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });

  if (isLoading) {
    return (
      <div className="bg-zinc-900 rounded-xl p-6">
        <div className="flex items-center justify-center gap-2 text-zinc-400">
          <Loader2 className="w-5 h-5 animate-spin" />
          Loading Spotify favorites...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-zinc-900 rounded-xl p-6">
        <p className="text-red-400 text-center">
          Failed to load unmatched tracks. Make sure Spotify is connected.
        </p>
      </div>
    );
  }

  if (!tracks || tracks.length === 0) {
    return (
      <div className="bg-zinc-900 rounded-xl p-6">
        <div className="text-center">
          <Music className="w-12 h-12 mx-auto mb-3 text-green-500" />
          <h3 className="text-lg font-medium mb-1">All caught up!</h3>
          <p className="text-zinc-400 text-sm">
            All your Spotify favorites are in your library.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-zinc-900 rounded-xl overflow-hidden">
      {/* Header */}
      <div
        className="p-4 flex items-center justify-between cursor-pointer hover:bg-zinc-800/50 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-3">
          <ShoppingCart className="w-5 h-5 text-green-500" />
          <div>
            <h3 className="font-semibold">Missing from Library</h3>
            <p className="text-sm text-zinc-400">
              {tracks.length} Spotify favorites you don't own
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {expanded ? (
            <ChevronUp className="w-5 h-5 text-zinc-400" />
          ) : (
            <ChevronDown className="w-5 h-5 text-zinc-400" />
          )}
        </div>
      </div>

      {expanded && (
        <>
          {/* Controls */}
          <div className="px-4 pb-3 flex items-center justify-between border-b border-zinc-800">
            <div className="flex items-center gap-2">
              <Clock className="w-3 h-3 text-zinc-500" />
              <span className="text-sm text-zinc-500">Sorted by date added</span>
            </div>

            {onImportClick && (
              <button
                onClick={onImportClick}
                className="text-sm text-green-500 hover:text-green-400 transition-colors"
              >
                Import purchased music
              </button>
            )}
          </div>

          {/* Track list */}
          <div className="max-h-96 overflow-y-auto">
            {tracks.map((track) => (
              <TrackRow key={track.spotify_id} track={track} />
            ))}
          </div>

          {/* Load more */}
          {tracks.length >= limit && (
            <div className="p-3 border-t border-zinc-800 text-center">
              <button
                onClick={() => setLimit((l) => l + 20)}
                className="text-sm text-zinc-400 hover:text-white transition-colors"
              >
                Load more...
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function TrackRow({ track }: { track: UnmatchedTrack }) {
  return (
    <div className="px-4 py-3 border-b border-zinc-800 last:border-0 hover:bg-zinc-800/30 transition-colors">
      <div className="flex items-start justify-between gap-4">
        {/* Track info */}
        <div className="flex-1 min-w-0">
          <p className="font-medium truncate">{track.name || 'Unknown Track'}</p>
          <p className="text-sm text-zinc-400 truncate">
            {track.artist || 'Unknown Artist'}
            {track.album && <span className="text-zinc-500"> - {track.album}</span>}
          </p>
        </div>

        {/* Search links */}
        <StoreSearchLinks
          artist={track.artist || 'Unknown Artist'}
          title={track.name || 'Unknown Track'}
          album={track.album}
        />
      </div>
    </div>
  );
}
