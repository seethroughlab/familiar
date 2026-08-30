/**
 * Shared types for the library UI.
 *
 * **The browser registry that used to live here is gone** (ADR-0081 point 3), along with
 * `BrowserProps`, `RegisteredBrowser` and `BrowserMetadata`. What is left is the vocabulary the
 * surviving components share: filters, the artist and album summaries, and the two context-menu
 * states.
 */
import type { Track } from '../../types';


/**
 * Filter state for library browsing.
 */
export interface LibraryFilters {
  search?: string;
  artist?: string;
  album?: string;
  genre?: string;
  yearFrom?: number;
  yearTo?: number;
  // Audio feature filters (0-1 range)
  energyMin?: number;
  energyMax?: number;
  valenceMin?: number;
  valenceMax?: number;
  // Generic feature range filters (for MoodGrid non-default axes)
  fx?: string;
  fxMin?: number;
  fxMax?: number;
  fy?: string;
  fyMin?: number;
  fyMax?: number;
  // Offline filter
  downloadedOnly?: boolean;
}

/**
 * Aggregated artist data for artist-level browsers.
 */
export interface ArtistSummary {
  name: string;
  trackCount: number;
  albumCount: number;
  firstTrackId: string; // For artwork lookup
}

/**
 * Aggregated album data for album-level browsers.
 */
export interface AlbumSummary {
  name: string;
  artist: string;
  year: number | null;
  trackCount: number;
  firstTrackId: string; // For artwork lookup
}








/**
 * Initial context menu state.
 */
/**
 * State for context menu management.
 */
export interface ContextMenuState {
  isOpen: boolean;
  track: Track | null;
  position: { x: number; y: number };
}

export const initialContextMenuState: ContextMenuState = {
  isOpen: false,
  track: null,
  position: { x: 0, y: 0 },
};

/**
 * State for album context menu management.
 */
export interface AlbumContextMenuState {
  isOpen: boolean;
  album: {
    name: string;
    artist: string;
    year: number | null;
    first_track_id: string;
  } | null;
  position: { x: number; y: number };
}

/**
 * Initial album context menu state.
 */
export const initialAlbumContextMenuState: AlbumContextMenuState = {
  isOpen: false,
  album: null,
  position: { x: 0, y: 0 },
};
