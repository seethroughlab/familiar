export type {
  QualityInfo,
  TrackPreview,
  PreviewResponse,
} from '../../api/importSession';

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
