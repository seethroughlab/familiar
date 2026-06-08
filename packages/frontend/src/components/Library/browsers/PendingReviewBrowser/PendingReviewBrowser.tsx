/**
 * PendingReviewBrowser - Review queue for newly discovered tracks.
 *
 * Displays pending tracks grouped by folder with approve/skip/replace actions.
 */
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Inbox,
  CheckCircle,
  ArrowUpCircle,
  ArrowDownCircle,
  Loader2,
  AlertCircle,
  ChevronDown,
  ChevronRight,
  Music,
  RefreshCw,
  RotateCcw,
  SkipForward,
  Check,
  Pencil,
  X,
} from 'lucide-react';
import { pendingTracksApi } from '../../../../api/pendingTracks';
import type { PendingTrackGroup, PendingTrack, MetadataUpdate } from '../../../../api/pendingTracks';
import type { BrowserProps } from '../../types';
import { queryKeys } from '../../../../api/queryKeys';

type FilterTab = 'all' | 'duplicates' | 'clean';

function formatDuration(seconds: number | null): string {
  if (!seconds) return '--:--';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function TrumpBadge({ status }: { status?: string }) {
  if (status === 'trumps') {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-1.5 py-0.5 bg-green-900/50 text-green-400 rounded">
        <ArrowUpCircle className="w-3 h-3" />
        Upgrade
      </span>
    );
  }
  if (status === 'trumped_by') {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-1.5 py-0.5 bg-red-900/50 text-red-400 rounded">
        <ArrowDownCircle className="w-3 h-3" />
        Downgrade
      </span>
    );
  }
  if (status === 'equal') {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-1.5 py-0.5 bg-zinc-700 text-zinc-300 rounded">
        Equal
      </span>
    );
  }
  return null;
}

