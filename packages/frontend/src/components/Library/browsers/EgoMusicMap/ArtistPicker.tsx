/**
 * Artist Picker for Ego Music Map.
 *
 * Search dropdown to select the center artist for the map.
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { Search, X, Loader2 } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { libraryApi } from '../../../../api';
import { tracksApi } from '../../../../api';

interface ArtistPickerProps {
  onSelect: (artistName: string) => void;
  onClose: () => void;
  initialValue?: string;
}

export function ArtistPicker({ onSelect, onClose, initialValue = '' }: ArtistPickerProps) {
  const [search, setSearch] = useState(initialValue);
  const [debouncedSearch, setDebouncedSearch] = useState(initialValue);
  const inputRef = useRef<HTMLInputElement>(null);

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  // Fetch artists matching search (only artists with embeddings for the music map)
  const { data, isLoading } = useQuery({
    queryKey: ['artists-picker', debouncedSearch],
    queryFn: () =>
      libraryApi.listArtists({
        search: debouncedSearch || undefined,
        sort_by: debouncedSearch ? 'name' : 'track_count',
        page_size: 20,
        has_embeddings: true,
      }),
    staleTime: 30000,
  });

  const handleSelect = useCallback(
    (artistName: string) => {
      onSelect(artistName);
    },
    [onSelect]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    },
    [onClose]
  );

  return (
    <div
      className="absolute inset-0 z-20 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md mx-4 bg-zinc-900 rounded-xl shadow-2xl border border-zinc-700 overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-4 py-3 border-b border-zinc-700 flex items-center justify-between">
          <h2 className="text-lg font-medium text-white">Choose an artist to explore</h2>
          <button
            onClick={onClose}
            className="p-1 text-zinc-400 hover:text-white rounded-lg hover:bg-zinc-700"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Search input */}
        <div className="p-4 border-b border-zinc-800">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-zinc-500" />
            <input
              ref={inputRef}
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Search artists..."
              className="w-full pl-10 pr-4 py-2.5 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:border-purple-500 focus:ring-1 focus:ring-purple-500"
            />
            {isLoading && (
              <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 w-5 h-5 text-zinc-500 animate-spin" />
            )}
          </div>
          <p className="mt-2 text-xs text-zinc-500">
            {search
              ? 'Matching artists with embeddings'
              : 'Showing artists with most tracks (with embeddings)'}
          </p>
        </div>

        {/* Artist list */}
        <div className="max-h-80 overflow-y-auto">
          {data?.items.length === 0 ? (
            <div className="py-8 text-center text-zinc-500">
              No artists found
            </div>
          ) : (
            <ul className="divide-y divide-zinc-800">
              {data?.items.map((artist) => (
                <li key={artist.name}>
                  <button
                    onClick={() => handleSelect(artist.name)}
                    className="w-full px-4 py-3 flex items-center gap-3 hover:bg-zinc-800 transition-colors text-left"
                  >
                    {/* Artist artwork */}
                    <img
                      src={tracksApi.getArtworkUrl(artist.first_track_id, 'thumb')}
                      alt=""
                      className="w-10 h-10 rounded-lg object-cover bg-zinc-700"
                      onError={(e) => {
                        (e.target as HTMLImageElement).src =
                          'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="%2371717a"><circle cx="12" cy="8" r="4"/><path d="M20 21a8 8 0 0 0-16 0"/></svg>';
                      }}
                    />
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-white truncate">
                        {artist.name}
                      </div>
                      <div className="text-sm text-zinc-500">
                        {artist.track_count} tracks
                        {artist.album_count > 0 && ` · ${artist.album_count} albums`}
                      </div>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Footer hint */}
        <div className="px-4 py-3 border-t border-zinc-800 text-xs text-zinc-500 text-center">
          Select an artist to see similar artists radiating outward
        </div>
      </div>
    </div>
  );
}
