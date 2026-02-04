import type { Track } from '../../types';

export interface ColumnDef {
  id: string;
  label: string;
  shortLabel?: string; // For narrow headers
  getValue: (track: Track) => string | number | null | undefined;
  width: string;
  minWidth?: string;
  align?: 'left' | 'center' | 'right';
  format?: (value: unknown) => string;
  category: 'basic' | 'analysis';
}

// Format duration as MM:SS
function formatDuration(seconds: unknown): string {
  if (typeof seconds !== 'number' || !seconds) return '--:--';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

// Format 0-1 values as percentage
function formatPercent(value: unknown): string {
  if (typeof value !== 'number' || value === null) return '-';
  return `${Math.round(value * 100)}%`;
}

// Format BPM
function formatBpm(value: unknown): string {
  if (typeof value !== 'number' || value === null) return '-';
  return Math.round(value).toString();
}

// Format relative date (e.g., "2 days ago", "3 months ago")
function formatRelativeDate(value: unknown): string {
  if (typeof value !== 'string' || !value) return '-';
  const date = new Date(value);
  if (isNaN(date.getTime())) return '-';

  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHour = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHour / 24);
  const diffWeek = Math.floor(diffDay / 7);
  const diffMonth = Math.floor(diffDay / 30);
  const diffYear = Math.floor(diffDay / 365);

  if (diffYear >= 1) return diffYear === 1 ? '1 year ago' : `${diffYear} years ago`;
  if (diffMonth >= 1) return diffMonth === 1 ? '1 month ago' : `${diffMonth} months ago`;
  if (diffWeek >= 1) return diffWeek === 1 ? '1 week ago' : `${diffWeek} weeks ago`;
  if (diffDay >= 1) return diffDay === 1 ? '1 day ago' : `${diffDay} days ago`;
  if (diffHour >= 1) return diffHour === 1 ? '1 hour ago' : `${diffHour} hours ago`;
  if (diffMin >= 1) return diffMin === 1 ? '1 min ago' : `${diffMin} mins ago`;
  return 'Just now';
}

export const COLUMN_DEFINITIONS: ColumnDef[] = [
  // Basic metadata columns
  {
    id: 'artist',
    label: 'Artist',
    getValue: (t) => t.artist,
    width: '1fr',
    minWidth: '100px',
    category: 'basic',
  },
  {
    id: 'album',
    label: 'Album',
    getValue: (t) => t.album,
    width: '1fr',
    minWidth: '100px',
    category: 'basic',
  },
  {
    id: 'duration',
    label: 'Duration',
    shortLabel: 'Dur',
    getValue: (t) => t.duration_seconds,
    width: '4.5rem',
    align: 'right',
    format: formatDuration,
    category: 'basic',
  },
  {
    id: 'year',
    label: 'Year',
    getValue: (t) => t.year,
    width: '4rem',
    align: 'center',
    category: 'basic',
  },
  {
    id: 'genre',
    label: 'Genre',
    getValue: (t) => t.genre,
    width: '8rem',
    minWidth: '60px',
    category: 'basic',
  },
  {
    id: 'trackNum',
    label: 'Track #',
    shortLabel: '#',
    getValue: (t) => t.track_number,
    width: '3.5rem',
    align: 'center',
    category: 'basic',
  },
  {
    id: 'format',
    label: 'Format',
    shortLabel: 'Fmt',
    getValue: (t) => t.format?.toUpperCase(),
    width: '4rem',
    align: 'center',
    category: 'basic',
  },
  {
    id: 'lastPlayed',
    label: 'Last Played',
    shortLabel: 'Played',
    getValue: (t) => t.last_played_at,
    width: '6.5rem',
    align: 'right',
    format: formatRelativeDate,
    category: 'basic',
  },

  // Analysis columns
  {
    id: 'bpm',
    label: 'BPM',
    getValue: (t) => t.features?.bpm,
    width: '4rem',
    align: 'right',
    format: formatBpm,
    category: 'analysis',
  },
  {
    id: 'key',
    label: 'Key',
    getValue: (t) => t.features?.key,
    width: '4rem',
    align: 'center',
    category: 'analysis',
  },
  {
    id: 'energy',
    label: 'Energy',
    shortLabel: 'Enrg',
    getValue: (t) => t.features?.energy,
    width: '4.5rem',
    align: 'right',
    format: formatPercent,
    category: 'analysis',
  },
  {
    id: 'danceability',
    label: 'Danceability',
    shortLabel: 'Dance',
    getValue: (t) => t.features?.danceability,
    width: '4.5rem',
    align: 'right',
    format: formatPercent,
    category: 'analysis',
  },
  {
    id: 'valence',
    label: 'Valence',
    shortLabel: 'Val',
    getValue: (t) => t.features?.valence,
    width: '4.5rem',
    align: 'right',
    format: formatPercent,
    category: 'analysis',
  },
  {
    id: 'acousticness',
    label: 'Acousticness',
    shortLabel: 'Acous',
    getValue: (t) => t.features?.acousticness,
    width: '4.5rem',
    align: 'right',
    format: formatPercent,
    category: 'analysis',
  },
  {
    id: 'instrumentalness',
    label: 'Instrumental',
    shortLabel: 'Instr',
    getValue: (t) => t.features?.instrumentalness,
    width: '4.5rem',
    align: 'right',
    format: formatPercent,
    category: 'analysis',
  },
];

// Create a map for quick lookup
export const COLUMN_MAP = new Map(
  COLUMN_DEFINITIONS.map((col) => [col.id, col])
);

// Get column definition by ID
export function getColumnDef(id: string): ColumnDef | undefined {
  return COLUMN_MAP.get(id);
}

// Get all basic columns
export function getBasicColumns(): ColumnDef[] {
  return COLUMN_DEFINITIONS.filter((col) => col.category === 'basic');
}

// Get all analysis columns
export function getAnalysisColumns(): ColumnDef[] {
  return COLUMN_DEFINITIONS.filter((col) => col.category === 'analysis');
}
