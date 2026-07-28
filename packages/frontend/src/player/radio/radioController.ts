/**
 * Radio controller — inserts tracks the listener is likely to enjoy into a playing queue
 * (ADR-0005 decision points 6 and 8).
 *
 * Follows the shape of `player/ambient/AmbientCoordinator`: subscribe to queue position,
 * rank candidates, insert ahead of the play head. The ranking itself is entirely
 * server-side — the same engine ambient uses, under the `RADIO` weight profile — so this
 * file holds cadence and insertion policy only, no scoring.
 *
 * That holds offline too. Rather than going quiet, the offline path looks the ranking up
 * in the precomputed manifest (ADR-0006), which the server built from the downloaded set
 * using the identical scorer. So an offline suggestion is the same suggestion the online
 * path would make over that set, not a degraded approximation — and there is still no
 * scoring code on any client.
 *
 * Cadence is every `INSERT_EVERY_N_TRACKS` (ADR decision point 8). Inserting on queue
 * exhaustion was rejected: a library queue is a lazy reservoir over the whole collection
 * and would effectively never empty, so the trigger would never fire.
 */
import { usePlayerStore } from '../playerStore';
import { useConnectivityStore } from '../../stores/connectivityStore';
import { queueApi } from '../../api/queue';
import { useRadioStore } from '../../stores/radioStore';
import { getOfflineNeighbours } from '../../services/offlineManifestService';
import { cachedTrackToTrack, resolveTrackIds } from '../../services/playlistCache';
import type { Track } from '../../types';
import { createLogger } from '../../utils/logger';

const log = createLogger('Radio');

/** A track worth inserting, and how well it scored. Same shape online and offline. */
interface Candidate {
  track: Track;
  score: number;
}

/** Insert a suggestion every N track changes. Revisit once ADR-0004 data exists. */
export const INSERT_EVERY_N_TRACKS = 4;

/** How many recent tracks/artists to send so the server avoids repeating them. */
const RECENT_WINDOW = 10;

/**
 * How far ahead to insert. 1 = immediately next.
 *
 * 2 leaves the listener's own next choice intact — a suggestion that displaces the very
 * next track reads as the app overriding them, which is the opposite of the intent.
 */
export const INSERT_OFFSET = 2;

class RadioController {
  private unsubscribe: (() => void) | null = null;
  private tracksSinceInsert = 0;
  private inFlight = false;
  /** Suggestions already inserted, so a re-suggest doesn't stack duplicates. */
  private inserted = new Set<string>();

  start(): void {
    if (this.unsubscribe) return;
    log.info('Radio controller started');

    let prevTrackId = usePlayerStore.getState().currentTrack?.id ?? null;

    this.unsubscribe = usePlayerStore.subscribe(() => {
      const trackId = usePlayerStore.getState().currentTrack?.id ?? null;
      if (trackId === prevTrackId) return;
      prevTrackId = trackId;
      if (!trackId) return;

      this.tracksSinceInsert += 1;
      if (this.tracksSinceInsert >= INSERT_EVERY_N_TRACKS) {
        void this.suggest();
      }
    });
  }

  stop(): void {
    this.unsubscribe?.();
    this.unsubscribe = null;
    this.tracksSinceInsert = 0;
    this.inFlight = false;
    this.inserted.clear();
    log.info('Radio controller stopped');
  }

  /** Reads the persisted opt-in. Radio is off until the listener turns it on. */
  isEnabled(): boolean {
    return useRadioStore.getState().enabled;
  }

