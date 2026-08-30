import { useState, useEffect, useCallback, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  X,
  Save,
  Loader2,
  Music,
  FileText,
  ArrowUpDown,
  Image,
  Mic2,
  BarChart3,
  AlertCircle,
  CheckCircle,
  Fingerprint,
} from 'lucide-react';
import { tracksApi, bulkTracksApi, type TrackMetadataUpdate } from '../../api';
import { queryKeys } from '../../api/queryKeys';
import { useSelectionStore } from '../../stores/selectionStore';
import { BasicMetadataTab } from './tabs/BasicMetadataTab';
import { ExtendedMetadataTab } from './tabs/ExtendedMetadataTab';
import { SortFieldsTab } from './tabs/SortFieldsTab';
import { LyricsTab } from './tabs/LyricsTab';
import { AnalysisTab } from './tabs/AnalysisTab';
import { ArtworkTab } from './tabs/ArtworkTab';
import { BulkAutoPopulatePanel } from './BulkAutoPopulatePanel';

import { createLogger } from '../../utils/logger';

const log = createLogger('TrackEditModal');

type TabId = 'basic' | 'extended' | 'sort' | 'artwork' | 'lyrics' | 'analysis' | 'auto-populate';

interface Tab {
  id: TabId;
  label: string;
  icon: React.ReactNode;
}

const TABS: Tab[] = [
  { id: 'basic', label: 'Basic', icon: <Music className="w-4 h-4" /> },
  { id: 'extended', label: 'Extended', icon: <FileText className="w-4 h-4" /> },
  { id: 'sort', label: 'Sort', icon: <ArrowUpDown className="w-4 h-4" /> },
  { id: 'artwork', label: 'Artwork', icon: <Image className="w-4 h-4" /> },
  { id: 'lyrics', label: 'Lyrics', icon: <Mic2 className="w-4 h-4" /> },
  { id: 'analysis', label: 'Analysis', icon: <BarChart3 className="w-4 h-4" /> },
];

const BULK_TABS: Tab[] = [
  { id: 'auto-populate', label: 'Auto-populate', icon: <Fingerprint className="w-4 h-4" /> },
  { id: 'basic', label: 'Basic', icon: <Music className="w-4 h-4" /> },
  { id: 'extended', label: 'Extended', icon: <FileText className="w-4 h-4" /> },
  { id: 'sort', label: 'Sort', icon: <ArrowUpDown className="w-4 h-4" /> },
];

