/**
 * Unified Discovery System Types
 *
 * A unified data model for discovery items across all contexts:
 * - Album detail (similar albums, more from artist)
 * - Artist detail (similar artists)
 * - Playlist recommendations
 * - Full player (track-based discovery)
 * - Library discover dashboard
 */

export type EntityType = 'track' | 'album' | 'artist';

export type LayoutType = 'list' | 'grid' | 'tracklist';

/**
 * Unified discovery item - represents any discoverable entity
 */
export interface DiscoveryItem {
  // Identity
  id?: string;                    // Track/album ID if in library
  entityType: EntityType;

  // Display
  name: string;
  subtitle?: string;              // Artist for tracks, track count for artists
  imageUrl?: string;

  // Library status
  inLibrary: boolean;

  // Relevance
  matchScore?: number;            // 0-1 (displayed as percentage)
  matchReason?: string;           // "Similar to X" or "via Artist Y"

  // Playback context (in-library items)
  playbackContext?: {
    artist: string;
    album?: string;
    trackId?: string;
  };

  // External links (not-in-library items)
  externalLinks?: {
    bandcamp?: string;
    lastfm?: string;
    amazon?: string;
    apple?: string;
  };
}

/**
 * A section of discovery items with a header
 */
export interface DiscoverySection {
  id: string;
  title: string;
  description?: string;
  entityType: EntityType;
  items: DiscoveryItem[];
  layout?: LayoutType;            // Default: 'list'
  icon?: React.ReactNode;
  rawTracks?: import('../../api').DiscoverTrack[];
}

/**
 * Props for the main DiscoveryPanel component
 */
export interface DiscoveryPanelProps {
  // Content
  sections: DiscoverySection[];

  // Optional header customization
  title?: string;                 // Default: 'Discover'
  sources?: string[];             // e.g., ['Last.fm', 'Spotify']

  // State
  loading?: boolean;
  emptyMessage?: string;

  // Behavior
  collapsible?: boolean;
  defaultExpanded?: boolean;

  // Callbacks
  onItemClick?: (item: DiscoveryItem) => void;
  onItemPlay?: (item: DiscoveryItem) => void;
}

/**
 * Props for individual section rendering
 */
export interface DiscoverySectionProps {
  section: DiscoverySection;
  onItemClick?: (item: DiscoveryItem) => void;
  onItemPlay?: (item: DiscoveryItem) => void;
}

/**
 * Props for individual discovery card
 */
export interface DiscoveryCardProps {
  item: DiscoveryItem;
  layout?: LayoutType;
  isPlaying?: boolean;
  onClick?: () => void;
  onPlay?: () => void;
}

/**
 * External link pill configuration
 */
export interface ExternalLinkConfig {
  type: 'bandcamp' | 'lastfm' | 'amazon' | 'apple';
  url: string;
  label?: string;
}

/**
 * Transformation utilities - input types from API responses
 */

// From AlbumDetailResponse
export interface AlbumDiscoveryInput {
  artist: string;
  album: string;
  otherAlbumsByArtist: Array<{
    name: string;
    artist: string;
    year: number | null;
    track_count: number;
    first_track_id: string;
  }>;
  similarAlbums: Array<{
    name: string;
    artist: string;
    year: number | null;
    track_count: number;
    first_track_id: string;
    similarity_score: number;
  }>;
  discoverAlbums: Array<{
    name: string;
    artist: string;
    image_url: string | null;
    lastfm_url: string | null;
    bandcamp_url: string | null;
  }>;
}

// From ArtistDetailResponse
export interface ArtistDiscoveryInput {
  similarArtists: Array<{
    name: string;
    match_score: number;
    in_library: boolean;
    track_count: number | null;
    image_url: string | null;
    lastfm_url: string | null;
    bandcamp_url: string | null;
  }>;
  getArtistImageUrl: (name: string, size: string) => string;
}

// From TrackDiscoverResponse
export interface TrackDiscoveryInput {
  similarTracks: Array<{
    id: string;
    title: string | null;
    artist: string | null;
    album: string | null;
  }>;
  similarArtists: Array<{
    name: string;
    match_score: number;
    in_library: boolean;
    track_count: number | null;
    image_url: string | null;
    lastfm_url: string | null;
    bandcamp_url: string | null;
  }>;
  getArtistImageUrl: (name: string, size: string) => string;
}

// From PlaylistRecommendations
export interface PlaylistDiscoveryInput {
  artists: Array<{
    name: string;
    source: string;
    match_score: number;
    image_url: string | null;
    external_url: string | null;
    local_track_count: number;
  }>;
  tracks: Array<{
    title: string;
    artist: string;
    source: string;
    match_score: number;
    external_url: string | null;
    local_track_id: string | null;
    album: string | null;
  }>;
  sourcesUsed: string[];
}

// From LibraryDiscoverResponse
export interface LibraryDiscoveryInput {
  unheardTracks: Array<{
    id: string;
    title: string | null;
    artist: string | null;
    album: string | null;
    duration_seconds: number | null;
    play_count: number;
  }>;
  deepCuts: Array<{
    id: string;
    title: string | null;
    artist: string | null;
    album: string | null;
    duration_seconds: number | null;
    play_count: number;
  }>;
  recommendedArtists: Array<{
    name: string;
    match_score: number;
    in_library: boolean;
    track_count: number | null;
    image_url: string | null;
    lastfm_url: string | null;
    bandcamp_url: string | null;
    based_on_artist: string;
  }>;
}
