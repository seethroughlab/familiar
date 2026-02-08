import { useState, useEffect, useCallback } from 'react';
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
import { tracksApi, type TrackMetadataUpdate } from '../../api/client';
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
  const [isDirty, setIsDirty] = useState(false);
  const [writeToFile, setWriteToFile] = useState(true);

  // Get selected IDs for bulk editing
  const selectedIds = getSelectedIds();
  const isBulkEdit = selectedIds.length > 1;
  const trackId = editingTrackId || selectedIds[0];

  // Use different default tab for bulk edit
  const [activeTab, setActiveTab] = useState<TabId>(isBulkEdit ? 'auto-populate' : 'basic');

  // Get the appropriate tabs based on mode
  const currentTabs = isBulkEdit ? BULK_TABS : TABS;

  // Fetch track metadata
  const { data: metadata, isLoading, error } = useQuery({
    queryKey: ['track-metadata', trackId],
    queryFn: () => tracksApi.getMetadata(trackId!),
    enabled: !!trackId,
  });

  // Update mutation
  const updateMutation = useMutation({
    mutationFn: async (update: TrackMetadataUpdate) => {
      if (isBulkEdit) {
        // For bulk edit, update all selected tracks
        const results = await Promise.all(
          selectedIds.map((id) => tracksApi.updateMetadata(id, update))
        );
        return results[0]; // Return first result for status
      }
      return tracksApi.updateMetadata(trackId!, update);
    },
    onSuccess: () => {
      // Invalidate track queries to refresh lists
      queryClient.invalidateQueries({ queryKey: ['tracks'] });
      queryClient.invalidateQueries({ queryKey: ['track-metadata'] });
      // Close modal
      handleClose();
    },
  });

  // Initialize form data when metadata loads
  useEffect(() => {
    if (metadata && !isDirty) {
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
  }, [metadata, isDirty]);

  const handleClose = () => {
    setEditingTrackId(null);
    setFormData({});
    setIsDirty(false);
    setActiveTab('basic');
  };

  // Handle applying metadata from bulk auto-populate to a specific track
  const handleApplyToTrack = useCallback(
    async (targetTrackId: string, metadata: Partial<TrackMetadataUpdate>) => {
      try {
        await tracksApi.updateMetadata(targetTrackId, {
          ...metadata,
          write_to_file: writeToFile,
        });
        // Invalidate to refresh UI
        queryClient.invalidateQueries({ queryKey: ['tracks'] });
        queryClient.invalidateQueries({ queryKey: ['track-metadata', targetTrackId] });
      } catch (error) {
        log.error(`Failed to update track ${targetTrackId}:`, error);
      }
    },
    [writeToFile, queryClient]
  );

  const handleFieldChange = (field: keyof TrackMetadataUpdate, value: unknown) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
    setIsDirty(true);
  };

  const handleSave = () => {
    // Only include changed fields
    const update: TrackMetadataUpdate = {
      ...formData,
      write_to_file: writeToFile,
    };
    updateMutation.mutate(update);
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
            <div className="flex flex-col items-center justify-center py-12 text-red-400">
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
                />
              )}
              {activeTab === 'extended' && (
                <ExtendedMetadataTab
                  formData={formData}
                  onChange={handleFieldChange}
                  isBulkEdit={isBulkEdit}
                />
              )}
              {activeTab === 'sort' && (
                <SortFieldsTab
                  formData={formData}
                  onChange={handleFieldChange}
                  isBulkEdit={isBulkEdit}
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
        <div className="flex items-center justify-between px-4 py-3 sm:px-6 sm:py-4 border-t border-zinc-700">
          <label className="flex items-center gap-2 text-sm text-zinc-400">
            <input
              type="checkbox"
              checked={writeToFile}
              onChange={(e) => setWriteToFile(e.target.checked)}
              className="w-4 h-4 rounded border-zinc-600 bg-zinc-800 text-purple-500 focus:ring-purple-500 focus:ring-offset-0"
            />
            Write changes to audio file
          </label>

          <div className="flex items-center gap-3">
            {updateMutation.isSuccess && (
              <span className="flex items-center gap-1 text-sm text-green-400">
                <CheckCircle className="w-4 h-4" />
                Saved
              </span>
            )}
            {updateMutation.isError && (
              <span className="flex items-center gap-1 text-sm text-red-400">
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
              disabled={!isDirty || updateMutation.isPending}
              className="flex items-center gap-2 px-4 py-2 bg-purple-500 hover:bg-purple-600 disabled:bg-zinc-700 disabled:text-zinc-500 text-white rounded-lg text-sm font-medium transition-colors"
            >
              {updateMutation.isPending ? (
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
