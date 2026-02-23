/**
 * Modal for manually matching an unmatched external favorite to a local library track.
 * Searches the library, shows results, and calls the manual match API.
 * After matching, offers to batch-match remaining tracks from the same album.
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { X, Search, Loader2, Music, Check, Album } from 'lucide-react';
import { tracksApi, externalTracksApi } from '../../api';
import type { ExternalFavoriteTrack } from '../../api';
import type { Track, TrackListResponse } from '../../types';
import { formatDuration } from '../../utils/format';
import { showSuccess, showError } from '../../stores/toastStore';

interface Props {
  externalTrack: ExternalFavoriteTrack;
  /** Other unmatched external favorites (for album batch prompt) */
  unmatchedExternals: ExternalFavoriteTrack[];
  onClose: () => void;
}

export function TrackMatchModal({ externalTrack, unmatchedExternals, onClose }: Props) {
  const [search, setSearch] = useState(externalTrack.artist || '');
  const [debouncedSearch, setDebouncedSearch] = useState(search);
  const [results, setResults] = useState<Track[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedTrack, setSelectedTrack] = useState<Track | null>(null);
  const [matching, setMatching] = useState(false);
  // After a successful match, show album batch prompt
  const [matchedAlbum, setMatchedAlbum] = useState<{ source: string; target: string; targetArtist: string | null; remaining: number } | null>(null);
  const [batchMatching, setBatchMatching] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();

  // Focus search on mount
  useEffect(() => {
    setTimeout(() => searchRef.current?.focus(), 50);
  }, []);

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(timer);
  }, [search]);

  // Search library when debounced search changes
  useEffect(() => {
    if (!debouncedSearch.trim()) {
      setResults([]);
      return;
    }

    let cancelled = false;
    setLoading(true);

    tracksApi.list({ search: debouncedSearch, page_size: 20 }).then((response: TrackListResponse) => {
      if (!cancelled) {
        setResults(response.items);
        setLoading(false);
      }
    }).catch(() => {
      if (!cancelled) {
        setResults([]);
        setLoading(false);
      }
    });

    return () => { cancelled = true; };
  }, [debouncedSearch]);

  const handleMatch = useCallback(async () => {
    if (!selectedTrack) return;
    setMatching(true);
    try {
      await externalTracksApi.manualMatch(externalTrack.id, selectedTrack.id);
      queryClient.invalidateQueries({ queryKey: ['favorites'] });
      queryClient.invalidateQueries({ queryKey: ['external-favorites'] });
      showSuccess(`Matched "${externalTrack.title}" to "${selectedTrack.title}"`);

      // Check if there are other unmatched tracks from the same album
      if (externalTrack.album) {
        const sameAlbum = unmatchedExternals.filter(
          (t) => t.id !== externalTrack.id && t.album && t.album === externalTrack.album && !t.is_matched,
        );
        if (sameAlbum.length > 0 && selectedTrack.album) {
          setMatchedAlbum({
            source: externalTrack.album,
            target: selectedTrack.album,
            targetArtist: selectedTrack.artist,
            remaining: sameAlbum.length,
          });
          setMatching(false);
          return;
        }
      }

      onClose();
    } catch {
      showError('Failed to match track');
    } finally {
      setMatching(false);
    }
  }, [selectedTrack, externalTrack, unmatchedExternals, queryClient, onClose]);

  const handleBatchMatch = useCallback(async () => {
    if (!matchedAlbum) return;
    setBatchMatching(true);
    try {
      const result = await externalTracksApi.matchByAlbum(
        matchedAlbum.source,
        matchedAlbum.target,
        matchedAlbum.targetArtist || undefined,
      );
      queryClient.invalidateQueries({ queryKey: ['favorites'] });
      queryClient.invalidateQueries({ queryKey: ['external-favorites'] });
      showSuccess(`Matched ${result.matched} tracks from "${matchedAlbum.source}"`);
      onClose();
    } catch {
      showError('Failed to batch match album');
    } finally {
      setBatchMatching(false);
    }
  }, [matchedAlbum, queryClient, onClose]);

  // Album batch prompt view
  if (matchedAlbum) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
        <div
          className="bg-zinc-800 border border-zinc-700 rounded-lg shadow-xl w-96 flex flex-col"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="flex items-center justify-between p-4 pb-3">
            <h3 className="text-sm font-medium text-white">Match Remaining Tracks?</h3>
            <button onClick={onClose} className="text-zinc-400 hover:text-white">
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="px-4 pb-4">
            <div className="flex items-start gap-3 mb-4">
              <Album className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
              <p className="text-sm text-zinc-300">
                {matchedAlbum.remaining} more unmatched {matchedAlbum.remaining === 1 ? 'track' : 'tracks'} from
                &ldquo;{matchedAlbum.source}&rdquo;. Match remaining by album?
              </p>
            </div>
            <div className="text-xs text-zinc-500 mb-4">
              Will match to &ldquo;{matchedAlbum.target}&rdquo;
              {matchedAlbum.targetArtist && ` by ${matchedAlbum.targetArtist}`}
            </div>
            <div className="flex gap-2">
              <button
                onClick={onClose}
                className="flex-1 px-3 py-2 text-sm bg-zinc-700 hover:bg-zinc-600 rounded transition-colors"
              >
                Skip
              </button>
              <button
                onClick={handleBatchMatch}
                disabled={batchMatching}
                className="flex-1 flex items-center justify-center gap-2 px-3 py-2 text-sm bg-green-600 hover:bg-green-500 disabled:opacity-50 rounded transition-colors"
              >
                {batchMatching ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  'Match Remaining'
                )}
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="bg-zinc-800 border border-zinc-700 rounded-lg shadow-xl w-96 max-h-[80vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 pb-3">
          <div className="min-w-0">
            <h3 className="text-sm font-medium text-white">Match Track</h3>
            <p className="text-xs text-zinc-400 truncate mt-0.5">
              {externalTrack.title} &mdash; {externalTrack.artist}
            </p>
          </div>
          <button onClick={onClose} className="text-zinc-400 hover:text-white shrink-0 ml-2">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Search */}
        <div className="px-4 pb-3">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-zinc-500" />
            <input
              ref={searchRef}
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setSelectedTrack(null);
              }}
              placeholder="Search library..."
              className="w-full pl-7 pr-2 py-1.5 text-sm bg-zinc-900 border border-zinc-600 rounded text-white placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
              onKeyDown={(e) => e.key === 'Escape' && onClose()}
            />
          </div>
        </div>

        {/* Results */}
        <div className="flex-1 min-h-0 overflow-y-auto px-2 pb-2">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-5 h-5 animate-spin text-zinc-400" />
            </div>
          ) : results.length === 0 ? (
            <div className="text-center py-8 text-sm text-zinc-500">
              {debouncedSearch.trim() ? 'No matches found' : 'Type to search your library'}
            </div>
          ) : (
            results.map((track) => {
              const isSelected = selectedTrack?.id === track.id;
              return (
                <button
                  key={track.id}
                  onClick={() => setSelectedTrack(isSelected ? null : track)}
                  className={`w-full flex items-center gap-3 px-2 py-2 rounded transition-colors text-left ${
                    isSelected
                      ? 'bg-green-600/20 ring-1 ring-green-500/50'
                      : 'hover:bg-zinc-700/50'
                  }`}
                >
                  <Music className="w-4 h-4 text-zinc-400 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-white truncate">{track.title || 'Unknown'}</div>
                    <div className="text-xs text-zinc-500 truncate">
                      {track.artist || 'Unknown'} &middot; {track.album || 'Unknown'}
                    </div>
                  </div>
                  <div className="text-xs text-zinc-500 shrink-0">
                    {formatDuration(track.duration_seconds)}
                  </div>
                  {isSelected && <Check className="w-4 h-4 text-green-400 shrink-0" />}
                </button>
              );
            })
          )}
        </div>

        {/* Match button */}
        <div className="p-3 border-t border-zinc-700">
          <button
            onClick={handleMatch}
            disabled={!selectedTrack || matching}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 text-sm bg-green-600 hover:bg-green-500 disabled:opacity-50 disabled:hover:bg-green-600 rounded transition-colors"
          >
            {matching ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              'Match'
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
