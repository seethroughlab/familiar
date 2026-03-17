/**
 * AmbientSeedPicker — search for a track/artist or hit "Surprise Me" to start.
 */

import { useState } from 'react';
import { Search, Shuffle, Loader2 } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { tracksApi } from '../../api';
import { useThemeStore } from '../../stores/themeStore';

interface Props {
  onSelectTrack: (trackId: string) => void;
  onSelectArtist: (artist: string) => void;
  onSurpriseMe: () => void;
  isLoading: boolean;
}

export function AmbientSeedPicker({ onSelectTrack, onSelectArtist, onSurpriseMe, isLoading }: Props) {
  const [query, setQuery] = useState('');
  const light = useThemeStore((s) => s.resolvedTheme === 'light');

  const { data: results } = useQuery({
    queryKey: ['ambient-seed-search', query],
    queryFn: () => tracksApi.list({ search: query, page_size: 10, include_features: false }),
    enabled: query.length >= 2,
    staleTime: 30000,
  });

  const tracks = results?.items ?? [];

  // Extract unique artists from results
  const artists = [...new Set(tracks.map((t: { artist?: string | null }) => t.artist).filter(Boolean) as string[])].slice(0, 3);

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Surprise Me button */}
      <button
        onClick={onSurpriseMe}
        disabled={isLoading}
        className={`flex items-center justify-center gap-2 py-4 rounded-xl font-medium transition-colors ${
          light
            ? 'bg-green-50 text-green-700 active:bg-green-100'
            : 'bg-green-900/30 text-green-400 active:bg-green-900/50'
        } ${isLoading ? 'opacity-50' : ''}`}
      >
        {isLoading ? (
          <Loader2 className="w-5 h-5 animate-spin" />
        ) : (
          <Shuffle className="w-5 h-5" />
        )}
        <span>Surprise Me</span>
      </button>

      {/* Search input */}
      <div className={`flex items-center gap-2 px-3 py-2.5 rounded-xl ${
        light ? 'bg-zinc-100' : 'bg-zinc-800'
      }`}>
        <Search className="w-4 h-4 text-zinc-500 flex-shrink-0" />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search tracks or artists..."
          className={`flex-1 bg-transparent outline-none text-sm ${
            light ? 'text-zinc-900 placeholder:text-zinc-400' : 'text-white placeholder:text-zinc-500'
          }`}
        />
      </div>

      {/* Artist results */}
      {artists.length > 0 && (
        <div className="flex flex-col gap-1">
          <span className={`text-xs font-semibold uppercase tracking-wider px-1 ${light ? 'text-zinc-400' : 'text-zinc-500'}`}>
            Artists
          </span>
          {artists.map(artist => (
            <button
              key={artist}
              onClick={() => onSelectArtist(artist)}
              disabled={isLoading}
              className={`text-left px-3 py-2.5 rounded-lg transition-colors ${
                light ? 'active:bg-zinc-100 text-zinc-700' : 'active:bg-zinc-800 text-zinc-300'
              }`}
            >
              {artist}
            </button>
          ))}
        </div>
      )}

      {/* Track results */}
      {tracks.length > 0 && (
        <div className="flex flex-col gap-1">
          <span className={`text-xs font-semibold uppercase tracking-wider px-1 ${light ? 'text-zinc-400' : 'text-zinc-500'}`}>
            Tracks
          </span>
          {tracks.slice(0, 8).map((track: { id: string; title?: string | null; artist?: string | null }) => (
            <button
              key={track.id}
              onClick={() => onSelectTrack(track.id)}
              disabled={isLoading}
              className={`text-left px-3 py-2.5 rounded-lg transition-colors ${
                light ? 'active:bg-zinc-100' : 'active:bg-zinc-800'
              }`}
            >
              <div className={`text-sm truncate ${light ? 'text-zinc-900' : 'text-white'}`}>
                {track.title || 'Unknown'}
              </div>
              <div className={`text-xs truncate ${light ? 'text-zinc-500' : 'text-zinc-400'}`}>
                {track.artist || 'Unknown'}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
