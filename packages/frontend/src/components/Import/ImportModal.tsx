import { useState, useCallback, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  X,
  Upload,
  Loader2,
  Music,
  FileArchive,
  Check,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  RotateCcw,
  ArrowUp,
  ArrowDown,
  Minus,
  RefreshCw,
} from 'lucide-react';
import { getApiUrl } from '../../api/base';

// Quality info from backend
interface QualityInfo {
  format_tier: number;
  format_tier_name: string;
  bitrate: number | null;
  sample_rate: number | null;
  bit_depth: number | null;
  is_lossless: boolean;
  bitrate_mode: string | null;
}

// Types matching backend
interface TrackPreview {
  filename: string;
  relative_path: string;
  detected_artist: string | null;
  detected_album: string | null;
  detected_title: string | null;
  detected_track_num: number | null;
  detected_year: number | null;
  format: string;
  duration_seconds: number | null;
  file_size_bytes: number;
  sample_rate: number | null;
  bit_depth: number | null;
  bitrate: number | null;
  bitrate_mode: string | null;
  // Duplicate detection
  duplicate_of: string | null;
  duplicate_info: string | null;
  duplicate_match_type: 'exact' | 'normalized' | 'artist_title' | null;
  // Quality comparison (for duplicates)
  trump_status: 'trumps' | 'trumped_by' | 'equal' | null;
  trump_reason: string | null;
  incoming_quality: QualityInfo | null;
  existing_quality: QualityInfo | null;
}

interface PreviewResponse {
  session_id: string;
  tracks: TrackPreview[];
  total_size_bytes: number;
  estimated_sizes: {
    original: number;
    flac: number;
    mp3_320: number;
  };
  has_convertible_formats: boolean;
}

interface EditableTrack extends TrackPreview {
  artist: string;
  album: string;
  title: string;
  track_num: number | null;
  year: number | null;
  // Duplicate detection (inherited but making explicit)
  duplicate_of: string | null;
  duplicate_info: string | null;
  // Track which fields have been manually edited
  editedFields: Set<'artist' | 'album' | 'title' | 'track_num' | 'year'>;
  // Quality-based replacement action
  action: 'import' | 'replace' | 'skip';
}

interface ImportModalProps {
  files: File[];
  onClose: () => void;
  onImportComplete?: () => void;
}

