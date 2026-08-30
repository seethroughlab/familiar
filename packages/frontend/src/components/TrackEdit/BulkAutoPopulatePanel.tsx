import { useState, useEffect, useCallback } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import {
  Fingerprint,
  Loader2,
  Check,
  X,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Image,
  CheckCircle,
} from 'lucide-react';
import {
  bulkTracksApi,
  type BulkIdentifyProgress,
  type IdentifyTrackResponse,
  type TrackMetadataUpdate,
} from '../../api';
import { queryKeys } from '../../api/queryKeys';

interface Props {
  trackIds: string[];
  onApplyToTrack: (trackId: string, metadata: Partial<TrackMetadataUpdate>) => void;
}

type ResultStatus = 'pending' | 'matched' | 'no_match' | 'error' | 'applied';

interface TrackResult {
  trackId: string;
  status: ResultStatus;
  result: IdentifyTrackResponse | null;
  selectedCandidateId: string | null;
  applied: boolean;
}

function ProgressBar({ current, total }: { current: number; total: number }) {
  const percent = total > 0 ? Math.round((current / total) * 100) : 0;
  return (
    <div className="w-full bg-zinc-700 rounded-full h-2 overflow-hidden">
      <div
        className="h-full bg-gradient-to-r from-purple-500 to-indigo-500 transition-all duration-300"
        style={{ width: `${percent}%` }}
      />
    </div>
  );
}

function ConfidenceBadge({ score }: { score: number }) {
  const percent = Math.round(score * 100);
  const colorClass =
    score >= 0.8
      ? 'bg-green-500/20 text-success'
      : score >= 0.5
      ? 'bg-amber-500/20 text-warning'
      : 'bg-zinc-700 text-zinc-400';

  return (
    <span className={`text-xs px-1.5 py-0.5 rounded ${colorClass}`}>
      {percent}%
    </span>
  );
}

function TrackResultCard({
  result,
  onSelectCandidate,
  onApply,
}: {
  result: TrackResult;
  onSelectCandidate: (trackId: string, candidateId: string) => void;
  onApply: (trackId: string) => void;
}) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [imageError, setImageError] = useState(false);

  const identifyResult = result.result;
  const candidates = identifyResult?.candidates || [];
  const bestCandidate = candidates[0];

  const statusIcon = {
    pending: <Loader2 className="w-4 h-4 animate-spin text-zinc-500" />,
    matched: <Check className="w-4 h-4 text-success" />,
    no_match: <X className="w-4 h-4 text-zinc-500" />,
    error: <AlertCircle className="w-4 h-4 text-danger" />,
    applied: <CheckCircle className="w-4 h-4 text-purple-400" />,
  };

  const statusText = {
    pending: 'Pending',
    matched: `${candidates.length} match${candidates.length !== 1 ? 'es' : ''}`,
    no_match: 'No match',
    error: 'Error',
    applied: 'Applied',
  };

  return (
    <div className="border border-zinc-700 rounded-lg overflow-hidden">
      {/* Header - always visible */}
      <div
        className={`flex items-center gap-3 px-3 py-2 cursor-pointer transition-colors ${
          result.status === 'applied'
            ? 'bg-purple-500/10'
            : result.status === 'matched'
            ? 'bg-zinc-800/50 hover:bg-zinc-800'
            : 'bg-zinc-900 hover:bg-zinc-800/50'
        }`}
        onClick={() => candidates.length > 0 && setIsExpanded(!isExpanded)}
      >
        {/* Status icon */}
        <div className="flex-shrink-0">{statusIcon[result.status]}</div>

        {/* Track info */}
        <div className="flex-1 min-w-0">
          {bestCandidate ? (
            <div>
              <span className="text-sm text-white truncate block">
                {bestCandidate.title || 'Unknown'}
              </span>
              <span className="text-xs text-zinc-400 truncate block">
                {bestCandidate.artist || 'Unknown Artist'}
              </span>
            </div>
          ) : (
            <span className="text-sm text-zinc-400 truncate block">
              Track {result.trackId.slice(0, 8)}...
            </span>
          )}
        </div>

        {/* Status badge */}
        <div className="flex items-center gap-2 flex-shrink-0">
          {bestCandidate && (
            <ConfidenceBadge score={bestCandidate.acoustid_score} />
          )}
          <span className="text-xs text-zinc-500">{statusText[result.status]}</span>
          {candidates.length > 0 && (
            isExpanded ? (
              <ChevronUp className="w-4 h-4 text-zinc-500" />
            ) : (
              <ChevronDown className="w-4 h-4 text-zinc-500" />
            )
          )}
        </div>
      </div>

      {/* Expanded content - candidate selection */}
      {isExpanded && candidates.length > 0 && (
        <div className="border-t border-zinc-700 p-3 bg-zinc-900/50 space-y-2">
          {candidates.map((candidate) => (
            <div
              key={candidate.musicbrainz_recording_id}
              className={`flex items-center gap-3 p-2 rounded-lg cursor-pointer transition-colors ${
                result.selectedCandidateId === candidate.musicbrainz_recording_id
                  ? 'bg-purple-500/20 border border-purple-500/30'
                  : 'bg-zinc-800/30 hover:bg-zinc-800/50 border border-transparent'
              }`}
              onClick={() =>
                onSelectCandidate(result.trackId, candidate.musicbrainz_recording_id)
              }
            >
              {/* Thumbnail */}
              <div className="flex-shrink-0 w-10 h-10 rounded bg-zinc-700 overflow-hidden">
                {candidate.artwork_url && !imageError ? (
                  <img
                    src={candidate.artwork_url}
                    alt=""
                    className="w-full h-full object-cover"
                    onError={() => setImageError(true)}
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center">
                    <Image className="w-4 h-4 text-zinc-500" />
                  </div>
                )}
              </div>

              {/* Info */}
              <div className="flex-1 min-w-0">
                <div className="text-sm text-white truncate">
                  {candidate.title || 'Unknown'}
                </div>
                <div className="text-xs text-zinc-400 truncate">
                  {candidate.artist}
                  {candidate.album && ` - ${candidate.album}`}
                  {candidate.year && ` (${candidate.year})`}
                </div>
              </div>

              {/* Confidence and select indicator */}
              <div className="flex items-center gap-2 flex-shrink-0">
                <ConfidenceBadge score={candidate.acoustid_score} />
                {result.selectedCandidateId === candidate.musicbrainz_recording_id && (
                  <Check className="w-4 h-4 text-purple-400" />
                )}
              </div>
            </div>
          ))}

          {/* Apply button */}
          {result.selectedCandidateId && !result.applied && (
            <button
              onClick={() => onApply(result.trackId)}
              className="w-full mt-2 px-3 py-2 bg-purple-500 hover:bg-purple-600 rounded-lg text-sm text-white font-medium transition-colors"
            >
              Apply Selected
            </button>
          )}
        </div>
      )}

      {/* Error message */}
      {result.status === 'error' && identifyResult?.error && (
        <div className="border-t border-zinc-700 px-3 py-2 bg-red-500/10">
          <p className="text-xs text-danger">{identifyResult.error}</p>
        </div>
      )}
    </div>
  );
}

