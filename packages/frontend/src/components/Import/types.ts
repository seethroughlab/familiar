// Quality info from backend
export interface QualityInfo {
  format_tier: number;
  format_tier_name: string;
  bitrate: number | null;
  sample_rate: number | null;
  bit_depth: number | null;
  is_lossless: boolean;
  bitrate_mode: string | null;
}

// Types matching backend
export interface TrackPreview {
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

export interface PreviewResponse {
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

export interface EditableTrack extends TrackPreview {
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

export type EditableField = 'artist' | 'album' | 'title' | 'track_num' | 'year';
export type BulkEditField = 'artist' | 'album' | 'year';

export interface ImportModalProps {
  files: File[];
  onClose: () => void;
  onImportComplete?: () => void;
}

export type UploadState = 'uploading' | 'preview' | 'importing' | 'complete' | 'error';
export type FormatOption = 'original' | 'flac' | 'mp3';
export type OrganizationOption = 'organized' | 'imports';

// Utility functions

export function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

export function formatDuration(seconds: number | null): string {
  if (!seconds) return '--:--';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

export function formatQuality(quality: QualityInfo | null): string {
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
