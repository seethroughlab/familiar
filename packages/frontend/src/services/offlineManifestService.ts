/**
 * Offline ranking manifest — fetch, store, look up (ADR-0006).
 *
 * The client carries **no ranking code**. It asks the server to rank its downloaded set
 * while online, stores the result, and offline does a lookup: read the seed's neighbours,
 * drop anything heard recently, take the best that remains. That is the whole algorithm.
 *
 * This replaces `offlineScoring.ts`, which scored candidates as a base of 0.5 minus 0.25
 * for a recently-heard artist over a random shuffle, with every analysis feature
 * discarded. Offline ranking is now identical to online because it *is* online ranking,
 * computed earlier.
 */
import { db, type OfflineManifest, type OfflineManifestVariant } from '../db';
import { getOfflineTrackIds } from './offlineService';
import { getSelectedProfileId } from './profileService';
import { queueApi } from '../api/queue';
import { createLogger } from '../utils/logger';

const log = createLogger('OfflineManifest');

/** Below this the pool is too small to rank meaningfully — matches offlineScoring's old floor. */
export const MIN_POOL_SIZE = 8;

/**
 * How long the offline set must stop changing before the manifest is rebuilt.
 *
 * `offline-tracks-updated` fires once per completed download, so a bulk job of 1,573
 * tracks would otherwise trigger 1,573 rebuilds. Measured on the NAS before this was
 * added: 17 rebuilds in 15 minutes, 21 seconds of server time, and the cost per rebuild
 * grows as the set grows.
 *
 * A manifest is only useful once the device is offline, so rebuilding mid-download buys
 * nothing — waiting for the job to settle is both cheaper and more accurate.
 */
export const REFRESH_DEBOUNCE_MS = 30_000;

export async function loadManifest(): Promise<OfflineManifest | null> {
  const profileId = await getSelectedProfileId();
  if (!profileId) return null;
  try {
    return (await db.offlineManifests.get(profileId)) ?? null;
  } catch (error) {
    log.warn('Failed to read offline manifest:', error);
    return null;
  }
}

/**
 * Ask the server to rank the current offline set, and store the result.
 *
 * Called when the offline set changes and the device is online — by definition it is
 * online, since the set only changes by downloading.
 */
export async function refreshManifest(): Promise<void> {
  const profileId = await getSelectedProfileId();
  if (!profileId) return;

  const trackIds = await getOfflineTrackIds();
  if (trackIds.length < MIN_POOL_SIZE) {
    // Not enough to rank. Drop any stale manifest rather than leaving one that describes
    // a set the device no longer has.
    await db.offlineManifests.delete(profileId).catch(() => {});
    return;
  }

  try {
    const response = await queueApi.getOfflineManifest({ track_ids: trackIds });
    await db.offlineManifests.put({
      profileId,
      variants: response.variants,
      trackCount: response.track_count,
      generatedAt: new Date(),
    });
    log.info('Offline manifest refreshed for %d tracks', trackIds.length);
  } catch (error) {
    // Keep whatever manifest we have: a slightly stale ranking beats none, and the
    // listener did not ask for this.
    log.warn('Offline manifest refresh failed, keeping existing:', error);
  }
}

function findVariant(
  manifest: OfflineManifest,
  profile: string,
  filterPreset: string
): OfflineManifestVariant | null {
  return (
    manifest.variants.find((v) => v.profile === profile && v.filter_preset === filterPreset) ??
    // Radio has no preset control, and a preset added server-side before the client knows
    // about it should degrade to 'all' rather than returning nothing.
    manifest.variants.find((v) => v.profile === profile && v.filter_preset === 'all') ??
    null
  );
}

export interface OfflineNeighbour {
  trackId: string;
  score: number;
}

/**
 * Ranked neighbours for a seed, best first, excluding anything recently played.
 *
 * Returns an empty list when the manifest is missing or does not know the seed — a track
 * downloaded since the last refresh is not usable as a seed until then, which ADR-0006
 * accepts explicitly.
 */
export async function getOfflineNeighbours(
  seedTrackId: string,
  options: { profile?: string; filterPreset?: string; recentTrackIds?: string[]; limit?: number } = {}
): Promise<OfflineNeighbour[]> {
  const { profile = 'ambient', filterPreset = 'all', recentTrackIds = [], limit = 10 } = options;

  const manifest = await loadManifest();
  if (!manifest) return [];

  const variant = findVariant(manifest, profile, filterPreset);
  if (!variant) return [];

  const entry = variant.entries.find((e) => e.track_id === seedTrackId);
  if (!entry) return [];

  const recent = new Set(recentTrackIds);
  return entry.neighbours
    .filter((n) => !recent.has(n.track_id))
    .slice(0, limit)
    .map((n) => ({ trackId: n.track_id, score: n.score }));
}

/**
 * A track fit to begin an offline session, matching the server's `pick_surprise_seed`
 * filters. The client picks from a list rather than choosing by feature — choosing by
 * feature would mean shipping features and the rules for reading them.
 */
export async function pickOfflineSeed(
  options: { profile?: string; filterPreset?: string } = {}
): Promise<string | null> {
  const { profile = 'ambient', filterPreset = 'all' } = options;

  const manifest = await loadManifest();
  if (!manifest) return null;

  const variant = findVariant(manifest, profile, filterPreset);
  if (!variant || variant.seed_track_ids.length === 0) return null;

  return variant.seed_track_ids[Math.floor(Math.random() * variant.seed_track_ids.length)];
}

/**
 * Refresh whenever the offline set changes.
 *
 * `offline-tracks-updated` already exists and already drives
 * `connectivityStore.refreshOfflineTrackIds` — it is exactly the invalidation signal
 * ADR-0006 describes, so nothing new is needed to know when to rebuild.
 */
export function initOfflineManifestSync(): () => void {
  if (typeof window === 'undefined') return () => {};

  let timer: ReturnType<typeof setTimeout> | null = null;

  // Trailing debounce: a download job produces a burst of these, and only the final
  // state is worth ranking.
  const handler = () => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      void refreshManifest();
    }, REFRESH_DEBOUNCE_MS);
  };

  window.addEventListener('offline-tracks-updated', handler);
  void refreshManifest();

  return () => {
    if (timer) clearTimeout(timer);
    window.removeEventListener('offline-tracks-updated', handler);
  };
}
