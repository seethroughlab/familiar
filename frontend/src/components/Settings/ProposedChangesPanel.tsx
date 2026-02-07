import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  CheckCircle,
  Loader2,
  Play,
  Eye,
  Undo2,
  Trash2,
  ClipboardList,
  X,
  ChevronDown,
  AlertCircle,
} from 'lucide-react';
import {
  proposedChangesApi,
  type ProposedChange,
  type ChangeStatus,
  type ChangeScope,
  type ChangePreview,
} from '../../api/client';

const STATUS_LABELS: Record<ChangeStatus, string> = {
  pending: 'Pending',
  rejected: 'Rejected',
  applied: 'Applied',
};

const SOURCE_LABELS: Record<string, string> = {
  user_request: 'User Request',
  llm_suggestion: 'AI Suggestion',
  musicbrainz: 'MusicBrainz',
  spotify: 'Spotify',
  auto_enrichment: 'Auto Enrichment',
};

const SCOPE_LABELS: Record<ChangeScope, string> = {
  db_only: 'Database Only',
  db_and_id3: 'DB + ID3 Tags',
  db_id3_files: 'DB + ID3 + Files',
};

const SCOPE_LABELS_SHORT: Record<ChangeScope, string> = {
  db_only: 'DB',
  db_and_id3: 'DB+ID3',
  db_id3_files: 'DB+ID3+Files',
};

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '(empty)';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '';
  const date = new Date(dateStr);
  return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

interface PreviewModalProps {
  preview: ChangePreview;
  onClose: () => void;
}