export function TrackEditModal() {
  const queryClient = useQueryClient();
  const { editingTrackId, setEditingTrackId, getSelectedIds } = useSelectionStore();
  const [formData, setFormData] = useState<Partial<TrackMetadataUpdate>>({});
  const [changedFields, setChangedFields] = useState<Set<string>>(new Set());
  const [isDirty, setIsDirty] = useState(false);

  // Get selected IDs for bulk editing
  const selectedIds = getSelectedIds();
  const isBulkEdit = selectedIds.length > 1;
  const trackId = editingTrackId || selectedIds[0];

  // Use different default tab for bulk edit
  const [activeTab, setActiveTab] = useState<TabId>(isBulkEdit ? 'auto-populate' : 'basic');

  // Get the appropriate tabs based on mode
  const currentTabs = isBulkEdit ? BULK_TABS : TABS;

  // Fetch single-track metadata (single edit mode)
  const { data: metadata, isLoading: isLoadingSingle, error: errorSingle } = useQuery({
    queryKey: queryKeys.trackMetadata.detail(trackId),
    queryFn: () => tracksApi.getMetadata(trackId!),
    enabled: !!trackId && !isBulkEdit,
  });

  // Fetch common values across selected tracks (bulk edit mode)
  const { data: commonValues, isLoading: isLoadingCommon, error: errorCommon } = useQuery({
    queryKey: queryKeys.trackCommonValues.detail(selectedIds),
    queryFn: () => bulkTracksApi.getCommonValues(selectedIds),
    enabled: isBulkEdit && selectedIds.length > 1,
  });

  const isLoading = isBulkEdit ? isLoadingCommon : isLoadingSingle;
  const error = isBulkEdit ? errorCommon : errorSingle;

  // Single-track update mutation
  const updateMutation = useMutation({
    mutationFn: async (update: TrackMetadataUpdate) => {
      return tracksApi.updateMetadata(trackId!, update);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.tracks.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.trackMetadata.all });
      handleClose();
    },
  });

  // Bulk update mutation — uses dedicated bulk endpoint
  const bulkUpdateMutation = useMutation({
    mutationFn: async ({ metadata }: { metadata: Partial<TrackMetadataUpdate> }) => {
      return bulkTracksApi.updateMetadata(selectedIds, metadata);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.tracks.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.trackMetadata.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.trackCommonValues.all });
      handleClose();
    },
  });

  const activeMutation = isBulkEdit ? bulkUpdateMutation : updateMutation;

  // Initialize form data from single-track metadata
  useEffect(() => {
    if (metadata && !isDirty && !isBulkEdit) {
      setFormData({
        title: metadata.title,
        artist: metadata.artist,
        album: metadata.album,
        album_artist: metadata.album_artist,
        track_number: metadata.track_number,
        disc_number: metadata.disc_number,
        year: metadata.year,
        genre: metadata.genre,
        composer: metadata.composer,
        conductor: metadata.conductor,
        lyricist: metadata.lyricist,
        grouping: metadata.grouping,
        comment: metadata.comment,
        sort_artist: metadata.sort_artist,
        sort_album: metadata.sort_album,
        sort_title: metadata.sort_title,
        lyrics: metadata.lyrics,
        user_overrides: metadata.user_overrides,
      });
    }
  }, [metadata, isDirty, isBulkEdit]);

  // Initialize form data from common values in bulk mode
  // null values = mixed across tracks, shown as empty with "(Mixed)" placeholder
  useEffect(() => {
    if (commonValues && !isDirty && isBulkEdit) {
      setFormData({
        title: commonValues.title,
        artist: commonValues.artist,
        album: commonValues.album,
        album_artist: commonValues.album_artist,
        track_number: commonValues.track_number,
        disc_number: commonValues.disc_number,
        year: commonValues.year,
        genre: commonValues.genre,
        composer: commonValues.composer,
        conductor: commonValues.conductor,
        lyricist: commonValues.lyricist,
        grouping: commonValues.grouping,
        comment: commonValues.comment,
        sort_artist: commonValues.sort_artist,
        sort_album: commonValues.sort_album,
        sort_title: commonValues.sort_title,
        lyrics: commonValues.lyrics,
      });
    }
  }, [commonValues, isDirty, isBulkEdit]);

  // Derive which fields are mixed (null in commonValues = different across tracks)
  const disabledFields = useMemo(() => {
    if (!isBulkEdit || !commonValues) return new Set<string>();
    const disabled = new Set<string>();
    const fields = ['title','artist','album','album_artist','track_number','disc_number',
      'year','genre','composer','conductor','lyricist','grouping','comment',
      'sort_artist','sort_album','sort_title','lyrics'] as const;
    for (const f of fields) {
      if (commonValues[f] === null) disabled.add(f);
    }
    return disabled;
  }, [isBulkEdit, commonValues]);

  const handleClose = () => {
    setEditingTrackId(null);
    setFormData({});
    setChangedFields(new Set());
    setIsDirty(false);
    setActiveTab('basic');
  };

  // Handle applying metadata from bulk auto-populate to a specific track
  const handleApplyToTrack = useCallback(
    async (targetTrackId: string, metadata: Partial<TrackMetadataUpdate>) => {
      try {
        await tracksApi.updateMetadata(targetTrackId, metadata);
        // Invalidate to refresh UI
        queryClient.invalidateQueries({ queryKey: queryKeys.tracks.all });
        queryClient.invalidateQueries({ queryKey: queryKeys.trackMetadata.detail(targetTrackId) });
      } catch (error) {
        log.error(`Failed to update track ${targetTrackId}:`, error);
      }
    },
    [queryClient]
  );

  const handleFieldChange = (field: keyof TrackMetadataUpdate, value: unknown) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
    setChangedFields((prev) => new Set(prev).add(field));
    setIsDirty(true);
  };

  const handleSave = () => {
    if (isBulkEdit) {
      // Only send fields the user actually changed
      const changedData: Partial<TrackMetadataUpdate> = {};
      for (const field of changedFields) {
        changedData[field as keyof TrackMetadataUpdate] = formData[field as keyof TrackMetadataUpdate] as never;
      }
      bulkUpdateMutation.mutate({ metadata: changedData });
    } else {
      const update: TrackMetadataUpdate = {
        ...formData,
      };
      updateMutation.mutate(update);
    }
  };

  // Don't render if no track is being edited
  if (!trackId) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-zinc-900 rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col border border-zinc-700">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 sm:px-6 sm:py-4 border-b border-zinc-700">
          <div className="flex items-center gap-3">
            <Music className="w-5 h-5 text-purple-400" />
            <h2 className="text-lg font-semibold text-white">
              {isBulkEdit ? `Edit ${selectedIds.length} Tracks` : 'Edit Track Metadata'}
            </h2>
          </div>
          <button
            onClick={handleClose}
            className="p-2 text-zinc-400 hover:text-white hover:bg-zinc-800 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 px-6 py-2 border-b border-zinc-800 overflow-x-auto">
          {currentTabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors whitespace-nowrap ${
                activeTab === tab.id
                  ? 'bg-purple-500/20 text-purple-400'
                  : 'text-zinc-400 hover:text-white hover:bg-zinc-800'
              }`}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-4 py-3 sm:px-6 sm:py-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-8 h-8 animate-spin text-purple-400" />
            </div>
          ) : error ? (
            <div className="flex flex-col items-center justify-center py-12 text-danger">
              <AlertCircle className="w-8 h-8 mb-2" />
              <p>Failed to load track metadata</p>
            </div>
          ) : (
            <>
              {activeTab === 'auto-populate' && isBulkEdit && (
                <BulkAutoPopulatePanel
                  trackIds={selectedIds}
                  onApplyToTrack={handleApplyToTrack}
                />
              )}
              {activeTab === 'basic' && (
                <BasicMetadataTab
                  formData={formData}
                  onChange={handleFieldChange}
                  isBulkEdit={isBulkEdit}
                  trackId={trackId}
                  disabledFields={disabledFields}
                />
              )}
              {activeTab === 'extended' && (
                <ExtendedMetadataTab
                  formData={formData}
                  onChange={handleFieldChange}
                  isBulkEdit={isBulkEdit}
                  disabledFields={disabledFields}
                />
              )}
              {activeTab === 'sort' && (
                <SortFieldsTab
                  formData={formData}
                  onChange={handleFieldChange}
                  isBulkEdit={isBulkEdit}
                  disabledFields={disabledFields}
                />
              )}
              {activeTab === 'artwork' && (
                <ArtworkTab
                  trackId={trackId}
                  artist={metadata?.artist}
                  album={metadata?.album}
                />
              )}
              {activeTab === 'lyrics' && (
                <LyricsTab
                  formData={formData}
                  onChange={handleFieldChange}
                />
              )}
              {activeTab === 'analysis' && (
                <AnalysisTab
                  formData={formData}
                  metadata={metadata}
                  onChange={handleFieldChange}
                />
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end px-4 py-3 sm:px-6 sm:py-4 border-t border-zinc-700">
          <div className="flex items-center gap-3">
            {activeMutation.isSuccess && (
              <span className="flex items-center gap-1 text-sm text-success">
                <CheckCircle className="w-4 h-4" />
                Saved
              </span>
            )}
            {activeMutation.isError && (
              <span className="flex items-center gap-1 text-sm text-danger">
                <AlertCircle className="w-4 h-4" />
                Error saving
              </span>
            )}

            <button
              onClick={handleClose}
              className="px-4 py-2 text-sm text-zinc-400 hover:text-white transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={!isDirty || activeMutation.isPending}
              className="flex items-center gap-2 px-4 py-2 bg-purple-500 hover:bg-purple-600 disabled:bg-zinc-700 disabled:text-zinc-500 text-white rounded-lg text-sm font-medium transition-colors"
            >
              {activeMutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Save className="w-4 h-4" />
              )}
              Save Changes
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
