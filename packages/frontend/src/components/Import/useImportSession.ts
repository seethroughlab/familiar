import { useState, useCallback, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { importSessionApi } from '../../api';
import type {
  EditableTrack,
  EditableField,
  BulkEditField,
  PreviewResponse,
  UploadState,
  FormatOption,
  OrganizationOption,
} from './types';

interface UseImportSessionOptions {
  files: File[];
  onImportComplete?: () => void;
}

export function useImportSession({ files, onImportComplete }: UseImportSessionOptions) {
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

  // Bulk edit input values
  const [bulkArtist, setBulkArtist] = useState('');
  const [bulkAlbum, setBulkAlbum] = useState('');
  const [bulkYear, setBulkYear] = useState('');

  // Upload files and get preview
  const uploadForPreview = useCallback(async () => {
    if (files.length === 0) return;

    setState('uploading');
    setUploadProgress(0);
    setError(null);

    try {
      // Use first file (could be zip or single audio)
      const file = files[0];
      const response = await importSessionApi.preview(file, setUploadProgress);

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
          editedFields: new Set<EditableField>(),
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
  const updateTrack = useCallback((index: number, field: EditableField, value: string | number | null) => {
    setTracks(prev => {
      const updated = [...prev];
      const track = updated[index];
      const newEditedFields = new Set(track.editedFields);
      newEditedFields.add(field);
      updated[index] = { ...track, [field]: value, editedFields: newEditedFields };
      return updated;
    });
  }, []);

  // Reset a single track field to detected value
  const resetTrackField = useCallback((index: number, field: EditableField) => {
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
  }, []);

  // Reset all fields for a track to detected values
  const resetTrack = useCallback((index: number) => {
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
  }, []);

  // Reset all tracks to detected values
  const resetAllTracks = useCallback(() => {
    setTracks(prev => prev.map(track => ({
      ...track,
      artist: track.detected_artist || '',
      album: track.detected_album || '',
      title: track.detected_title || track.filename,
      track_num: track.detected_track_num,
      year: track.detected_year,
      editedFields: new Set(),
    })));
  }, []);

  // Apply value to all tracks (bulk edit) and mark as edited
  const applyToAll = useCallback((field: BulkEditField, value: string | number | null) => {
    setTracks(prev => prev.map(track => {
      const newEditedFields = new Set(track.editedFields);
      newEditedFields.add(field);
      return { ...track, [field]: value, editedFields: newEditedFields };
    }));
  }, []);

  // Set action for a duplicate track (by index in the filtered duplicates array)
  const setTrackAction = useCallback((duplicateIdx: number, action: 'import' | 'replace' | 'skip') => {
    const duplicates = tracks.filter((t) => t.duplicate_of);
    if (duplicateIdx >= duplicates.length) return;
    const trackToUpdate = duplicates[duplicateIdx];
    setTracks(prev => prev.map(track =>
      track.relative_path === trackToUpdate.relative_path
        ? { ...track, action }
        : track
    ));
  }, [tracks]);

  // Bulk actions for duplicate tracks
  const replaceAllUpgrades = useCallback(() => {
    setTracks(prev => prev.map(t =>
      t.trump_status === 'trumps' ? { ...t, action: 'replace' as const } : t
    ));
  }, []);

  const skipAllDowngrades = useCallback(() => {
    setTracks(prev => prev.map(t =>
      (t.trump_status === 'trumped_by' || t.trump_status === 'equal') ? { ...t, action: 'skip' as const } : t
    ));
  }, []);

  // Check if any tracks have been edited
  const hasAnyEdits = tracks.some(t => t.editedFields.size > 0);

  // Execute import
  const executeImport = useCallback(async () => {
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
      const result = await importSessionApi.execute({
        session_id: sessionId,
        tracks: tracksToImport.map((t) => ({
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
          action: t.action,
          replace_track_id: t.action === 'replace' ? t.duplicate_of : null,
        })),
        options: {
          format,
          mp3_quality: mp3Quality,
          organization,
          queue_analysis: queueAnalysis,
        },
      });

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
  }, [sessionId, tracks, format, mp3Quality, organization, queueAnalysis, queryClient, onImportComplete]);

  // Get estimated size for current format
  const getEstimatedSize = useCallback((): number => {
    if (!estimatedSizes) return 0;
    if (format === 'flac') return estimatedSizes.flac;
    if (format === 'mp3') return estimatedSizes.mp3_320;
    return estimatedSizes.original;
  }, [estimatedSizes, format]);

  // Get count of tracks that will actually be imported (not skipped)
  const getImportCount = useCallback((): number => {
    return tracks.filter((t) => t.action !== 'skip').length;
  }, [tracks]);

  // Get count of tracks that will replace existing ones
  const getReplaceCount = useCallback((): number => {
    return tracks.filter((t) => t.action === 'replace').length;
  }, [tracks]);

  return {
    // State
    state,
    uploadProgress,
    tracks,
    estimatedSizes,
    hasConvertible,
    error,
    expandedTracks,
    importedCount,
    replacedCount,
    importErrors,
    hasAnyEdits,

    // Import options
    format,
    setFormat,
    mp3Quality,
    setMp3Quality,
    organization,
    setOrganization,
    queueAnalysis,
    setQueueAnalysis,

    // Bulk edit state
    bulkArtist,
    setBulkArtist,
    bulkAlbum,
    setBulkAlbum,
    bulkYear,
    setBulkYear,

    // UI actions
    setExpandedTracks,

    // Track editing
    updateTrack,
    resetTrackField,
    resetTrack,
    resetAllTracks,
    applyToAll,

    // Duplicate actions
    setTrackAction,
    replaceAllUpgrades,
    skipAllDowngrades,

    // Import actions
    executeImport,

    // Computed values
    getEstimatedSize,
    getImportCount,
    getReplaceCount,
  };
}

export type ImportSession = ReturnType<typeof useImportSession>;
