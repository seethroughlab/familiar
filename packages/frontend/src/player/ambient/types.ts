/**
 * Ambient mode types.
 *
 * All types specific to the ambient playback feature.
 */

export type AmbientIntensity = 'quiet' | 'balanced' | 'immersive';
export type SnippetLength = 8 | 16 | 24;
export type TransitionDensity = 'sparse' | 'moderate' | 'lush';
export type FilterPreset = 'all' | 'soft' | 'dark' | 'instrumental';
export type AmbientSessionStatus = 'idle' | 'loading' | 'playing' | 'paused' | 'error';

export interface AmbientControls {
  intensity: AmbientIntensity;
  snippetLength: SnippetLength;
  transitionDensity: TransitionDensity;
  filterPreset: FilterPreset;
}

export interface AmbientDescriptor {
  track_id: string;
  title: string | null;
  artist: string | null;
  album: string | null;
  duration_seconds: number | null;
  key: string | null;
  bpm: number | null;
  energy: number | null;
  brightness: number | null;
  valence: number | null;
  instrumentalness: number | null;
  speechiness: number | null;
  dynamic_range_db: number | null;
  energy_shape: string | null;
  section_count: number | null;
  modal_character: string | null;
  acousticness: number | null;
}

export interface AmbientCandidate {
  descriptor: AmbientDescriptor;
  compatibility_score: number;
  key_compatibility: number;
  suggested_start_pct: number;
  suggested_end_pct: number;
}

export interface AmbientSnippet {
  descriptor: AmbientDescriptor;
  startTime: number;
  endTime: number;
  compatibility_score: number;
}

export interface TransitionRecipe {
  droneRootNote: number;
  droneSecondNote: number;
  droneAttackMs: number;
  droneReleaseMs: number;
  motifNotes: number[];
  motifTimingsMs: number[];
  motifNoteDurationMs: number;
}

export interface AmbientSeedRequest {
  track_id?: string;
  artist?: string;
  surprise_me?: boolean;
  filter_preset: FilterPreset;
}

export interface AmbientCandidatesRequest {
  current_track_id: string;
  filter_preset: FilterPreset;
  intensity: AmbientIntensity;
  recent_track_ids: string[];
  recent_artist_names: string[];
  limit: number;
}

export interface AmbientSeedResponse {
  seed: AmbientDescriptor;
  initial_candidates: AmbientCandidate[];
  pool_size: number;
}

export interface AmbientCandidatesResponse {
  candidates: AmbientCandidate[];
  pool_size: number;
  pool_collapsed: boolean;
}
