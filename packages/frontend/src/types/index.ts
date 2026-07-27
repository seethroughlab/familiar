export interface Track {
  id: string;
  file_path: string;
  title: string | null;
  artist: string | null;
  album: string | null;
  album_artist: string | null;
  album_type: 'album' | 'compilation' | 'soundtrack';
  track_number: number | null;
  disc_number: number | null;
  year: number | null;
  genre: string | null;
  duration_seconds: number | null;
  format: string | null;
  analysis_version: number;
  features?: TrackFeatures;
  // Play history (profile-specific)
  last_played_at?: string | null;
  play_count?: number | null;

}

export interface TrackFeatures {
  bpm: number | null;
  key: string | null;
  energy: number | null;
  danceability: number | null;
  valence: number | null;
  acousticness: number | null;
  instrumentalness: number | null;
  speechiness: number | null;
  brightness: number | null;
  harmonic_complexity: number | null;
  swing_ratio: number | null;
  syncopation: number | null;
  loudness_lufs: number | null;
  track_peak: number | null;
  replaygain_track_gain: number | null;
}


export interface PlaylistTrackItem {
  id: string; // track_id
  playlist_track_id: string; // PlaylistTrack.id for reordering/removal
  type: 'local';
  title: string | null;
  artist: string | null;
  album: string | null;
  duration_seconds: number | null;
  position: number;
}

export interface TrackListResponse {
  items: Track[];
  total: number;
  page: number;
  page_size: number;
}

export interface LibraryStats {
  total_tracks: number;
  total_albums: number;
  total_artists: number;
  albums: number;
  compilations: number;
  soundtracks: number;
  analyzed_tracks: number;
  pending_analysis: number;
}

export interface QueueItem {
  track: Track;
  queueId: string;
  /**
   * Set when the radio controller inserted this track rather than the listener
   * choosing it (ADR-0005). The queue shows it differently and offers accept/reject —
   * a suggestion the listener cannot identify as one cannot be judged by them or
   * learned from.
   */
  suggested?: boolean;
}

