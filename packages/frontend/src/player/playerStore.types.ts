export type QueueSourceType = 'library' | 'album' | 'playlist' | 'artist' | 'ephemeral' | 'other';

export interface LibraryFilters {
  search?: string;
  artist?: string;
  album?: string;
  genre?: string;
  year_from?: number;
  year_to?: number;
  energy_min?: number;
  energy_max?: number;
  valence_min?: number;
  valence_max?: number;
}

export interface QueueSource {
  type: QueueSourceType;
  id?: string;
  filters?: LibraryFilters;
}
