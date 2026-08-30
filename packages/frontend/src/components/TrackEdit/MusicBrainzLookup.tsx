import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Search, Loader2, Check, ExternalLink, Music } from 'lucide-react';
import api from '../../api';
import type { TrackMetadataUpdate } from '../../api';

interface MetadataCandidate {
  source: string;
  source_id: string;
  confidence: number;
  title: string | null;
  artist: string | null;
  album: string | null;
  album_artist: string | null;
  year: number | null;
  track_number: number | null;
  genre: string | null;
  artwork_url: string | null;
}

interface Props {
  title: string | null | undefined;
  artist: string | null | undefined;
  album: string | null | undefined;
  onApply: (metadata: Partial<TrackMetadataUpdate>) => void;
}

export function MusicBrainzLookup({ title, artist, album, onApply }: Props) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Lookup mutation
  const lookupMutation = useMutation({
    mutationFn: async () => {
      const { data } = await api.post<MetadataCandidate[]>('/tracks/lookup/metadata', {
        title: title || '',
        artist: artist || '',
        album: album || null,
      });
      return data;
    },
  });

  const handleSearch = () => {
    if (!title && !artist) {
      return;
    }
    setIsExpanded(true);
    lookupMutation.mutate();
  };

  const handleApply = (candidate: MetadataCandidate) => {
    setSelectedId(candidate.source_id);
    onApply({
      title: candidate.title,
      artist: candidate.artist,
      album: candidate.album,
      album_artist: candidate.album_artist,
      year: candidate.year,
      track_number: candidate.track_number,
      genre: candidate.genre,
    });
  };

  const formatConfidence = (confidence: number) => {
    return `${Math.round(confidence * 100)}%`;
  };

  if (!isExpanded) {
    return (
      <button
        onClick={handleSearch}
        disabled={!title && !artist}
        className="flex items-center gap-2 w-full px-4 py-3 bg-zinc-800/50 hover:bg-zinc-800 disabled:bg-zinc-900 disabled:text-zinc-600 border border-zinc-700 rounded-lg text-sm text-zinc-300 transition-colors"
      >
        <Search className="w-4 h-4" />
        Look up from MusicBrainz
      </button>
    );
  }

  return (
    <div className="border border-zinc-700 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-zinc-800/50 border-b border-zinc-700">
        <div className="flex items-center gap-2 text-sm text-zinc-300">
          <Search className="w-4 h-4" />
          MusicBrainz Lookup
        </div>
        <button
          onClick={() => setIsExpanded(false)}
          className="text-xs text-zinc-500 hover:text-zinc-300"
        >
          Close
        </button>
      </div>

      {/* Content */}
      <div className="p-4">
        {/* Search info */}
        <div className="mb-4 text-sm text-zinc-500">
          Searching for: <span className="text-zinc-300">{artist}</span>
          {title && <> - <span className="text-zinc-300">{title}</span></>}
        </div>

        {/* Loading */}
        {lookupMutation.isPending && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-6 h-6 animate-spin text-purple-400" />
          </div>
        )}

        {/* Error */}
        {lookupMutation.isError && (
          <div className="text-danger text-sm py-4">
            Failed to search MusicBrainz. Please try again.
          </div>
        )}

        {/* Results */}
        {lookupMutation.isSuccess && (
          <div className="space-y-2">
            {lookupMutation.data.length === 0 ? (
              <div className="text-zinc-500 text-sm py-4 text-center">
                No matches found
              </div>
            ) : (
              lookupMutation.data.map((candidate) => (
                <div
                  key={candidate.source_id}
                  className={`p-3 rounded-lg border transition-colors cursor-pointer ${
                    selectedId === candidate.source_id
                      ? 'border-purple-500 bg-purple-500/10'
                      : 'border-zinc-700 bg-zinc-800/30 hover:bg-zinc-800/50'
                  }`}
                  onClick={() => handleApply(candidate)}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <Music className="w-4 h-4 text-zinc-500 flex-shrink-0" />
                        <span className="font-medium text-white truncate">
                          {candidate.title || 'Unknown Title'}
                        </span>
                        {selectedId === candidate.source_id && (
                          <Check className="w-4 h-4 text-purple-400 flex-shrink-0" />
                        )}
                      </div>
                      <div className="text-sm text-zinc-400 mt-1">
                        {candidate.artist || 'Unknown Artist'}
                        {candidate.album && (
                          <> &middot; {candidate.album}</>
                        )}
                        {candidate.year && (
                          <> ({candidate.year})</>
                        )}
                      </div>
                      {candidate.genre && (
                        <div className="text-xs text-zinc-500 mt-1">
                          {candidate.genre}
                        </div>
                      )}
                    </div>
                    <div className="flex flex-col items-end gap-1">
                      <span
                        className={`text-xs px-2 py-0.5 rounded ${
                          candidate.confidence >= 0.8
                            ? 'bg-success-strong/20 text-success'
                            : candidate.confidence >= 0.5
                            ? 'bg-warning-strong/20 text-warning'
                            : 'bg-zinc-700 text-zinc-400'
                        }`}
                      >
                        {formatConfidence(candidate.confidence)}
                      </span>
                      <a
                        href={`https://musicbrainz.org/recording/${candidate.source_id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="text-xs text-zinc-500 hover:text-zinc-300 flex items-center gap-1"
                      >
                        <ExternalLink className="w-3 h-3" />
                        View
                      </a>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {/* Retry button */}
        {(lookupMutation.isSuccess || lookupMutation.isError) && (
          <button
            onClick={() => lookupMutation.mutate()}
            disabled={lookupMutation.isPending}
            className="mt-4 w-full flex items-center justify-center gap-2 px-4 py-2 bg-zinc-700 hover:bg-zinc-600 rounded-lg text-sm text-zinc-300 transition-colors"
          >
            <Search className="w-4 h-4" />
            Search Again
          </button>
        )}
      </div>
    </div>
  );
}
