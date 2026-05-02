export type CarPlayLibraryBucketId = 'recently-played' | 'artists' | 'albums';

export interface CarPlayTrackSnapshot {
  id: string;
  title: string;
  subtitle?: string | null;
  artist?: string | null;
  album?: string | null;
  artworkUrl?: string | null;
}

export interface CarPlayCollectionSnapshot {
  id: string;
  title: string;
  subtitle?: string | null;
  tracks: CarPlayTrackSnapshot[];
}

export interface CarPlayLibraryBucketSnapshot {
  id: CarPlayLibraryBucketId;
  title: string;
  tracks?: CarPlayTrackSnapshot[];
  collections?: CarPlayCollectionSnapshot[];
}

export interface CarPlayPlaylistSnapshot {
  id: string;
  title: string;
  subtitle?: string | null;
  tracks: CarPlayTrackSnapshot[];
}

export interface CarPlayNowPlayingSnapshot {
  trackId: string;
  title: string;
  artist: string;
  album: string;
  artworkUrl?: string | null;
  isPlaying: boolean;
  isFavorite: boolean;
}

export interface CarPlayLibrarySelectionEvent {
  bucketId: CarPlayLibraryBucketId;
  selectionType: 'bucket' | 'collection' | 'track';
  itemId: string;
  parentId?: string | null;
}

export interface CarPlayPlaylistSelectionEvent {
  playlistId: string;
}

export interface CarPlayPlaylistTrackSelectionEvent {
  playlistId: string;
  trackId: string;
}

export interface CarPlayFavoriteTrackSelectionEvent {
  trackId: string;
}