  /** Ask for a suggestion and insert it. Safe to call directly (e.g. a "suggest now" action). */
  async suggest(): Promise<void> {
    if (!this.isEnabled() || this.inFlight) return;

    const state = usePlayerStore.getState();
    const current = state.currentTrack;
    if (!current) return;

    this.inFlight = true;
    try {
      const recent = state.queue
        .slice(Math.max(0, state.queueIndex - RECENT_WINDOW), state.queueIndex + 1)
        .map((item) => item.track);
      const recentTrackIds = Array.from(new Set(recent.map((t) => t.id)));

      const candidates = useConnectivityStore.getState().offlineModeActive
        ? await this.offlineCandidates(current.id, recentTrackIds)
        : await this.onlineCandidates(current.id, recent, recentTrackIds);

      if (candidates.length === 0) {
        // Too few candidates to rank meaningfully, or nothing downloaded to draw from.
        // Stay quiet rather than insert something arbitrary; retry after the next N.
        this.tracksSinceInsert = 0;
        return;
      }

      const pick = candidates.find(
        (s) => !this.inserted.has(s.track.id) && !this.isQueuedNearby(s.track.id)
      );
      if (!pick) {
        this.tracksSinceInsert = 0;
        return;
      }

      // Re-read: the queue may have moved while the request was in flight.
      const fresh = usePlayerStore.getState();
      const insertAt = Math.min(fresh.queueIndex + INSERT_OFFSET, fresh.queue.length);

      // Under shuffle, both playback and the queue view follow `shuffleOrder`, not the
      // queue array. Without an explicit position `addToQueue` appends to the end of that
      // order, so a suggestion inserted "two ahead" in queue terms lands last in play
      // order — invisible at the bottom of the list and never actually reached.
      const shuffleInsertPosition = fresh.shuffle && fresh.shuffleOrder.length > 0
        ? Math.min(fresh.shuffleIndex + INSERT_OFFSET, fresh.shuffleOrder.length)
        : undefined;

      fresh.addToQueue(pick.track, insertAt, shuffleInsertPosition, { suggested: true });

      this.inserted.add(pick.track.id);
      this.tracksSinceInsert = 0;
      log.info('Inserted suggestion "%s" at %d (score %s)', pick.track.title, insertAt, pick.score);
    } catch (error) {
      // A failed suggestion is not worth surfacing — the listener did not ask for one,
      // and playback is unaffected. Retry naturally after the next N tracks.
      log.warn('Suggestion request failed:', error);
      this.tracksSinceInsert = 0;
    } finally {
      this.inFlight = false;
    }
  }

  /** Rank against the whole library, server-side. */
  private async onlineCandidates(
    currentTrackId: string,
    recent: Track[],
    recentTrackIds: string[],
  ): Promise<Candidate[]> {
    const response = await queueApi.getSuggestions({
      current_track_id: currentTrackId,
      recent_track_ids: recentTrackIds,
      recent_artist_names: Array.from(
        new Set(recent.map((t) => t.artist).filter((a): a is string => !!a))
      ),
      profile: 'radio',
      limit: 5,
    });

    if (response.pool_collapsed) {
      log.debug('No usable suggestion (pool_size %d)', response.pool_size);
      return [];
    }
    return response.suggestions.map((s) => ({ track: s.track, score: s.score }));
  }

  /**
   * Look the ranking up in the precomputed manifest (ADR-0006).
   *
   * No scoring happens here and none ever should — the server ranked the downloaded set
   * against itself using the same `score_candidate()` the online path uses, so an offline
   * suggestion is the same suggestion, not an approximation of one. This resolves ids to
   * tracks and preserves the server's order.
   *
   * The `radio` variant has been generated since ADR-0006 landed and, until now, was
   * consumed by nothing.
   */
  private async offlineCandidates(
    currentTrackId: string,
    recentTrackIds: string[],
  ): Promise<Candidate[]> {
    const neighbours = await getOfflineNeighbours(currentTrackId, {
      profile: 'radio',
      // Radio has no preset control; the server emits its variant under 'all'.
      filterPreset: 'all',
      recentTrackIds,
      limit: 5,
    });
    if (neighbours.length === 0) {
      // Either no manifest yet, or it does not know this seed — a track downloaded since
      // the last refresh is not usable as a seed until then (ADR-0006 accepts this).
      log.debug('No offline neighbours for %s', currentTrackId);
      return [];
    }

    // Filter against what is *actually downloaded* right now, not merely what the manifest
    // was built from. The manifest goes stale when a track is removed, and suggesting a
    // track whose audio is absent is the failure mode ADR-0006 flagged in `offlineScoring`
    // (it read `cachedTracks` — metadata — rather than `offlineTracks`). `addToQueue`
    // enforces the same invariant and would silently drop the insert, leaving this
    // controller's `inserted` bookkeeping out of step with the queue.
    const downloaded = useConnectivityStore.getState().offlineTrackIds;
    const playable = neighbours.filter((n) => downloaded.has(n.trackId));
    if (playable.length === 0) return [];

    const scoreById = new Map(playable.map((n) => [n.trackId, n.score]));
    const cached = await resolveTrackIds(playable.map((n) => n.trackId));

    // resolveTrackIds preserves the requested order, which is the server's ranking.
    return cached.map((track) => ({
      track: cachedTrackToTrack(track),
      score: scoreById.get(track.id) ?? 0,
    }));
  }

  /** Already sitting in the upcoming queue — suggesting it again would be noise. */
  private isQueuedNearby(trackId: string): boolean {
    const { queue, queueIndex } = usePlayerStore.getState();
    return queue.slice(queueIndex, queueIndex + 20).some((item) => item.track.id === trackId);
  }
}

export const radioController = new RadioController();