type UploadState = 'uploading' | 'preview' | 'importing' | 'complete' | 'error';
type FormatOption = 'original' | 'flac' | 'mp3';
type OrganizationOption = 'organized' | 'imports';

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function formatDuration(seconds: number | null): string {
  if (!seconds) return '--:--';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function formatQuality(quality: QualityInfo | null): string {
  if (!quality) return 'Unknown';

  if (quality.is_lossless) {
    const parts: string[] = ['FLAC'];
    if (quality.bit_depth) {
      parts.push(`${quality.bit_depth}-bit`);
    }
    if (quality.sample_rate) {
      const srKhz = quality.sample_rate / 1000;
      parts.push(`${srKhz === Math.floor(srKhz) ? srKhz : srKhz.toFixed(1)}kHz`);
    }
    return parts.join(' ');
  } else {
    const parts: string[] = [];
    if (quality.bitrate) {
      parts.push(`${quality.bitrate}kbps`);
    }
    if (quality.bitrate_mode) {
      parts.push(quality.bitrate_mode);
    }
    return parts.length > 0 ? parts.join(' ') : 'Lossy';
  }
}

export function ImportModal({ files, onClose, onImportComplete }: ImportModalProps) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<UploadState>('uploading');
  const [uploadProgress, setUploadProgress] = useState(0);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [tracks, setTracks] = useState<EditableTrack[]>([]);
  const [estimatedSizes, setEstimatedSizes] = useState<PreviewResponse['estimated_sizes'] | null>(null);
  const [hasConvertible, setHasConvertible] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Import options
  const [format, setFormat] = useState<FormatOption>('original');
  const [mp3Quality, setMp3Quality] = useState(320);
  const [organization, setOrganization] = useState<OrganizationOption>('organized');
  const [queueAnalysis, setQueueAnalysis] = useState(true);

  // UI state
  const [expandedTracks, setExpandedTracks] = useState(false);
  // Progress tracking - value is set but not displayed in UI yet
  const [, setImportProgress] = useState(0);
  const [importedCount, setImportedCount] = useState(0);
  const [replacedCount, setReplacedCount] = useState(0);
  const [importErrors, setImportErrors] = useState<string[]>([]);

  // Upload files and get preview
  const uploadForPreview = useCallback(async () => {
    if (files.length === 0) return;

    setState('uploading');
    setUploadProgress(0);
    setError(null);

    try {
      // Use first file (could be zip or single audio)
      const file = files[0];
      const formData = new FormData();
      formData.append('file', file);

      // Upload with progress
      const xhr = new XMLHttpRequest();

      const uploadPromise = new Promise<PreviewResponse>((resolve, reject) => {
        xhr.upload.addEventListener('progress', (e) => {
          if (e.lengthComputable) {
            setUploadProgress(Math.round((e.loaded / e.total) * 100));
          }
        });

        xhr.addEventListener('load', () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            try {
              const response = JSON.parse(xhr.responseText);
              resolve(response);
            } catch {
              reject(new Error('Invalid response'));
            }
          } else {
            try {
              const errorData = JSON.parse(xhr.responseText);
              reject(new Error(errorData.detail || 'Upload failed'));
            } catch {
              reject(new Error(`Upload failed: ${xhr.status}`));
            }
          }
        });

        xhr.addEventListener('error', () => reject(new Error('Network error')));
        xhr.addEventListener('abort', () => reject(new Error('Upload cancelled')));
      });

      xhr.open('POST', getApiUrl('/library/import/preview'));
      xhr.send(formData);

      const response = await uploadPromise;

      // Convert to editable tracks with default actions based on quality
      const editableTracks: EditableTrack[] = response.tracks.map(t => {
        // Determine default action based on quality comparison
        let action: 'import' | 'replace' | 'skip' = 'import';
        if (t.duplicate_of) {
          if (t.trump_status === 'trumps') {
            // Incoming is better - default to replace
            action = 'replace';
          } else if (t.trump_status === 'trumped_by') {
            // Existing is better - default to skip
            action = 'skip';
          } else {
            // Equal quality - default to skip
            action = 'skip';
          }
        }
        return {
          ...t,
          artist: t.detected_artist || '',
          album: t.detected_album || '',
          title: t.detected_title || t.filename,
          track_num: t.detected_track_num,
          year: t.detected_year,
          editedFields: new Set<'artist' | 'album' | 'title' | 'track_num' | 'year'>(),
          action,
        };
      });

      setSessionId(response.session_id);
      setTracks(editableTracks);
      setEstimatedSizes(response.estimated_sizes);
      setHasConvertible(response.has_convertible_formats);
      setState('preview');

      // Auto-select FLAC if convertible formats present
      if (response.has_convertible_formats) {
        setFormat('flac');
      }

    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed');
      setState('error');
    }
  }, [files]);

  // Start upload on mount
  useEffect(() => {
    uploadForPreview();
  }, [uploadForPreview]);

  // Update track field and mark as edited
  const updateTrack = (index: number, field: 'artist' | 'album' | 'title' | 'track_num' | 'year', value: string | number | null) => {
    setTracks(prev => {
      const updated = [...prev];
      const track = updated[index];
      const newEditedFields = new Set(track.editedFields);
      newEditedFields.add(field);
      updated[index] = { ...track, [field]: value, editedFields: newEditedFields };
      return updated;
    });
  };

  // Reset a single track field to detected value
  const resetTrackField = (index: number, field: 'artist' | 'album' | 'title' | 'track_num' | 'year') => {
    setTracks(prev => {
      const updated = [...prev];
      const track = updated[index];
      const newEditedFields = new Set(track.editedFields);
      newEditedFields.delete(field);

      let detectedValue: string | number | null;
      switch (field) {
        case 'artist': detectedValue = track.detected_artist || ''; break;
        case 'album': detectedValue = track.detected_album || ''; break;
        case 'title': detectedValue = track.detected_title || track.filename; break;
        case 'track_num': detectedValue = track.detected_track_num; break;
        case 'year': detectedValue = track.detected_year; break;
      }

      updated[index] = { ...track, [field]: detectedValue, editedFields: newEditedFields };
      return updated;
    });
  };

  // Reset all fields for a track to detected values
  const resetTrack = (index: number) => {
    setTracks(prev => {
      const updated = [...prev];
      const track = updated[index];
      updated[index] = {
        ...track,
        artist: track.detected_artist || '',
        album: track.detected_album || '',
        title: track.detected_title || track.filename,
        track_num: track.detected_track_num,
        year: track.detected_year,
        editedFields: new Set(),
      };
      return updated;
    });
  };

  // Reset all tracks to detected values
  const resetAllTracks = () => {
    setTracks(prev => prev.map(track => ({
      ...track,
      artist: track.detected_artist || '',
      album: track.detected_album || '',
      title: track.detected_title || track.filename,
      track_num: track.detected_track_num,
      year: track.detected_year,
      editedFields: new Set(),
    })));
  };

  // Apply value to all tracks (bulk edit) and mark as edited
  const applyToAll = (field: 'artist' | 'album' | 'year', value: string | number | null) => {
    setTracks(prev => prev.map(track => {
      const newEditedFields = new Set(track.editedFields);
      newEditedFields.add(field);
      return { ...track, [field]: value, editedFields: newEditedFields };
    }));
  };

  // Set action for a duplicate track (by index in the full tracks array)
  const setTrackAction = (duplicateIdx: number, action: 'import' | 'replace' | 'skip') => {
    // Find the actual track index - duplicateIdx is the index within filtered duplicates
    const duplicates = tracks.filter((t) => t.duplicate_of);
    if (duplicateIdx >= duplicates.length) return;
    const trackToUpdate = duplicates[duplicateIdx];
    setTracks(prev => prev.map(track =>
      track.relative_path === trackToUpdate.relative_path
        ? { ...track, action }
        : track
    ));
  };

  // State for bulk edit input values
  const [bulkArtist, setBulkArtist] = useState('');
  const [bulkAlbum, setBulkAlbum] = useState('');
  const [bulkYear, setBulkYear] = useState('');

  // Check if any tracks have been edited
  const hasAnyEdits = tracks.some(t => t.editedFields.size > 0);

  // Execute import
  const executeImport = async () => {
    if (!sessionId) return;

    // Filter out tracks with action="skip"
    const tracksToImport = tracks.filter((t) => t.action !== 'skip');

    if (tracksToImport.length === 0) {
      setError('All tracks were skipped');
      setState('error');
      return;
    }

    setState('importing');
    setImportProgress(0);
    setImportErrors([]);

    try {
      const response = await fetch(getApiUrl('/library/import/execute'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          tracks: tracksToImport.map(t => ({
            filename: t.filename,
            relative_path: t.relative_path,
            artist: t.artist || t.detected_artist,
            album: t.album || t.detected_album,
            title: t.title || t.detected_title,
            track_num: t.track_num ?? t.detected_track_num,
            year: t.year ?? t.detected_year,
            detected_artist: t.detected_artist,
            detected_album: t.detected_album,
            detected_title: t.detected_title,
            detected_track_num: t.detected_track_num,
            detected_year: t.detected_year,
            // Quality-based replacement
            action: t.action,
            replace_track_id: t.action === 'replace' ? t.duplicate_of : null,
          })),
          options: {
            format,
            mp3_quality: mp3Quality,
            organization,
            queue_analysis: queueAnalysis,
          },
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Import failed');
      }

      const result = await response.json();

      setImportedCount(result.imported_count);
      setReplacedCount(result.replaced_count || 0);
      setImportErrors(result.errors || []);
      setImportProgress(100);
      setState('complete');

      // Invalidate and refetch all library-related queries to refresh browsers
      await queryClient.invalidateQueries({
        predicate: (query) => {
          const key = query.queryKey[0];
          return typeof key === 'string' && (
            key === 'tracks' ||
            key.startsWith('library')
          );
        },
      });

      onImportComplete?.();

    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import failed');
      setState('error');
    }
  };

  // Get estimated size for current format
  const getEstimatedSize = (): number => {
    if (!estimatedSizes) return 0;
    if (format === 'flac') return estimatedSizes.flac;
    if (format === 'mp3') return estimatedSizes.mp3_320;
    return estimatedSizes.original;
  };

  // Get count of tracks that will actually be imported (not skipped)
  const getImportCount = (): number => {
    return tracks.filter((t) => t.action !== 'skip').length;
  };

  // Get count of tracks that will replace existing ones
  const getReplaceCount = (): number => {
    return tracks.filter((t) => t.action === 'replace').length;
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/80 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative bg-zinc-900 rounded-xl w-full max-w-2xl max-h-[90vh] flex flex-col shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-800">
          <h2 className="text-xl font-semibold text-white flex items-center gap-2">
            <Upload className="w-5 h-5" />
            Import Music
          </h2>
          <button
            onClick={onClose}
            className="p-1 text-zinc-400 hover:text-white rounded-md hover:bg-zinc-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {/* Uploading state */}
          {state === 'uploading' && (
            <div role="status" aria-label="Scanning files" className="text-center py-12">
              <Loader2 className="w-12 h-12 mx-auto mb-4 text-green-400 animate-spin" />
              <p className="text-white mb-2">Scanning files...</p>
              <div className="w-full max-w-xs mx-auto bg-zinc-800 rounded-full h-2">
                <div
                  className="bg-green-500 h-2 rounded-full transition-all duration-300"
                  style={{ width: `${uploadProgress}%` }}
                />
              </div>
              <p className="text-sm text-zinc-500 mt-2">{uploadProgress}%</p>
            </div>
          )}

          {/* Preview state */}
          {state === 'preview' && (
            <div className="space-y-6">
              {/* Summary */}
              <div className="flex items-center justify-between text-sm">
                <span className="text-zinc-400">
                  {tracks.length} track{tracks.length !== 1 ? 's' : ''} found
                </span>
                <span className="text-zinc-400">
                  {formatBytes(getEstimatedSize())}
                </span>
              </div>

              {/* Quality-based duplicate panel */}
              {tracks.some((t) => t.duplicate_of) && (
                <div className="space-y-3">
                  {/* Summary badges */}
                  <div className="flex items-center gap-3">
                    <span className="text-sm text-zinc-400">Duplicates found:</span>
                    {tracks.filter((t) => t.trump_status === 'trumps').length > 0 && (
                      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 bg-green-500/20 text-green-400 text-xs font-medium rounded">
                        <ArrowUp className="w-3 h-3" />
                        {tracks.filter((t) => t.trump_status === 'trumps').length} upgrade{tracks.filter((t) => t.trump_status === 'trumps').length !== 1 ? 's' : ''}
                      </span>
                    )}
                    {tracks.filter((t) => t.trump_status === 'trumped_by').length > 0 && (
                      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 bg-red-500/20 text-red-400 text-xs font-medium rounded">
                        <ArrowDown className="w-3 h-3" />
                        {tracks.filter((t) => t.trump_status === 'trumped_by').length} downgrade{tracks.filter((t) => t.trump_status === 'trumped_by').length !== 1 ? 's' : ''}
                      </span>
                    )}
                    {tracks.filter((t) => t.trump_status === 'equal').length > 0 && (
                      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 bg-zinc-500/20 text-zinc-400 text-xs font-medium rounded">
                        <Minus className="w-3 h-3" />
                        {tracks.filter((t) => t.trump_status === 'equal').length} same
                      </span>
                    )}
                    {/* Bulk actions */}
                    <div className="ml-auto flex items-center gap-2">
                      {tracks.some((t) => t.trump_status === 'trumps') && (
                        <button
                          onClick={() => setTracks(prev => prev.map(t =>
                            t.trump_status === 'trumps' ? { ...t, action: 'replace' as const } : t
                          ))}
                          className="px-2 py-0.5 text-xs bg-green-600/20 text-green-400 hover:bg-green-600/40 rounded transition-colors"
                        >
                          Replace all upgrades
                        </button>
                      )}
                      {tracks.some((t) => t.trump_status === 'trumped_by' || t.trump_status === 'equal') && (
                        <button
                          onClick={() => setTracks(prev => prev.map(t =>
                            (t.trump_status === 'trumped_by' || t.trump_status === 'equal') ? { ...t, action: 'skip' as const } : t
                          ))}
                          className="px-2 py-0.5 text-xs bg-zinc-600/20 text-zinc-400 hover:bg-zinc-600/40 rounded transition-colors"
                        >
                          Skip all downgrades
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Duplicate tracks with quality comparison */}
                  <div className="bg-zinc-800/50 rounded-lg border border-zinc-700/50 divide-y divide-zinc-700/50 max-h-48 overflow-y-auto">
                    {tracks.filter((t) => t.duplicate_of).map((track, idx) => (
                      <div key={track.relative_path} className="p-3">
                        <div className="flex items-start gap-3">
                          {/* Quality indicator */}
                          <div className="flex-shrink-0 mt-0.5">
                            {track.trump_status === 'trumps' && (
                              <div className="w-6 h-6 rounded-full bg-green-500/20 flex items-center justify-center" title="Better quality">
                                <ArrowUp className="w-4 h-4 text-green-400" />
                              </div>
                            )}
                            {track.trump_status === 'trumped_by' && (
                              <div className="w-6 h-6 rounded-full bg-red-500/20 flex items-center justify-center" title="Lower quality">
                                <ArrowDown className="w-4 h-4 text-red-400" />
                              </div>
                            )}
                            {track.trump_status === 'equal' && (
                              <div className="w-6 h-6 rounded-full bg-zinc-500/20 flex items-center justify-center" title="Same quality">
                                <Minus className="w-4 h-4 text-zinc-400" />
                              </div>
                            )}
                          </div>

                          {/* Track info */}
                          <div className="flex-1 min-w-0">
                            <p className="text-sm text-white truncate">
                              {track.artist || track.detected_artist} - {track.title || track.detected_title}
                            </p>
                            <div className="flex items-center gap-2 mt-1 text-xs">
                              <span className={track.trump_status === 'trumps' ? 'text-green-400' : track.trump_status === 'trumped_by' ? 'text-zinc-400' : 'text-zinc-400'}>
                                New: {formatQuality(track.incoming_quality)}
                              </span>
                              <span className="text-zinc-600">vs</span>
                              <span className={track.trump_status === 'trumped_by' ? 'text-green-400' : track.trump_status === 'trumps' ? 'text-zinc-400' : 'text-zinc-400'}>
                                Library: {formatQuality(track.existing_quality)}
                              </span>
                            </div>
                            {track.trump_reason && (
                              <p className="text-xs text-zinc-500 mt-0.5">{track.trump_reason}</p>
                            )}
                            {track.duplicate_match_type === 'artist_title' && track.duplicate_info && (
                              <p className="text-xs text-amber-400/80 mt-0.5">
                                Matched by artist + title only (different album: {track.duplicate_info.split(' - ')[1] || 'unknown'})
                              </p>
                            )}
                          </div>

                          {/* Action buttons */}
                          <div className="flex items-center gap-1 flex-shrink-0">
                            <button
                              onClick={() => setTrackAction(idx, 'skip')}
                              className={`px-2 py-1 text-xs rounded transition-colors ${
                                track.action === 'skip'
                                  ? 'bg-zinc-600 text-white'
                                  : 'bg-zinc-700/50 text-zinc-400 hover:text-white hover:bg-zinc-700'
                              }`}
                            >
                              Skip
                            </button>
                            {track.trump_status === 'trumps' && (
                              <button
                                onClick={() => setTrackAction(idx, 'replace')}
                                className={`px-2 py-1 text-xs rounded transition-colors ${
                                  track.action === 'replace'
                                    ? 'bg-green-600 text-white'
                                    : 'bg-green-600/20 text-green-400 hover:bg-green-600/40'
                                }`}
                              >
                                <RefreshCw className="w-3 h-3 inline mr-1" />
                                Replace
                              </button>
                            )}
                            {track.trump_status !== 'trumps' && (
                              <button
                                onClick={() => setTrackAction(idx, 'import')}
                                className={`px-2 py-1 text-xs rounded transition-colors ${
                                  track.action === 'import'
                                    ? 'bg-amber-600 text-white'
                                    : 'bg-amber-600/20 text-amber-400 hover:bg-amber-600/40'
                                }`}
                                title={track.trump_status === 'trumped_by' ? 'Import anyway (not recommended)' : 'Import as duplicate'}
                              >
                                Import
                              </button>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Track list with tabular editing */}
              <div className="space-y-3">
                {/* Header with expand/collapse and reset */}
                <div className="flex items-center justify-between">
                  <button
                    onClick={() => setExpandedTracks(!expandedTracks)}
                    className="flex items-center gap-2 text-sm text-zinc-400 hover:text-white"
                  >
                    {expandedTracks ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                    {expandedTracks ? 'Show summary' : 'Edit track details'}
                  </button>
                  {expandedTracks && hasAnyEdits && (
                    <button
                      onClick={resetAllTracks}
                      className="flex items-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
                      title="Reset all tracks to detected values"
                    >
                      <RotateCcw className="w-3 h-3" />
                      Reset all
                    </button>
                  )}
                </div>

                {expandedTracks ? (
                  <>
                    {/* Bulk edit section */}
                    {tracks.length > 1 && (
                      <div className="p-3 bg-zinc-800/50 rounded-lg border border-zinc-700/50">
                        <p className="text-xs font-medium text-zinc-400 mb-2">Apply to all tracks</p>
                        <div className="flex gap-2">
                          <div className="flex-1">
                            <label className="text-xs text-zinc-500 mb-1 block">Artist</label>
                            <div className="flex gap-1">
                              <input
                                type="text"
                                value={bulkArtist}
                                onChange={(e) => setBulkArtist(e.target.value)}
                                placeholder="Enter artist..."
                                className="flex-1 px-2 py-1.5 bg-zinc-700 border border-zinc-600 rounded text-sm text-white placeholder-zinc-500"
                              />
                              <button
                                onClick={() => { if (bulkArtist) { applyToAll('artist', bulkArtist); setBulkArtist(''); } }}
                                disabled={!bulkArtist}
                                className="px-2 py-1 text-xs bg-zinc-600 hover:bg-zinc-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded transition-colors"
                              >
                                Apply
                              </button>
                            </div>
                          </div>
                          <div className="flex-1">
                            <label className="text-xs text-zinc-500 mb-1 block">Album</label>
                            <div className="flex gap-1">
                              <input
                                type="text"
                                value={bulkAlbum}
                                onChange={(e) => setBulkAlbum(e.target.value)}
                                placeholder="Enter album..."
                                className="flex-1 px-2 py-1.5 bg-zinc-700 border border-zinc-600 rounded text-sm text-white placeholder-zinc-500"
                              />
                              <button
                                onClick={() => { if (bulkAlbum) { applyToAll('album', bulkAlbum); setBulkAlbum(''); } }}
                                disabled={!bulkAlbum}
                                className="px-2 py-1 text-xs bg-zinc-600 hover:bg-zinc-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded transition-colors"
                              >
                                Apply
                              </button>
                            </div>
                          </div>
                          <div className="w-28">
                            <label className="text-xs text-zinc-500 mb-1 block">Year</label>
                            <div className="flex gap-1">
                              <input
                                type="number"
                                value={bulkYear}
                                onChange={(e) => setBulkYear(e.target.value)}
                                placeholder="YYYY"
                                className="w-16 px-2 py-1.5 bg-zinc-700 border border-zinc-600 rounded text-sm text-white placeholder-zinc-500"
                              />
                              <button
                                onClick={() => { if (bulkYear) { applyToAll('year', parseInt(bulkYear)); setBulkYear(''); } }}
                                disabled={!bulkYear}
                                className="px-2 py-1 text-xs bg-zinc-600 hover:bg-zinc-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded transition-colors"
                              >
                                Apply
                              </button>
                            </div>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Table header */}
                    <div className="grid grid-cols-[40px_48px_1fr_1fr_1fr_64px_32px] gap-2 px-2 text-xs font-medium text-zinc-500 border-b border-zinc-700/50 pb-2">
                      <div></div>
                      <div>#</div>
                      <div>Title</div>
                      <div>Artist</div>
                      <div>Album</div>
                      <div>Year</div>
                      <div></div>
                    </div>

                    {/* Track rows */}
                    <div className="space-y-1 max-h-64 overflow-y-auto">
                      {tracks.map((track, index) => (
                        <div
                          key={track.relative_path}
                          className={`grid grid-cols-[40px_48px_1fr_1fr_1fr_64px_32px] gap-2 items-center py-1.5 px-2 rounded-lg ${
                            track.duplicate_of ? 'bg-amber-500/10 border border-amber-500/20' : 'bg-zinc-800/30 hover:bg-zinc-800/50'
                          } transition-colors`}
                        >
                          {/* Icon and duration */}
                          <div className="flex items-center justify-center">
                            {track.duplicate_of ? (
                              <span title={`Duplicate: ${track.duplicate_info}`}>
                                <AlertCircle className="w-4 h-4 text-amber-400" />
                              </span>
                            ) : track.format === 'zip' ? (
                              <FileArchive className="w-4 h-4 text-zinc-500" />
                            ) : (
                              <Music className="w-4 h-4 text-zinc-500" />
                            )}
                          </div>

                          {/* Track number */}
                          <div className="relative">
                            <input
                              type="number"
                              value={track.track_num || ''}
                              onChange={(e) => updateTrack(index, 'track_num', e.target.value ? parseInt(e.target.value) : null)}
                              placeholder="#"
                              className={`w-full px-1.5 py-1 bg-zinc-700/50 border rounded text-sm text-white placeholder-zinc-500 text-center ${
                                track.editedFields.has('track_num') ? 'border-green-500/50 bg-green-500/10' : 'border-zinc-600/50'
                              }`}
                            />
                          </div>

                          {/* Title */}
                          <div className="relative group">
                            <input
                              type="text"
                              value={track.title}
                              onChange={(e) => updateTrack(index, 'title', e.target.value)}
                              placeholder="Title"
                              title={track.filename}
                              className={`w-full px-2 py-1 bg-zinc-700/50 border rounded text-sm text-white placeholder-zinc-500 ${
                                track.editedFields.has('title') ? 'border-green-500/50 bg-green-500/10' : 'border-zinc-600/50'
                              }`}
                            />
                            {track.editedFields.has('title') && (
                              <button
                                onClick={() => resetTrackField(index, 'title')}
                                className="absolute right-1 top-1/2 -translate-y-1/2 p-0.5 text-zinc-500 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity"
                                title="Reset to detected value"
                              >
                                <RotateCcw className="w-3 h-3" />
                              </button>
                            )}
                          </div>

                          {/* Artist */}
                          <div className="relative group">
                            <input
                              type="text"
                              value={track.artist}
                              onChange={(e) => updateTrack(index, 'artist', e.target.value)}
                              placeholder="Artist"
                              className={`w-full px-2 py-1 bg-zinc-700/50 border rounded text-sm text-white placeholder-zinc-500 ${
                                track.editedFields.has('artist') ? 'border-green-500/50 bg-green-500/10' : 'border-zinc-600/50'
                              }`}
                            />
                            {track.editedFields.has('artist') && (
                              <button
                                onClick={() => resetTrackField(index, 'artist')}
                                className="absolute right-1 top-1/2 -translate-y-1/2 p-0.5 text-zinc-500 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity"
                                title="Reset to detected value"
                              >
                                <RotateCcw className="w-3 h-3" />
                              </button>
                            )}
                          </div>

                          {/* Album */}
                          <div className="relative group">
                            <input
                              type="text"
                              value={track.album}
                              onChange={(e) => updateTrack(index, 'album', e.target.value)}
                              placeholder="Album"
                              className={`w-full px-2 py-1 bg-zinc-700/50 border rounded text-sm text-white placeholder-zinc-500 ${
                                track.editedFields.has('album') ? 'border-green-500/50 bg-green-500/10' : 'border-zinc-600/50'
                              }`}
                            />
                            {track.editedFields.has('album') && (
                              <button
                                onClick={() => resetTrackField(index, 'album')}
                                className="absolute right-1 top-1/2 -translate-y-1/2 p-0.5 text-zinc-500 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity"
                                title="Reset to detected value"
                              >
                                <RotateCcw className="w-3 h-3" />
                              </button>
                            )}
                          </div>

                          {/* Year */}
                          <div className="relative group">
                            <input
                              type="number"
                              value={track.year || ''}
                              onChange={(e) => updateTrack(index, 'year', e.target.value ? parseInt(e.target.value) : null)}
                              placeholder="Year"
                              className={`w-full px-1.5 py-1 bg-zinc-700/50 border rounded text-sm text-white placeholder-zinc-500 text-center ${
                                track.editedFields.has('year') ? 'border-green-500/50 bg-green-500/10' : 'border-zinc-600/50'
                              }`}
                            />
                          </div>

                          {/* Reset track button */}
                          <div className="flex justify-center">
                            {track.editedFields.size > 0 && (
                              <button
                                onClick={() => resetTrack(index)}
                                className="p-1 text-zinc-500 hover:text-white transition-colors"
                                title="Reset all fields to detected values"
                              >
                                <RotateCcw className="w-3.5 h-3.5" />
                              </button>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>

                    {/* Legend */}
                    <div className="flex items-center gap-4 text-xs text-zinc-500 pt-2 border-t border-zinc-700/50">
                      <span className="flex items-center gap-1.5">
                        <span className="w-3 h-3 rounded border border-green-500/50 bg-green-500/10"></span>
                        Edited field
                      </span>
                      <span className="flex items-center gap-1.5">
                        <RotateCcw className="w-3 h-3" />
                        Reset to detected
                      </span>
                    </div>
                  </>
                ) : (
                  /* Collapsed summary view */
                  <div className="bg-zinc-800/50 rounded-lg p-3 max-h-32 overflow-y-auto">
                    {tracks.slice(0, 5).map((track) => (
                      <div key={track.relative_path} className="flex items-center gap-2 text-sm text-zinc-300 py-1">
                        {track.duplicate_of ? (
                          <AlertCircle className="w-3 h-3 text-amber-400 flex-shrink-0" />
                        ) : (
                          <Music className="w-3 h-3 text-zinc-500 flex-shrink-0" />
                        )}
                        <span className={`truncate ${track.duplicate_of ? 'text-amber-200' : ''}`}>
                          {track.artist && track.title
                            ? `${track.artist} - ${track.title}`
                            : track.title || track.filename}
                        </span>
                        {track.editedFields.size > 0 && (
                          <span className="text-xs text-green-400 flex-shrink-0">edited</span>
                        )}
                        <span className="ml-auto text-zinc-500 flex-shrink-0">{formatDuration(track.duration_seconds)}</span>
                      </div>
                    ))}
                    {tracks.length > 5 && (
                      <p className="text-xs text-zinc-500 mt-1">+{tracks.length - 5} more tracks</p>
                    )}
                  </div>
                )}
              </div>

              {/* Format options */}
              {hasConvertible && (
                <div>
                  <h3 className="text-sm font-medium text-zinc-400 mb-2">Format</h3>
                  <div className="space-y-2">
                    <label className="flex items-center gap-3 p-3 bg-zinc-800/50 rounded-lg cursor-pointer hover:bg-zinc-800 transition-colors">
                      <input
                        type="radio"
                        name="format"
                        checked={format === 'original'}
                        onChange={() => setFormat('original')}
                        className="text-green-500"
                      />
                      <div className="flex-1">
                        <span className="text-white">Keep Original</span>
                        <span className="text-zinc-500 text-sm ml-2">
                          {formatBytes(estimatedSizes?.original || 0)}
                        </span>
                      </div>
                    </label>
                    <label className="flex items-center gap-3 p-3 bg-zinc-800/50 rounded-lg cursor-pointer hover:bg-zinc-800 transition-colors">
                      <input
                        type="radio"
                        name="format"
                        checked={format === 'flac'}
                        onChange={() => setFormat('flac')}
                        className="text-green-500"
                      />
                      <div className="flex-1">
                        <span className="text-white">Convert to FLAC</span>
                        <span className="text-zinc-500 text-sm ml-2">
                          {formatBytes(estimatedSizes?.flac || 0)}
                        </span>
                        <span className="text-xs text-green-400 ml-2">Lossless</span>
                      </div>
                    </label>
                    <label className="flex items-center gap-3 p-3 bg-zinc-800/50 rounded-lg cursor-pointer hover:bg-zinc-800 transition-colors">
                      <input
                        type="radio"
                        name="format"
                        checked={format === 'mp3'}
                        onChange={() => setFormat('mp3')}
                        className="text-green-500"
                      />
                      <div className="flex-1 flex items-center gap-2">
                        <span className="text-white">Convert to MP3</span>
                        <select
                          value={mp3Quality}
                          onChange={(e) => setMp3Quality(parseInt(e.target.value))}
                          onClick={(e) => e.stopPropagation()}
                          className="px-2 py-0.5 bg-zinc-700 border border-zinc-600 rounded text-sm text-white"
                        >
                          <option value={320}>320 kbps</option>
                          <option value={192}>192 kbps</option>
                          <option value={128}>128 kbps</option>
                        </select>
                        <span className="text-zinc-500 text-sm">
                          {formatBytes(estimatedSizes?.mp3_320 || 0)}
                        </span>
                      </div>
                    </label>
                  </div>
                </div>
              )}

              {/* Organization options */}
              <div>
                <h3 className="text-sm font-medium text-zinc-400 mb-2">Organization</h3>
                <div className="space-y-2">
                  <label className="flex items-center gap-3 p-3 bg-zinc-800/50 rounded-lg cursor-pointer hover:bg-zinc-800 transition-colors">
                    <input
                      type="radio"
                      name="organization"
                      checked={organization === 'organized'}
                      onChange={() => setOrganization('organized')}
                      className="text-green-500"
                    />
                    <div>
                      <span className="text-white">Organize into folders</span>
                      <p className="text-xs text-zinc-500">Artist / Album / ## - Title.ext</p>
                    </div>
                  </label>
                  <label className="flex items-center gap-3 p-3 bg-zinc-800/50 rounded-lg cursor-pointer hover:bg-zinc-800 transition-colors">
                    <input
                      type="radio"
                      name="organization"
                      checked={organization === 'imports'}
                      onChange={() => setOrganization('imports')}
                      className="text-green-500"
                    />
                    <div>
                      <span className="text-white">Import to _imports folder</span>
                      <p className="text-xs text-zinc-500">Flat structure, timestamped folder</p>
                    </div>
                  </label>
                </div>
              </div>

              {/* Additional options */}
              <div className="space-y-3">
                <label className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    checked={queueAnalysis}
                    onChange={(e) => setQueueAnalysis(e.target.checked)}
                    className="rounded text-green-500"
                  />
                  <span className="text-sm text-zinc-300">
                    Queue for audio analysis after import
                  </span>
                </label>
              </div>
            </div>
          )}

          {/* Importing state */}
          {state === 'importing' && (
            <div role="status" aria-label="Importing tracks" className="text-center py-12">
              <Loader2 className="w-12 h-12 mx-auto mb-4 text-green-400 animate-spin" />
              <p className="text-white mb-2">
                Importing {tracks.length} track{tracks.length !== 1 ? 's' : ''}...
              </p>
              <p className="text-sm text-zinc-500 mb-4">
                {format !== 'original' ? 'Converting and copying files' : 'Copying files'}
              </p>
              {/* Animated progress bar */}
              <div className="w-full max-w-xs mx-auto bg-zinc-800 rounded-full h-2 overflow-hidden">
                <div
                  className="bg-green-500 h-2 rounded-full animate-pulse"
                  style={{
                    width: '100%',
                    animation: 'indeterminate 1.5s ease-in-out infinite',
                  }}
                />
              </div>
              <style>{`
                @keyframes indeterminate {
                  0% { transform: translateX(-100%); width: 50%; }
                  50% { transform: translateX(50%); width: 50%; }
                  100% { transform: translateX(200%); width: 50%; }
                }
              `}</style>
            </div>
          )}

          {/* Complete state */}
          {state === 'complete' && (
            <div className="text-center py-12">
              <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-green-500/20 flex items-center justify-center">
                <Check className="w-8 h-8 text-green-400" />
              </div>
              <h3 className="text-xl font-semibold text-white mb-2">
                Import Complete!
              </h3>
              <p className="text-zinc-400">
                {importedCount > 0 && (
                  <>{importedCount} track{importedCount !== 1 ? 's' : ''} imported</>
                )}
                {importedCount > 0 && replacedCount > 0 && ', '}
                {replacedCount > 0 && (
                  <span className="text-green-400">
                    {replacedCount} upgraded
                  </span>
                )}
                {importedCount === 0 && replacedCount === 0 && 'No tracks imported'}
              </p>
              {importErrors.length > 0 && (
                <div className="mt-4 text-left max-w-md mx-auto">
                  <p className="text-sm text-amber-400 mb-2">
                    {importErrors.length} error{importErrors.length !== 1 ? 's' : ''}:
                  </p>
                  <div className="bg-zinc-800/50 rounded-lg p-2 max-h-32 overflow-y-auto">
                    {importErrors.map((err, i) => (
                      <p key={i} className="text-xs text-zinc-400">{err}</p>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Error state */}
          {state === 'error' && (
            <div className="text-center py-12">
              <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-red-500/20 flex items-center justify-center">
                <AlertCircle className="w-8 h-8 text-red-400" />
              </div>
              <h3 className="text-xl font-semibold text-white mb-2">
                Import Failed
              </h3>
              <p className="text-zinc-400">{error}</p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-zinc-800">
          {state === 'preview' && (
            <>
              <button
                onClick={onClose}
                className="px-4 py-2 text-zinc-400 hover:text-white transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={executeImport}
                disabled={getImportCount() === 0}
                className="px-4 py-2 bg-green-600 hover:bg-green-500 text-white rounded-lg transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Upload className="w-4 h-4" />
                {getReplaceCount() > 0 ? (
                  <>Import {getImportCount() - getReplaceCount()} + Replace {getReplaceCount()}</>
                ) : (
                  <>Import {getImportCount()} track{getImportCount() !== 1 ? 's' : ''}</>
                )}
              </button>
            </>
          )}
          {(state === 'complete' || state === 'error') && (
            <button
              onClick={onClose}
              className="px-4 py-2 bg-zinc-700 hover:bg-zinc-600 text-white rounded-lg transition-colors"
            >
              Close
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
