/**
 * Client-side ambient scoring fallback for offline mode.
 *
 * Uses IndexedDB cached track metadata to build a minimal candidate list
 * when the backend is unreachable. Since CachedTrack only stores basic
 * metadata (no analysis features), scoring is simplified — mostly random
 * selection with artist cooldown and duration filtering.
 */

import { db, type CachedTrack } from '../../db';
import type {
  AmbientCandidate,
  AmbientDescriptor,
  AmbientIntensity,
  FilterPreset,
} from './types';
import { suggestSnippetWindow } from './offlineScoringHelpers';

const MIN_POOL_SIZE = 8;

/**
 * Convert a CachedTrack to a minimal AmbientDescriptor.
 * Analysis features will be null (not available offline).
 */
function cachedTrackToDescriptor(track: CachedTrack): AmbientDescriptor {
  return {
    track_id: track.id,
    title: track.title,
    artist: track.artist,
    album: track.album,
    duration_seconds: track.durationSeconds,
    // Analysis features not available in CachedTrack
    key: null,
    bpm: null,
    energy: null,
    brightness: null,
    valence: null,
    instrumentalness: null,
    speechiness: null,
    dynamic_range_db: null,
    energy_shape: null,
    section_count: null,
    modal_character: null,
    acousticness: null,
  };
}

export interface OfflineScoringResult {
  candidates: AmbientCandidate[];
  poolSize: number;
  poolCollapsed: boolean;
  error?: string;
}

/**
 * Score offline candidates against the current track.
 *
 * Without analysis features, scoring is limited to:
 * - Duration filter (>= 45s)
 * - Exclude recent tracks
 * - Artist cooldown
 * - Random ordering
 */
export async function getOfflineCandidates(
  currentDescriptor: AmbientDescriptor,
  _filterPreset: FilterPreset,
  _intensity: AmbientIntensity,
  recentTrackIds: string[],
  recentArtistNames: string[],
  limit: number = 10,
): Promise<OfflineScoringResult> {
  try {
    const cachedTracks = await db.cachedTracks.toArray();

    if (cachedTracks.length < MIN_POOL_SIZE) {
      return {
        candidates: [],
        poolSize: cachedTracks.length,
        poolCollapsed: true,
        error: `Need at least ${MIN_POOL_SIZE} downloaded tracks for offline ambient mode (have ${cachedTracks.length})`,
      };
    }

    const recentSet = new Set(recentTrackIds);
    const recentArtistsLower = recentArtistNames.map(a => a.toLowerCase());
    const eligible: AmbientDescriptor[] = [];

    for (const track of cachedTracks) {
      if (recentSet.has(track.id)) continue;
      if ((track.durationSeconds ?? 0) < 45) continue;
      eligible.push(cachedTrackToDescriptor(track));
    }

    const poolSize = eligible.length;
    const poolCollapsed = poolSize < 5;

    // Shuffle and apply artist cooldown penalty
    const shuffled = eligible.sort(() => Math.random() - 0.5);

    const scored: AmbientCandidate[] = shuffled.map(d => {
      let score = 0.5; // Base score (no features available)

      // Artist cooldown
      if (d.artist && recentArtistsLower.includes(d.artist.toLowerCase())) {
        score -= 0.25;
      }

      // Slight bonus for different artist than current
      if (d.artist && currentDescriptor.artist && d.artist !== currentDescriptor.artist) {
        score += 0.05;
      }

      const [startPct, endPct] = suggestSnippetWindow(d.duration_seconds, null);
      return {
        descriptor: d,
        compatibility_score: Math.max(0, Math.min(1, score)),
        key_compatibility: 0.5, // Unknown
        suggested_start_pct: startPct,
        suggested_end_pct: endPct,
      };
    });

    scored.sort((a, b) => b.compatibility_score - a.compatibility_score);

    return {
      candidates: scored.slice(0, limit),
      poolSize,
      poolCollapsed,
    };
  } catch (e) {
    return {
      candidates: [],
      poolSize: 0,
      poolCollapsed: true,
      error: `Offline scoring failed: ${e instanceof Error ? e.message : String(e)}`,
    };
  }
}

/**
 * Pick a surprise seed from offline tracks.
 */
export async function pickOfflineSurpriseSeed(
  _filterPreset: FilterPreset,
): Promise<AmbientDescriptor | null> {
  try {
    const cachedTracks = await db.cachedTracks.toArray();
    const eligible = cachedTracks.filter(t => (t.durationSeconds ?? 0) >= 60);

    if (eligible.length === 0) return null;

    // Random pick
    const pick = eligible[Math.floor(Math.random() * eligible.length)];
    return cachedTrackToDescriptor(pick);
  } catch {
    return null;
  }
}