function PreviewModal({ preview, onClose }: PreviewModalProps) {
  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-zinc-800 rounded-lg p-4 max-w-lg w-full mx-4 max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-white">Change Preview</h3>
          <button onClick={onClose} className="p-1 hover:bg-zinc-700 rounded">
            <X className="w-5 h-5 text-zinc-400" />
          </button>
        </div>

        <div className="space-y-3">
          <div>
            <span className="text-xs text-zinc-500 uppercase">Target</span>
            <p className="text-white">{preview.target_description}</p>
          </div>

          {preview.field && (
            <div>
              <span className="text-xs text-zinc-500 uppercase">Field</span>
              <p className="text-white font-mono">{preview.field}</p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <span className="text-xs text-zinc-500 uppercase">Before</span>
              <p className="text-red-400 font-mono text-sm">{formatValue(preview.old_value)}</p>
            </div>
            <div>
              <span className="text-xs text-zinc-500 uppercase">After</span>
              <p className="text-green-400 font-mono text-sm">{formatValue(preview.new_value)}</p>
            </div>
          </div>

          <div>
            <span className="text-xs text-zinc-500 uppercase">Tracks Affected</span>
            <p className="text-white">{preview.tracks_affected}</p>
          </div>

          {Array.isArray(preview.files_affected) && preview.files_affected.length > 0 && (
            <div>
              <span className="text-xs text-zinc-500 uppercase">Files</span>
              <div className="max-h-32 overflow-y-auto bg-zinc-900/50 rounded p-2 mt-1">
                {preview.files_affected.map((path, i) => (
                  <p key={i} className="text-xs text-zinc-400 font-mono truncate">
                    {path}
                  </p>
                ))}
              </div>
            </div>
          )}

          <div>
            <span className="text-xs text-zinc-500 uppercase">Scope</span>
            <p className="text-white">{SCOPE_LABELS[preview.scope]}</p>
          </div>
        </div>
      </div>
    </div>
  );
}

interface ChangeCardProps {
  change: ProposedChange;
  onPreview: () => void;
  onReject: () => void;
  onApply: (scope: ChangeScope) => void;
  onUndo: () => void;
  onDelete: () => void;
  isLoading: boolean;
}

function ChangeCard({
  change,
  onPreview,
  onReject,
  onApply,
  onUndo,
  onDelete,
  isLoading,
}: ChangeCardProps) {
  const [selectedScope, setSelectedScope] = useState<ChangeScope>(change.scope);
  const [showScopeDropdown, setShowScopeDropdown] = useState(false);

  const isPending = change.status === 'pending';
  const isApplied = change.status === 'applied';
  const isRejected = change.status === 'rejected';

  return (
    <div
      className={`rounded-lg border p-3 space-y-2 ${
        isPending
          ? 'bg-zinc-900/50 border-zinc-700'
          : isApplied
            ? 'bg-green-900/20 border-green-800/50'
            : 'bg-zinc-900/30 border-zinc-700/50'
      }`}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <ClipboardList className="w-4 h-4 text-purple-400 flex-shrink-0" />
            <span className="text-white font-medium truncate">
              {change.field ? `Set ${change.field}` : change.change_type}
            </span>
            {change.target_type && (
              <span className="text-xs px-1.5 py-0.5 bg-zinc-700 rounded text-zinc-300">
                {change.target_type}
              </span>
            )}
          </div>
          {change.target_description && (
            <p className="text-xs text-zinc-400 truncate">{change.target_description}</p>
          )}
          {change.reason && <p className="text-sm text-zinc-400 mt-1">{change.reason}</p>}
        </div>

        <div className="flex items-center gap-1 flex-shrink-0">
          <span
            className={`text-xs px-2 py-0.5 rounded ${
              isPending
                ? 'bg-yellow-900/50 text-yellow-400'
                : isApplied
                  ? 'bg-green-900/50 text-green-400'
                  : 'bg-zinc-700 text-zinc-400'
            }`}
          >
            {STATUS_LABELS[change.status]}
          </span>
        </div>
      </div>

      {/* Change details */}
      <div className="grid grid-cols-2 gap-2 text-sm">
        <div>
          <span className="text-xs text-zinc-500">Before</span>
          <p className="text-red-400 font-mono text-xs truncate">{formatValue(change.old_value)}</p>
        </div>
        <div>
          <span className="text-xs text-zinc-500">After</span>
          <p className="text-green-400 font-mono text-xs truncate">{formatValue(change.new_value)}</p>
        </div>
      </div>

      {/* Metadata */}
      <div className="flex flex-wrap items-center gap-3 text-xs text-zinc-500">
        <span>{SOURCE_LABELS[change.source] || change.source}</span>
        <span>{Math.round(change.confidence * 100)}% confidence</span>
        <span>{Array.isArray(change.target_ids) ? change.target_ids.length : 0} track(s)</span>
        <span>{formatDate(change.created_at)}</span>
      </div>

      {/* Actions */}
      <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-zinc-700/50">
        {/* Scope selector (for pending) */}
        {isPending && (
          <div className="relative">
            <button
              onClick={() => setShowScopeDropdown(!showScopeDropdown)}
              className="flex items-center gap-1 px-2 py-1 bg-zinc-700 hover:bg-zinc-600 rounded text-xs transition-colors"
            >
              <span className="sm:hidden">{SCOPE_LABELS_SHORT[selectedScope]}</span>
              <span className="hidden sm:inline">{SCOPE_LABELS[selectedScope]}</span>
              <ChevronDown className="w-3 h-3" />
            </button>
            {showScopeDropdown && (
              <div className="absolute bottom-full left-0 mb-1 bg-zinc-700 rounded shadow-lg border border-zinc-600 z-10">
                {(Object.keys(SCOPE_LABELS) as ChangeScope[]).map((scope) => (
                  <button
                    key={scope}
                    onClick={() => {
                      setSelectedScope(scope);
                      setShowScopeDropdown(false);
                    }}
                    className={`block w-full text-left px-3 py-1.5 text-xs hover:bg-zinc-600 whitespace-nowrap ${
                      selectedScope === scope ? 'text-purple-400' : 'text-zinc-200'
                    }`}
                  >
                    {SCOPE_LABELS[scope]}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="flex-1" />

        {/* Preview button */}
        <button
          onClick={onPreview}
          disabled={isLoading}
          className="flex items-center gap-1 px-2 py-1 bg-zinc-700 hover:bg-zinc-600 rounded text-xs transition-colors disabled:opacity-50"
        >
          <Eye className="w-3 h-3" />
          <span className="hidden sm:inline">Preview</span>
        </button>

        {/* Status-specific actions */}
        {isPending && (
          <>
            <button
              onClick={() => onApply(selectedScope)}
              disabled={isLoading}
              className="flex items-center gap-1 px-2 py-1 bg-green-600 hover:bg-green-700 rounded text-xs transition-colors disabled:opacity-50"
            >
              {isLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />}
              <span className="hidden sm:inline">Apply</span>
            </button>
            <button
              onClick={onReject}
              disabled={isLoading}
              className="flex items-center gap-1 px-2 py-1 bg-zinc-600 hover:bg-zinc-500 rounded text-xs transition-colors disabled:opacity-50"
            >
              <X className="w-3 h-3" />
              <span className="hidden sm:inline">Reject</span>
            </button>
          </>
        )}

        {isApplied && (
          <button
            onClick={onUndo}
            disabled={isLoading}
            className="flex items-center gap-1 px-2 py-1 bg-amber-600 hover:bg-amber-700 rounded text-xs transition-colors disabled:opacity-50"
          >
            {isLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Undo2 className="w-3 h-3" />}
            <span className="hidden sm:inline">Undo</span>
          </button>
        )}

        {isRejected && (
          <button
            onClick={onDelete}
            disabled={isLoading}
            className="flex items-center gap-1 px-2 py-1 bg-red-600 hover:bg-red-700 rounded text-xs transition-colors disabled:opacity-50"
          >
            {isLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
            <span className="hidden sm:inline">Delete</span>
          </button>
        )}
      </div>
    </div>
  );
}

export function ProposedChangesPanel() {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<ChangeStatus | null>(null);
  const [previewData, setPreviewData] = useState<ChangePreview | null>(null);
  const [loadingChangeId, setLoadingChangeId] = useState<string | null>(null);

  // Fetch stats
  const { data: stats } = useQuery({
    queryKey: ['proposed-changes-stats'],
    queryFn: proposedChangesApi.getStats,
    refetchInterval: 30000,
  });

  // Fetch changes
  const {
    data: changes,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['proposed-changes', statusFilter],
    queryFn: () => proposedChangesApi.list({ status: statusFilter || undefined, limit: 100 }),
  });

  // Mutations
  const rejectMutation = useMutation({
    mutationFn: proposedChangesApi.reject,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['proposed-changes'] });
      queryClient.invalidateQueries({ queryKey: ['proposed-changes-stats'] });
    },
  });

  const applyMutation = useMutation({
    mutationFn: ({ id, scope }: { id: string; scope: ChangeScope }) => proposedChangesApi.apply(id, scope),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['proposed-changes'] });
      queryClient.invalidateQueries({ queryKey: ['proposed-changes-stats'] });
    },
  });

  const undoMutation = useMutation({
    mutationFn: proposedChangesApi.undo,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['proposed-changes'] });
      queryClient.invalidateQueries({ queryKey: ['proposed-changes-stats'] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: proposedChangesApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['proposed-changes'] });
      queryClient.invalidateQueries({ queryKey: ['proposed-changes-stats'] });
    },
  });

  const handlePreview = async (changeId: string) => {
    setLoadingChangeId(changeId);
    try {
      const preview = await proposedChangesApi.preview(changeId);
      setPreviewData(preview);
    } catch (error) {
      console.error('Failed to fetch preview:', error);
    } finally {
      setLoadingChangeId(null);
    }
  };

  const handleReject = (changeId: string) => {
    setLoadingChangeId(changeId);
    rejectMutation.mutate(changeId, {
      onSettled: () => setLoadingChangeId(null),
    });
  };

  const handleApply = (changeId: string, scope: ChangeScope) => {
    setLoadingChangeId(changeId);
    applyMutation.mutate(
      { id: changeId, scope },
      {
        onSettled: () => setLoadingChangeId(null),
      }
    );
  };

  const handleUndo = (changeId: string) => {
    setLoadingChangeId(changeId);
    undoMutation.mutate(changeId, {
      onSettled: () => setLoadingChangeId(null),
    });
  };

  const handleDelete = (changeId: string) => {
    if (!window.confirm('Are you sure you want to delete this change?')) return;
    setLoadingChangeId(changeId);
    deleteMutation.mutate(changeId, {
      onSettled: () => setLoadingChangeId(null),
    });
  };

  const totalChanges = stats ? stats.pending + stats.rejected + stats.applied : 0;

  if (totalChanges === 0 && !isLoading) {
    return (
      <div className="bg-zinc-800/50 dark:bg-zinc-800/50 light:bg-zinc-100 rounded-lg p-4">
        <div className="flex items-center gap-2 mb-2">
          <CheckCircle className="w-5 h-5 text-green-400" />
          <h4 className="font-medium text-white dark:text-white light:text-zinc-900">No Proposed Changes</h4>
        </div>
        <p className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
          When the AI suggests metadata corrections or you request changes, they'll appear here for review.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-zinc-800/50 dark:bg-zinc-800/50 light:bg-zinc-100 rounded-lg p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <ClipboardList className="w-5 h-5 text-purple-400" />
        <div>
          <h4 className="font-medium text-white dark:text-white light:text-zinc-900">Proposed Changes</h4>
          <p className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
            Review and apply metadata corrections
          </p>
        </div>
      </div>

      {/* Status tabs */}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => setStatusFilter(null)}
          className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${
            statusFilter === null
              ? 'bg-purple-600 text-white'
              : 'bg-zinc-700 text-zinc-300 hover:bg-zinc-600'
          }`}
        >
          All ({totalChanges})
        </button>
        <button
          onClick={() => setStatusFilter('pending')}
          className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${
            statusFilter === 'pending'
              ? 'bg-yellow-600 text-white'
              : 'bg-zinc-700 text-zinc-300 hover:bg-zinc-600'
          }`}
        >
          Pending ({stats?.pending || 0})
        </button>
        <button
          onClick={() => setStatusFilter('applied')}
          className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${
            statusFilter === 'applied'
              ? 'bg-green-600 text-white'
              : 'bg-zinc-700 text-zinc-300 hover:bg-zinc-600'
          }`}
        >
          Applied ({stats?.applied || 0})
        </button>
        <button
          onClick={() => setStatusFilter('rejected')}
          className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${
            statusFilter === 'rejected'
              ? 'bg-zinc-500 text-white'
              : 'bg-zinc-700 text-zinc-300 hover:bg-zinc-600'
          }`}
        >
          Rejected ({stats?.rejected || 0})
        </button>
      </div>

      {/* Loading state */}
      {isLoading && (
        <div className="flex items-center gap-2 py-8 justify-center">
          <Loader2 className="w-5 h-5 animate-spin text-zinc-400" />
          <span className="text-sm text-zinc-400">Loading changes...</span>
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="flex items-center gap-2 p-3 bg-red-900/30 rounded-lg border border-red-800">
          <AlertCircle className="w-4 h-4 text-red-400" />
          <span className="text-sm text-red-400">Failed to load changes</span>
        </div>
      )}

      {/* Changes list */}
      {!isLoading && !error && Array.isArray(changes) && (
        <div className="space-y-3 max-h-[500px] overflow-y-auto">
          {changes.length === 0 ? (
            <p className="text-sm text-zinc-500 text-center py-4">
              No {statusFilter ? STATUS_LABELS[statusFilter].toLowerCase() : ''} changes
            </p>
          ) : (
            changes.map((change) => (
              <ChangeCard
                key={change.id}
                change={change}
                onPreview={() => handlePreview(change.id)}
                onReject={() => handleReject(change.id)}
                onApply={(scope) => handleApply(change.id, scope)}
                onUndo={() => handleUndo(change.id)}
                onDelete={() => handleDelete(change.id)}
                isLoading={loadingChangeId === change.id}
              />
            ))
          )}
        </div>
      )}

      {/* Info text */}
      <p className="text-xs text-zinc-500 dark:text-zinc-500 light:text-zinc-500">
        Changes can be applied at different scopes: database only (fast, reversible), with ID3 tags (writes to files),
        or with file organization (moves files to match metadata).
      </p>

      {/* Preview modal */}
      {previewData && <PreviewModal preview={previewData} onClose={() => setPreviewData(null)} />}
    </div>
  );
}
