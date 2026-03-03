/**
 * Library Browser types and registry.
 *
 * Follows the same pluggable pattern as the Visualizer API.
 * Browsers are registered at startup and can be selected by the user.
 */
import type { ComponentType } from 'react';
import type { Track } from '../../types';

/**
 * Metadata about a browser for the picker UI.
 */
export interface BrowserMetadata {
  id: string;
  name: string;
  description: string;
  icon: string; // Lucide icon name
  category: 'traditional' | 'spatial' | 'temporal' | 'discovery';
  requiresFeatures: boolean; // Needs audio analysis data (BPM, energy, etc.)
  requiresEmbeddings: boolean; // Needs CLAP embeddings for similarity
}

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
 * Props passed to all browser components.
 */
export interface BrowserProps {
  // Data
  tracks: Track[];
  artists: ArtistSummary[];
  albums: AlbumSummary[];
  isLoading: boolean;

  // Selection (for playlist creation)
  selectedTrackIds: Set<string>;
  onSelectTrack: (id: string, multi: boolean) => void;
  onSelectAll: () => void;
  onClearSelection: () => void;

  // Navigation
  onGoToArtist: (artistName: string) => void;
  onGoToAlbum: (artistName: string, albumName: string) => void;
  onGoToYear: (year: number) => void;
  onGoToYearRange: (yearFrom: number, yearTo: number) => void;
  onGoToGenre: (genre: string) => void;
  onGoToMood: (xAxis: string, xMin: number, xMax: number, yAxis: string, yMin: number, yMax: number) => void;

  // Playback
  onPlayTrack: (trackId: string) => void;
  onPlayTrackAt: (trackId: string, index: number) => void;
  onQueueTrack: (trackId: string) => void;

  // Editing
  onEditTrack: (trackId: string) => void;

  // Filters
  filters: LibraryFilters;
  onFilterChange: (filters: Partial<LibraryFilters>) => void;

  // Offline track IDs (for downloadedOnly filter)
  offlineTrackIds?: Set<string>;
}

/**
 * A registered browser with metadata and component.
 */
export interface RegisteredBrowser {
  metadata: BrowserMetadata;
  component: ComponentType<BrowserProps>;
}

/**
 * Browser registry - maps id to browser info.
 */
export const browserRegistry: Map<string, RegisteredBrowser> = new Map();

/**
 * Register a browser in the registry.
 */
export function registerBrowser(
  metadata: BrowserMetadata,
  component: ComponentType<BrowserProps>
): void {
  browserRegistry.set(metadata.id, { metadata, component });
}

/**
 * Get all registered browsers.
 */
export function getBrowsers(): RegisteredBrowser[] {
  return Array.from(browserRegistry.values());
}

/**
 * Get a specific browser by ID.
 */
export function getBrowser(id: string): RegisteredBrowser | undefined {
  return browserRegistry.get(id);
}

/**
 * Get browsers by category.
 */
export function getBrowsersByCategory(
  category: BrowserMetadata['category']
): RegisteredBrowser[] {
  return getBrowsers().filter((b) => b.metadata.category === category);
}

/**
 * Default browser ID.
 */
export const DEFAULT_BROWSER_ID = 'artist-list';

/**
 * State for context menu management.
 */
export interface ContextMenuState {
  isOpen: boolean;
  track: Track | null;
  position: { x: number; y: number };
}

/**
 * Initial context menu state.
 */
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
