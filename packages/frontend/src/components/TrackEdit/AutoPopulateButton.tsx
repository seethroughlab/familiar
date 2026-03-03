import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import {
  Fingerprint,
  Loader2,
  Check,
  ExternalLink,
  Music,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Image,
} from 'lucide-react';
import { tracksApi, type TrackMetadataUpdate, type IdentifyCandidate } from '../../api';

interface Props {
  trackId: string;
  onApply: (metadata: Partial<TrackMetadataUpdate>) => void;
}

function ConfidenceBadge({ score }: { score: number }) {
  const percent = Math.round(score * 100);
  const colorClass =
    score >= 0.8
      ? 'bg-green-500/20 text-green-400'
      : score >= 0.5
      ? 'bg-amber-500/20 text-amber-400'
      : 'bg-zinc-700 text-zinc-400';

  return (
    <span className={`text-xs px-2 py-0.5 rounded ${colorClass}`}>
      {percent}%
    </span>
  );
}

function CandidateCard({
  candidate,
  isSelected,
  onSelect,
}: {
  candidate: IdentifyCandidate;
  isSelected: boolean;
  onSelect: () => void;
}) {
  const [imageError, setImageError] = useState(false);

  return (
    <div
      className={`p-3 rounded-lg border transition-colors cursor-pointer ${
        isSelected
          ? 'border-purple-500 bg-purple-500/10'
          : 'border-zinc-700 bg-zinc-800/30 hover:bg-zinc-800/50'
      }`}
      onClick={onSelect}
    >
      <div className="flex gap-3">
        {/* Artwork thumbnail */}
        <div className="flex-shrink-0 w-12 h-12 rounded bg-zinc-700 overflow-hidden">
          {candidate.artwork_url && !imageError ? (
            <img
              src={candidate.artwork_url}
              alt=""
              className="w-full h-full object-cover"
              onError={() => setImageError(true)}
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center">
              <Image className="w-5 h-5 text-zinc-500" />
            </div>
          )}
        </div>

        {/* Main content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <Music className="w-4 h-4 text-zinc-500 flex-shrink-0" />
            <span className="font-medium text-white truncate">
              {candidate.title || 'Unknown Title'}
            </span>
            {isSelected && (
              <Check className="w-4 h-4 text-purple-400 flex-shrink-0" />
            )}
          </div>
          <div className="text-sm text-zinc-400 mt-0.5 truncate">
            {candidate.artist || 'Unknown Artist'}
            {candidate.album && <> &middot; {candidate.album}</>}
            {candidate.year && <> ({candidate.year})</>}
          </div>
          {/* Show additional metadata if available */}
          <div className="flex flex-wrap gap-2 mt-1">
            {candidate.track_number && (
              <span className="text-xs text-zinc-500">
                Track {candidate.track_number}
              </span>
            )}
            {candidate.genre && (
              <span className="text-xs text-zinc-500">{candidate.genre}</span>
            )}
            {candidate.composer && (
              <span className="text-xs text-zinc-500">
                Composer: {candidate.composer}
              </span>
            )}
          </div>
        </div>

        {/* Right side: confidence and link */}
        <div className="flex flex-col items-end gap-1 flex-shrink-0">
          <ConfidenceBadge score={candidate.acoustid_score} />
          <a
            href={candidate.musicbrainz_url}
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
  );
}