export function BulkAutoPopulatePanel({ trackIds, onApplyToTrack }: Props) {
  const [taskId, setTaskId] = useState<string | null>(null);
  const [trackResults, setTrackResults] = useState<Map<string, TrackResult>>(
    new Map()
  );
  const [isExpanded, setIsExpanded] = useState(false);

  // Start bulk identification
  const startMutation = useMutation({
    mutationFn: () => bulkTracksApi.startIdentify(trackIds),
    onSuccess: (data) => {
      setTaskId(data.task_id);
      setIsExpanded(true);
      // Initialize pending results
      const initial = new Map<string, TrackResult>();
      trackIds.forEach((id) => {
        initial.set(id, {
          trackId: id,
          status: 'pending',
          result: null,
          selectedCandidateId: null,
          applied: false,
        });
      });
      setTrackResults(initial);
    },
  });

  // Poll for progress
  const { data: progress } = useQuery<BulkIdentifyProgress>({
    queryKey: queryKeys.bulkIdentify.detail(taskId!),
    queryFn: () => bulkTracksApi.getIdentifyProgress(taskId!),
    enabled: !!taskId && startMutation.isSuccess,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return 1000;
      if (data.status === 'running') return 1000;
      return false; // Stop polling when complete
    },
  });

  // Update track results when progress changes
  useEffect(() => {
    if (!progress) return;

    setTrackResults((prev) => {
      const updated = new Map(prev);

      // Update results from progress
      for (const result of progress.results) {
        const existing = updated.get(result.track_id);
        if (existing && !existing.applied) {
          const hasMatches = result.candidates.length > 0;
          const hasError = !!result.error;

          updated.set(result.track_id, {
            ...existing,
            status: hasError ? 'error' : hasMatches ? 'matched' : 'no_match',
            result,
            // Auto-select best match if score > 0.8
            selectedCandidateId:
              hasMatches && result.candidates[0].acoustid_score >= 0.8
                ? result.candidates[0].musicbrainz_recording_id
                : existing.selectedCandidateId,
          });
        }
      }

      return updated;
    });
  }, [progress]);

  const handleSelectCandidate = useCallback(
    (trackId: string, candidateId: string) => {
      setTrackResults((prev) => {
        const updated = new Map(prev);
        const existing = updated.get(trackId);
        if (existing) {
          updated.set(trackId, {
            ...existing,
            selectedCandidateId: candidateId,
          });
        }
        return updated;
      });
    },
    []
  );

  const handleApplySingle = useCallback(
    (trackId: string) => {
      const result = trackResults.get(trackId);
      if (!result?.result?.candidates || !result.selectedCandidateId) return;

      const candidate = result.result.candidates.find(
        (c) => c.musicbrainz_recording_id === result.selectedCandidateId
      );
      if (!candidate) return;

      // Apply metadata
      onApplyToTrack(trackId, {
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

      // Mark as applied
      setTrackResults((prev) => {
        const updated = new Map(prev);
        const existing = updated.get(trackId);
        if (existing) {
          updated.set(trackId, {
            ...existing,
            status: 'applied',
            applied: true,
          });
        }
        return updated;
      });
    },
    [trackResults, onApplyToTrack]
  );

  const handleApplyAllBest = useCallback(() => {
    trackResults.forEach((result, trackId) => {
      if (
        result.status === 'matched' &&
        result.selectedCandidateId &&
        !result.applied
      ) {
        handleApplySingle(trackId);
      }
    });
  }, [trackResults, handleApplySingle]);

  // Calculate stats
  const stats = {
    total: trackIds.length,
    processed: progress?.processed_tracks || 0,
    matched: Array.from(trackResults.values()).filter(
      (r) => r.status === 'matched' || r.status === 'applied'
    ).length,
    applied: Array.from(trackResults.values()).filter((r) => r.applied).length,
    pending: Array.from(trackResults.values()).filter(
      (r) => r.status === 'pending'
    ).length,
  };

  const isRunning = progress?.status === 'running';
  const isComplete = progress?.status === 'completed';

  // Collapsed state
  if (!isExpanded && !taskId) {
    return (
      <button
        onClick={() => startMutation.mutate()}
        disabled={startMutation.isPending}
        className="flex items-center gap-2 w-full px-4 py-3 bg-gradient-to-r from-purple-500/20 to-indigo-500/20 hover:from-purple-500/30 hover:to-indigo-500/30 border border-purple-500/30 rounded-lg text-sm text-purple-300 transition-colors disabled:opacity-50"
      >
        {startMutation.isPending ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : (
          <Fingerprint className="w-4 h-4" />
        )}
        Auto-populate All ({trackIds.length} tracks)
      </button>
    );
  }

  return (
    <div className="border border-purple-500/30 rounded-lg overflow-hidden bg-zinc-900/50">
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 bg-gradient-to-r from-purple-500/10 to-indigo-500/10 border-b border-purple-500/20 cursor-pointer"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-2 text-sm text-purple-300">
          <Fingerprint className="w-4 h-4" />
          Bulk Audio Fingerprint Identification
        </div>
        <div className="flex items-center gap-3">
          {isRunning && (
            <span className="text-xs text-zinc-400">
              {stats.processed}/{stats.total}
            </span>
          )}
          {isComplete && (
            <span className="text-xs text-success">
              {stats.matched} matched
            </span>
          )}
          {isExpanded ? (
            <ChevronUp className="w-4 h-4 text-zinc-500" />
          ) : (
            <ChevronDown className="w-4 h-4 text-zinc-500" />
          )}
        </div>
      </div>

      {/* Progress bar */}
      {isRunning && (
        <div className="px-4 py-2 border-b border-zinc-800">
          <ProgressBar current={stats.processed} total={stats.total} />
          <p className="text-xs text-zinc-500 mt-1 text-center">
            Processing track {stats.processed + 1} of {stats.total}...
          </p>
        </div>
      )}

      {/* Content */}
      {isExpanded && (
        <div className="p-4">
          {/* Stats summary */}
          {isComplete && (
            <div className="flex items-center justify-between mb-4 p-3 bg-zinc-800/50 rounded-lg">
              <div className="flex items-center gap-4 text-sm">
                <span className="text-zinc-400">
                  <span className="text-white font-medium">{stats.matched}</span> matched
                </span>
                <span className="text-zinc-400">
                  <span className="text-white font-medium">{stats.applied}</span> applied
                </span>
                <span className="text-zinc-400">
                  <span className="text-white font-medium">
                    {stats.total - stats.matched}
                  </span>{' '}
                  no match
                </span>
              </div>
              {stats.matched > stats.applied && (
                <button
                  onClick={handleApplyAllBest}
                  className="px-3 py-1.5 bg-purple-500 hover:bg-purple-600 rounded-lg text-xs text-white font-medium transition-colors"
                >
                  Apply All Best Matches
                </button>
              )}
            </div>
          )}

          {/* Results list */}
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {Array.from(trackResults.values()).map((result) => (
              <TrackResultCard
                key={result.trackId}
                result={result}
                onSelectCandidate={handleSelectCandidate}
                onApply={handleApplySingle}
              />
            ))}
          </div>

          {/* Errors */}
          {progress?.errors && progress.errors.length > 0 && (
            <div className="mt-4 p-3 bg-red-500/10 border border-danger/20 rounded-lg">
              <p className="text-sm font-medium text-danger mb-2">
                {progress.errors.length} error{progress.errors.length !== 1 ? 's' : ''}
              </p>
              <ul className="text-xs text-danger/80 space-y-1">
                {progress.errors.slice(0, 5).map((error, i) => (
                  <li key={i}>{error}</li>
                ))}
                {progress.errors.length > 5 && (
                  <li>...and {progress.errors.length - 5} more</li>
                )}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