function TrackEditForm({
  track,
  onSave,
  onCancel,
  isSaving,
}: {
  track: PendingTrack;
  onSave: (metadata: MetadataUpdate) => void;
  onCancel: () => void;
  isSaving: boolean;
}) {
  const [artist, setArtist] = useState(track.artist ?? '');
  const [album, setAlbum] = useState(track.album ?? '');
  const [title, setTitle] = useState(track.title ?? '');
  const [trackNumber, setTrackNumber] = useState(track.track_number?.toString() ?? '');
  const [year, setYear] = useState(track.year?.toString() ?? '');

  const handleSave = () => {
    const metadata: MetadataUpdate = {};
    if (artist !== (track.artist ?? '')) metadata.artist = artist;
    if (album !== (track.album ?? '')) metadata.album = album;
    if (title !== (track.title ?? '')) metadata.title = title;
    if (trackNumber !== (track.track_number?.toString() ?? '')) {
      metadata.track_number = trackNumber ? parseInt(trackNumber, 10) : undefined;
    }
    if (year !== (track.year?.toString() ?? '')) {
      metadata.year = year ? parseInt(year, 10) : undefined;
    }
    onSave(metadata);
  };

  const inputClass = 'bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-sm text-white focus:outline-none focus:border-blue-500';

  return (
    <div className="px-3 py-2 ml-7 bg-zinc-800/50 rounded-lg mb-1">
      <div className="grid grid-cols-2 gap-2">
        <label className="block">
          <span className="text-xs text-zinc-400">Title</span>
          <input className={inputClass + ' w-full'} value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label className="block">
          <span className="text-xs text-zinc-400">Artist</span>
          <input className={inputClass + ' w-full'} value={artist} onChange={(e) => setArtist(e.target.value)} />
        </label>
        <label className="block">
          <span className="text-xs text-zinc-400">Album</span>
          <input className={inputClass + ' w-full'} value={album} onChange={(e) => setAlbum(e.target.value)} />
        </label>
        <div className="flex gap-2">
          <label className="block flex-1">
            <span className="text-xs text-zinc-400">Track #</span>
            <input className={inputClass + ' w-full'} type="number" value={trackNumber} onChange={(e) => setTrackNumber(e.target.value)} />
          </label>
          <label className="block flex-1">
            <span className="text-xs text-zinc-400">Year</span>
            <input className={inputClass + ' w-full'} type="number" value={year} onChange={(e) => setYear(e.target.value)} />
          </label>
        </div>
      </div>
      <div className="flex justify-end gap-2 mt-2">
        <button
          onClick={onCancel}
          className="px-2 py-1 rounded text-xs bg-zinc-700 hover:bg-zinc-600 text-zinc-300"
        >
          Cancel
        </button>
        <button
          onClick={handleSave}
          disabled={isSaving}
          className="px-2 py-1 rounded text-xs bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50"
        >
          {isSaving ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Save'}
        </button>
      </div>
    </div>
  );
}

function GroupEditForm({
  group,
  onSave,
  onCancel,
  isSaving,
}: {
  group: PendingTrackGroup;
  onSave: (metadata: Record<string, unknown>) => void;
  onCancel: () => void;
  isSaving: boolean;
}) {
  const firstTrack = group.tracks[0];
  const [artist, setArtist] = useState(firstTrack?.artist ?? '');
  const [album, setAlbum] = useState(firstTrack?.album ?? '');
  const [year, setYear] = useState(firstTrack?.year?.toString() ?? '');

  const handleSave = () => {
    const metadata: Record<string, unknown> = {};
    if (artist) metadata.artist = artist;
    if (album) metadata.album = album;
    if (year) metadata.year = parseInt(year, 10);
    onSave(metadata);
  };

  const inputClass = 'bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-sm text-white focus:outline-none focus:border-blue-500';

  return (
    <div className="px-4 py-2 bg-zinc-800/50 border-t border-zinc-800">
      <div className="flex items-end gap-2">
        <label className="block flex-1">
          <span className="text-xs text-zinc-400">Artist</span>
          <input className={inputClass + ' w-full'} value={artist} onChange={(e) => setArtist(e.target.value)} />
        </label>
        <label className="block flex-1">
          <span className="text-xs text-zinc-400">Album</span>
          <input className={inputClass + ' w-full'} value={album} onChange={(e) => setAlbum(e.target.value)} />
        </label>
        <label className="block w-24">
          <span className="text-xs text-zinc-400">Year</span>
          <input className={inputClass + ' w-full'} type="number" value={year} onChange={(e) => setYear(e.target.value)} />
        </label>
        <button
          onClick={onCancel}
          className="px-2 py-1 rounded text-xs bg-zinc-700 hover:bg-zinc-600 text-zinc-300 mb-0.5"
        >
          Cancel
        </button>
        <button
          onClick={handleSave}
          disabled={isSaving}
          className="px-2 py-1 rounded text-xs bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 mb-0.5"
        >
          {isSaving ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Save All'}
        </button>
      </div>
    </div>
  );
}

function TrackRow({
  track,
  onApprove,
  onSkip,
  onReplace,
  isLoading,
  isEditing,
  onEdit,
  onCancelEdit,
  onSaveEdit,
  isSavingEdit,
}: {
  track: PendingTrack;
  onApprove: () => void;
  onSkip: () => void;
  onReplace: () => void;
  isLoading: boolean;
  isEditing: boolean;
  onEdit: () => void;
  onCancelEdit: () => void;
  onSaveEdit: (metadata: MetadataUpdate) => void;
  isSavingEdit: boolean;
}) {
  const hasDuplicate = track.review_info?.duplicate_of;

  return (
    <>
      <div className="flex items-center gap-3 px-3 py-2 hover:bg-zinc-800/50 rounded-lg group">
        <Music className="w-4 h-4 text-zinc-500 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm text-white truncate">{track.title || '(untitled)'}</span>
            {track.track_number && (
              <span className="text-xs text-zinc-500">#{track.track_number}</span>
            )}
            <TrumpBadge status={track.review_info?.trump_status} />
          </div>
          <div className="flex items-center gap-2 text-xs text-zinc-500">
            <span>{track.artist || 'Unknown'}</span>
            {track.album && (
              <>
                <span className="text-zinc-600">&middot;</span>
                <span>{track.album}</span>
              </>
            )}
            <span className="text-zinc-600">&middot;</span>
            <span>{track.format?.toUpperCase()}</span>
            {track.bitrate && <span>{track.bitrate}kbps</span>}
            <span>{formatDuration(track.duration_seconds)}</span>
          </div>
          {hasDuplicate && track.review_info?.duplicate_info && (
            <div className="text-xs text-amber-500/80 mt-0.5">
              Duplicate of: {track.review_info.duplicate_info}
              {track.review_info.trump_reason && (
                <span className="text-zinc-500 ml-1">({track.review_info.trump_reason})</span>
              )}
            </div>
          )}
        </div>
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={onEdit}
            disabled={isLoading}
            className="p-1.5 rounded bg-zinc-700 hover:bg-zinc-600 text-zinc-300 text-xs disabled:opacity-50"
            title="Edit metadata"
          >
            <Pencil className="w-3.5 h-3.5" />
          </button>
          {hasDuplicate && track.review_info?.trump_status === 'trumps' && (
            <button
              onClick={onReplace}
              disabled={isLoading}
              className="p-1.5 rounded bg-blue-600 hover:bg-blue-700 text-white text-xs disabled:opacity-50"
              title="Replace existing"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          )}
          <button
            onClick={onApprove}
            disabled={isLoading}
            className="p-1.5 rounded bg-green-600 hover:bg-green-700 text-white text-xs disabled:opacity-50"
            title="Import"
          >
            <Check className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={onSkip}
            disabled={isLoading}
            className="p-1.5 rounded bg-zinc-600 hover:bg-zinc-500 text-white text-xs disabled:opacity-50"
            title="Skip"
          >
            <SkipForward className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
      {isEditing && (
        <TrackEditForm
          track={track}
          onSave={onSaveEdit}
          onCancel={onCancelEdit}
          isSaving={isSavingEdit}
        />
      )}
    </>
  );
}

function GroupCard({
  group,
  queueAnalysis,
  onInvalidate,
}: {
  group: PendingTrackGroup;
  queueAnalysis: boolean;
  onInvalidate: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [loadingTrackId, setLoadingTrackId] = useState<string | null>(null);
  const [editingTrackId, setEditingTrackId] = useState<string | null>(null);
  const [isEditingGroup, setIsEditingGroup] = useState(false);

  const approveMutation = useMutation({
    mutationFn: (trackId: string) => pendingTracksApi.approve(trackId, { queue_analysis: queueAnalysis }),
    onSuccess: onInvalidate,
  });

  const skipMutation = useMutation({
    mutationFn: (trackId: string) => pendingTracksApi.skip(trackId),
    onSuccess: onInvalidate,
  });

  const replaceMutation = useMutation({
    mutationFn: (trackId: string) => {
      const track = group.tracks.find(t => t.id === trackId);
      const duplicateOf = track?.review_info?.duplicate_of;
      if (!duplicateOf) throw new Error('No duplicate to replace');
      return pendingTracksApi.replace(trackId, { replace_track_id: duplicateOf, queue_analysis: queueAnalysis });
    },
    onSuccess: onInvalidate,
  });

  const trackMetadataMutation = useMutation({
    mutationFn: ({ trackId, metadata }: { trackId: string; metadata: MetadataUpdate }) =>
      pendingTracksApi.updateMetadata(trackId, metadata),
    onSuccess: () => {
      setEditingTrackId(null);
      onInvalidate();
    },
  });

  const groupMetadataMutation = useMutation({
    mutationFn: (metadata: Record<string, unknown>) =>
      pendingTracksApi.groupMetadata(group.folder_path, metadata),
    onSuccess: () => {
      setIsEditingGroup(false);
      onInvalidate();
    },
  });

  const groupApproveMutation = useMutation({
    mutationFn: () => pendingTracksApi.groupApprove(group.folder_path, { queue_analysis: queueAnalysis }),
    onSuccess: onInvalidate,
  });

  const groupSkipMutation = useMutation({
    mutationFn: () => pendingTracksApi.groupSkip(group.folder_path),
    onSuccess: onInvalidate,
  });

  const groupReplaceUpgradesMutation = useMutation({
    mutationFn: () => pendingTracksApi.groupReplaceUpgrades(group.folder_path, { queue_analysis: queueAnalysis }),
    onSuccess: onInvalidate,
  });

  const groupSkipDowngradesMutation = useMutation({
    mutationFn: () => pendingTracksApi.groupSkipDowngrades(group.folder_path),
    onSuccess: onInvalidate,
  });

  const isGroupLoading =
    groupApproveMutation.isPending ||
    groupSkipMutation.isPending ||
    groupReplaceUpgradesMutation.isPending ||
    groupSkipDowngradesMutation.isPending;

  return (
    <div className="rounded-lg border border-zinc-700 bg-zinc-900/50 overflow-hidden">
      {/* Group header */}
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-zinc-800/50"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? (
          <ChevronDown className="w-4 h-4 text-zinc-400 flex-shrink-0" />
        ) : (
          <ChevronRight className="w-4 h-4 text-zinc-400 flex-shrink-0" />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-white truncate">{group.folder_name}</span>
            <span className="text-xs text-zinc-500">{group.track_count} track{group.track_count !== 1 ? 's' : ''}</span>
          </div>
          <div className="flex items-center gap-2 text-xs text-zinc-500 mt-0.5">
            {group.duplicate_count > 0 && (
              <span className="text-amber-400">{group.duplicate_count} duplicate{group.duplicate_count !== 1 ? 's' : ''}</span>
            )}
            {group.upgrade_count > 0 && (
              <span className="text-green-400">{group.upgrade_count} upgrade{group.upgrade_count !== 1 ? 's' : ''}</span>
            )}
            {group.downgrade_count > 0 && (
              <span className="text-red-400">{group.downgrade_count} downgrade{group.downgrade_count !== 1 ? 's' : ''}</span>
            )}
          </div>
        </div>

        {/* Group actions */}
        <div className="flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <button
            onClick={() => setIsEditingGroup(!isEditingGroup)}
            disabled={isGroupLoading}
            className="p-1.5 rounded bg-zinc-700 hover:bg-zinc-600 text-zinc-300 text-xs disabled:opacity-50"
            title="Edit group metadata"
          >
            <Pencil className="w-3.5 h-3.5" />
          </button>
          {group.upgrade_count > 0 && (
            <button
              onClick={() => groupReplaceUpgradesMutation.mutate()}
              disabled={isGroupLoading}
              className="px-2 py-1 rounded text-xs bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50"
              title="Replace upgrades"
            >
              Replace Upgrades
            </button>
          )}
          {group.downgrade_count > 0 && (
            <button
              onClick={() => groupSkipDowngradesMutation.mutate()}
              disabled={isGroupLoading}
              className="px-2 py-1 rounded text-xs bg-zinc-600 hover:bg-zinc-500 text-white disabled:opacity-50"
              title="Skip downgrades"
            >
              Skip Downgrades
            </button>
          )}
          <button
            onClick={() => groupApproveMutation.mutate()}
            disabled={isGroupLoading}
            className="px-2 py-1 rounded text-xs bg-green-600 hover:bg-green-700 text-white disabled:opacity-50"
          >
            {isGroupLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Import All'}
          </button>
          <button
            onClick={() => groupSkipMutation.mutate()}
            disabled={isGroupLoading}
            className="px-2 py-1 rounded text-xs bg-zinc-600 hover:bg-zinc-500 text-white disabled:opacity-50"
          >
            Skip All
          </button>
        </div>
      </div>

      {/* Group metadata editor */}
      {isEditingGroup && (
        <GroupEditForm
          group={group}
          onSave={(metadata) => groupMetadataMutation.mutate(metadata)}
          onCancel={() => setIsEditingGroup(false)}
          isSaving={groupMetadataMutation.isPending}
        />
      )}

      {/* Expanded tracks */}
      {expanded && (
        <div className="border-t border-zinc-800 py-1">
          {group.tracks.map((track) => (
            <TrackRow
              key={track.id}
              track={track}
              onApprove={() => {
                setLoadingTrackId(track.id);
                approveMutation.mutate(track.id, { onSettled: () => setLoadingTrackId(null) });
              }}
              onSkip={() => {
                setLoadingTrackId(track.id);
                skipMutation.mutate(track.id, { onSettled: () => setLoadingTrackId(null) });
              }}
              onReplace={() => {
                setLoadingTrackId(track.id);
                replaceMutation.mutate(track.id, { onSettled: () => setLoadingTrackId(null) });
              }}
              isLoading={loadingTrackId === track.id}
              isEditing={editingTrackId === track.id}
              onEdit={() => setEditingTrackId(editingTrackId === track.id ? null : track.id)}
              onCancelEdit={() => setEditingTrackId(null)}
              onSaveEdit={(metadata) => trackMetadataMutation.mutate({ trackId: track.id, metadata })}
              isSavingEdit={trackMetadataMutation.isPending}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/** Read-only group card for the Skipped view: per-track and per-group "Un-skip". */
function SkippedGroupCard({
  group,
  onInvalidate,
}: {
  group: PendingTrackGroup;
  onInvalidate: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [loadingTrackId, setLoadingTrackId] = useState<string | null>(null);

  const unskipMutation = useMutation({
    mutationFn: (trackId: string) => pendingTracksApi.unskip(trackId),
    onSuccess: onInvalidate,
  });
  const groupUnskipMutation = useMutation({
    mutationFn: () => pendingTracksApi.groupUnskip(group.folder_path),
    onSuccess: onInvalidate,
  });

  return (
    <div className="rounded-lg border border-zinc-700 bg-zinc-900/50 overflow-hidden">
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-zinc-800/50"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? (
          <ChevronDown className="w-4 h-4 text-zinc-400 flex-shrink-0" />
        ) : (
          <ChevronRight className="w-4 h-4 text-zinc-400 flex-shrink-0" />
        )}
        <div className="flex-1 min-w-0">
          <span className="text-sm font-medium text-white truncate">{group.folder_name}</span>
          <span className="text-xs text-zinc-500 ml-2">{group.track_count} track{group.track_count !== 1 ? 's' : ''}</span>
        </div>
        <div className="flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <button
            onClick={() => groupUnskipMutation.mutate()}
            disabled={groupUnskipMutation.isPending}
            className="px-2 py-1 rounded text-xs bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50"
          >
            {groupUnskipMutation.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Un-skip All'}
          </button>
        </div>
      </div>
      {expanded && (
        <div className="border-t border-zinc-800 py-1">
          {group.tracks.map((track) => (
            <div key={track.id} className="flex items-center gap-3 px-3 py-2 hover:bg-zinc-800/50 rounded-lg group">
              <Music className="w-4 h-4 text-zinc-500 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="text-sm text-white truncate">{track.title || '(untitled)'}</div>
                <div className="flex items-center gap-2 text-xs text-zinc-500">
                  <span>{track.artist || 'Unknown'}</span>
                  {track.album && (
                    <>
                      <span className="text-zinc-600">&middot;</span>
                      <span>{track.album}</span>
                    </>
                  )}
                  <span className="text-zinc-600">&middot;</span>
                  <span>{track.format?.toUpperCase()}</span>
                  <span>{formatDuration(track.duration_seconds)}</span>
                </div>
              </div>
              <button
                onClick={() => {
                  setLoadingTrackId(track.id);
                  unskipMutation.mutate(track.id, { onSettled: () => setLoadingTrackId(null) });
                }}
                disabled={loadingTrackId === track.id}
                className="p-1.5 rounded bg-blue-600 hover:bg-blue-700 text-white text-xs disabled:opacity-50 opacity-0 group-hover:opacity-100 transition-opacity"
                title="Un-skip (return to review)"
              >
                <RotateCcw className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PendingReviewBrowser(_props: BrowserProps) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<'pending' | 'skipped'>('pending');
  const [filterTab, setFilterTab] = useState<FilterTab>('all');
  const [queueAnalysis, setQueueAnalysis] = useState(true);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.pendingTracks.all });
    queryClient.invalidateQueries({ queryKey: queryKeys.tracks.all });
  };

  const { data: stats } = useQuery({
    queryKey: queryKeys.pendingTracks.stats,
    queryFn: pendingTracksApi.getStats,
    refetchInterval: 30000,
  });

  // Lightweight count of skipped tracks for the toggle badge.
  const { data: skippedCountData } = useQuery({
    queryKey: queryKeys.pendingTracks.groups({ count: 'skipped' }),
    queryFn: () => pendingTracksApi.listGroups({ status: 'skipped', limit: 1 }),
    refetchInterval: 30000,
  });
  const skippedCount = skippedCountData?.total_tracks ?? 0;

  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.pendingTracks.groups({ mode, filter: filterTab }),
    queryFn: () =>
      pendingTracksApi.listGroups({ status: mode === 'skipped' ? 'skipped' : 'pending_review' }),
  });

  const bulkApproveMutation = useMutation({
    mutationFn: () => pendingTracksApi.bulkApproveAll({ queue_analysis: queueAnalysis }),
    onSuccess: invalidate,
  });

  const bulkSkipMutation = useMutation({
    mutationFn: () => pendingTracksApi.bulkSkipAll(),
    onSuccess: invalidate,
  });

  const bulkUnskipMutation = useMutation({
    mutationFn: () => pendingTracksApi.bulkUnskipAll(),
    onSuccess: invalidate,
  });

  // Filter groups based on tab (pending mode only)
  let filteredGroups = data?.groups ?? [];
  if (mode === 'pending') {
    if (filterTab === 'duplicates') {
      filteredGroups = filteredGroups.filter((g) => g.duplicate_count > 0);
    } else if (filterTab === 'clean') {
      filteredGroups = filteredGroups.filter((g) => g.duplicate_count === 0);
    }
  }

  const totalTracks = stats?.total_tracks ?? 0;
  const isBulkLoading =
    bulkApproveMutation.isPending || bulkSkipMutation.isPending || bulkUnskipMutation.isPending;

  return (
    <div className="p-4 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <Inbox className="w-6 h-6 text-blue-400" />
        <div className="flex-1">
          <h2 className="text-xl font-semibold text-white">Pending Review</h2>
          <p className="text-sm text-zinc-400">
            {mode === 'pending'
              ? (totalTracks > 0
                  ? `${totalTracks} track${totalTracks !== 1 ? 's' : ''} in ${stats?.total_groups ?? 0} group${(stats?.total_groups ?? 0) !== 1 ? 's' : ''} awaiting review`
                  : 'No tracks awaiting review')
              : (skippedCount > 0
                  ? `${skippedCount} skipped track${skippedCount !== 1 ? 's' : ''} — un-skip to return them to review`
                  : 'No skipped tracks')}
          </p>
        </div>
        {mode === 'pending' && totalTracks > 0 && (
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1.5 text-sm text-zinc-400 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={queueAnalysis}
                onChange={(e) => setQueueAnalysis(e.target.checked)}
                className="rounded border-zinc-600 bg-zinc-800 text-blue-500 focus:ring-blue-500 focus:ring-offset-0"
              />
              Queue analysis
            </label>
            <button
              onClick={() => bulkSkipMutation.mutate()}
              disabled={isBulkLoading}
              className="px-3 py-1.5 rounded text-sm bg-zinc-600 hover:bg-zinc-500 text-white disabled:opacity-50 flex items-center gap-1.5"
            >
              {bulkSkipMutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <>
                  <X className="w-4 h-4" />
                  Skip All
                </>
              )}
            </button>
            <button
              onClick={() => bulkApproveMutation.mutate()}
              disabled={isBulkLoading}
              className="px-3 py-1.5 rounded text-sm bg-green-600 hover:bg-green-700 text-white disabled:opacity-50"
            >
              {bulkApproveMutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                'Import All'
              )}
            </button>
          </div>
        )}
        {mode === 'skipped' && skippedCount > 0 && (
          <button
            onClick={() => bulkUnskipMutation.mutate()}
            disabled={isBulkLoading}
            className="px-3 py-1.5 rounded text-sm bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 flex items-center gap-1.5"
          >
            {bulkUnskipMutation.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <>
                <RotateCcw className="w-4 h-4" />
                Un-skip All
              </>
            )}
          </button>
        )}
      </div>

      {/* Mode toggle */}
      <div className="flex gap-2 mb-4">
        <button
          onClick={() => setMode('pending')}
          className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
            mode === 'pending' ? 'bg-blue-600 text-white' : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700'
          }`}
        >
          Pending ({totalTracks})
        </button>
        <button
          onClick={() => setMode('skipped')}
          className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
            mode === 'skipped' ? 'bg-blue-600 text-white' : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700'
          }`}
        >
          Skipped ({skippedCount})
        </button>
      </div>

      {/* Empty states */}
      {mode === 'pending' && totalTracks === 0 && !isLoading && (
        <div className="text-center py-12">
          <CheckCircle className="w-12 h-12 text-green-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-white mb-2">All Clear</h3>
          <p className="text-zinc-400 max-w-md mx-auto">
            New tracks discovered during library sync will appear here for review.
          </p>
        </div>
      )}
      {mode === 'skipped' && skippedCount === 0 && !isLoading && (
        <div className="text-center py-12">
          <CheckCircle className="w-12 h-12 text-zinc-500 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-white mb-2">No skipped tracks</h3>
          <p className="text-zinc-400 max-w-md mx-auto">
            Tracks you skip during review appear here so you can un-skip them later.
          </p>
        </div>
      )}

      {mode === 'pending' && totalTracks > 0 && (
        <>
          {/* Filter tabs */}
          <div className="flex flex-wrap gap-2 mb-4">
            <button
              onClick={() => setFilterTab('all')}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                filterTab === 'all'
                  ? 'bg-blue-600 text-white'
                  : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700'
              }`}
            >
              All ({data?.total_groups ?? 0})
            </button>
            <button
              onClick={() => setFilterTab('duplicates')}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                filterTab === 'duplicates'
                  ? 'bg-amber-600 text-white'
                  : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700'
              }`}
            >
              Has Duplicates ({stats?.with_duplicates ?? 0})
            </button>
            <button
              onClick={() => setFilterTab('clean')}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                filterTab === 'clean'
                  ? 'bg-green-600 text-white'
                  : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700'
              }`}
            >
              Clean
            </button>
          </div>

          {/* Loading */}
          {isLoading && (
            <div className="flex items-center gap-2 py-12 justify-center">
              <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
              <span className="text-zinc-400">Loading...</span>
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="flex items-center gap-2 p-4 bg-red-900/30 rounded-lg border border-red-800">
              <AlertCircle className="w-5 h-5 text-red-400" />
              <span className="text-red-400">Failed to load pending tracks</span>
            </div>
          )}

          {/* Groups */}
          {!isLoading && !error && (
            <div className="space-y-3">
              {filteredGroups.length === 0 ? (
                <p className="text-zinc-500 text-center py-8">
                  No groups match the current filter
                </p>
              ) : (
                filteredGroups.map((group) => (
                  <GroupCard key={group.folder_path} group={group} queueAnalysis={queueAnalysis} onInvalidate={invalidate} />
                ))
              )}
            </div>
          )}
        </>
      )}

      {/* Skipped mode body */}
      {mode === 'skipped' && skippedCount > 0 && (
        <>
          {isLoading && (
            <div className="flex items-center gap-2 py-12 justify-center">
              <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
              <span className="text-zinc-400">Loading...</span>
            </div>
          )}
          {error && (
            <div className="flex items-center gap-2 p-4 bg-red-900/30 rounded-lg border border-red-800">
              <AlertCircle className="w-5 h-5 text-red-400" />
              <span className="text-red-400">Failed to load skipped tracks</span>
            </div>
          )}
          {!isLoading && !error && (
            <div className="space-y-3">
              {filteredGroups.length === 0 ? (
                <p className="text-zinc-500 text-center py-8">No skipped tracks</p>
              ) : (
                filteredGroups.map((group) => (
                  <SkippedGroupCard key={group.folder_path} group={group} onInvalidate={invalidate} />
                ))
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default PendingReviewBrowser;