export function AutoPopulateButton({ trackId, onApply }: Props) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Identification mutation
  const identifyMutation = useMutation({
    mutationFn: () => tracksApi.identify(trackId),
  });

  const handleIdentify = () => {
    setIsExpanded(true);
    identifyMutation.mutate();
  };

  const handleApply = (candidate: IdentifyCandidate) => {
    setSelectedId(candidate.musicbrainz_recording_id);
    onApply({
      title: candidate.title,
      artist: candidate.artist,
      album: candidate.album,
      album_artist: candidate.album_artist,
      year: candidate.year,
      track_number: candidate.track_number,
      disc_number: candidate.disc_number,
      genre: candidate.genre,
      composer: candidate.composer,
    });
  };

  const toggleExpand = () => {
    if (!isExpanded) {
      handleIdentify();
    } else {
      setIsExpanded(false);
    }
  };

  // Collapsed state - just the button
  if (!isExpanded) {
    return (
      <button
        onClick={handleIdentify}
        className="flex items-center gap-2 w-full px-4 py-3 bg-gradient-to-r from-purple-500/20 to-indigo-500/20 hover:from-purple-500/30 hover:to-indigo-500/30 border border-purple-500/30 rounded-lg text-sm text-purple-300 transition-colors"
      >
        <Fingerprint className="w-4 h-4" />
        Auto-populate from audio fingerprint
      </button>
    );
  }

  return (
    <div className="border border-purple-500/30 rounded-lg overflow-hidden bg-zinc-900/50">
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 bg-gradient-to-r from-purple-500/10 to-indigo-500/10 border-b border-purple-500/20 cursor-pointer"
        onClick={toggleExpand}
      >
        <div className="flex items-center gap-2 text-sm text-purple-300">
          <Fingerprint className="w-4 h-4" />
          Audio Fingerprint Identification
        </div>
        <div className="flex items-center gap-2">
          {identifyMutation.isPending && (
            <Loader2 className="w-4 h-4 animate-spin text-purple-400" />
          )}
          {isExpanded ? (
            <ChevronUp className="w-4 h-4 text-zinc-500" />
          ) : (
            <ChevronDown className="w-4 h-4 text-zinc-500" />
          )}
        </div>
      </div>

      {/* Content */}
      <div className="p-4">
        {/* Loading state */}
        {identifyMutation.isPending && (
          <div className="flex flex-col items-center justify-center py-8 gap-3">
            <Loader2 className="w-8 h-8 animate-spin text-purple-400" />
            <p className="text-sm text-zinc-400">Analyzing audio fingerprint...</p>
          </div>
        )}

        {/* Error state */}
        {identifyMutation.isError && (
          <div className="flex items-start gap-3 py-4 text-red-400">
            <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium">Identification failed</p>
              <p className="text-sm text-red-400/80 mt-1">
                {identifyMutation.error instanceof Error
                  ? identifyMutation.error.message
                  : 'An error occurred'}
              </p>
            </div>
          </div>
        )}

        {/* Results */}
        {identifyMutation.isSuccess && (
          <div className="space-y-3">
            {/* Error from API response */}
            {identifyMutation.data.error && (
              <div className="flex items-start gap-3 p-3 bg-red-500/10 border border-red-500/20 rounded-lg">
                <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-medium text-red-400">
                    {identifyMutation.data.error_type === 'not_configured'
                      ? 'AcoustID not configured'
                      : identifyMutation.data.error_type === 'chromaprint_missing'
                      ? 'Chromaprint not installed'
                      : identifyMutation.data.error_type === 'file_not_found'
                      ? 'Audio file not found'
                      : 'Identification error'}
                  </p>
                  <p className="text-sm text-red-400/80 mt-1">
                    {identifyMutation.data.error}
                  </p>
                </div>
              </div>
            )}

            {/* No matches */}
            {!identifyMutation.data.error &&
              identifyMutation.data.candidates.length === 0 && (
                <div className="text-zinc-500 text-sm py-6 text-center">
                  <Music className="w-8 h-8 mx-auto mb-2 opacity-50" />
                  <p>No matches found for this audio fingerprint</p>
                  <p className="text-xs mt-1">
                    Try the text-based MusicBrainz lookup below
                  </p>
                </div>
              )}

            {/* Candidate list */}
            {identifyMutation.data.candidates.length > 0 && (
              <>
                <p className="text-xs text-zinc-500 mb-2">
                  Found {identifyMutation.data.candidates.length} match
                  {identifyMutation.data.candidates.length !== 1 ? 'es' : ''}.
                  Click to apply:
                </p>
                {identifyMutation.data.candidates.map((candidate) => (
                  <CandidateCard
                    key={candidate.musicbrainz_recording_id}
                    candidate={candidate}
                    isSelected={selectedId === candidate.musicbrainz_recording_id}
                    onSelect={() => handleApply(candidate)}
                  />
                ))}
              </>
            )}
          </div>
        )}

        {/* Retry button */}
        {(identifyMutation.isSuccess || identifyMutation.isError) && (
          <button
            onClick={() => identifyMutation.mutate()}
            disabled={identifyMutation.isPending}
            className="mt-4 w-full flex items-center justify-center gap-2 px-4 py-2 bg-zinc-700 hover:bg-zinc-600 rounded-lg text-sm text-zinc-300 transition-colors"
          >
            <Fingerprint className="w-4 h-4" />
            Scan Again
          </button>
        )}
      </div>
    </div>
  );
}
