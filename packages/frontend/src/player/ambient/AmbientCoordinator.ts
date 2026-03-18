/**
 * AmbientCoordinator — module-level singleton class.
 *
 * Orchestrates ambient playback sessions:
 * - Snippet scheduling and timers
 * - Candidate prefetching (keeps 2-3 upcoming planned)
 * - Engine event subscription (timeUpdate for transition triggers, ended for advancement)
 * - Transition execution (synth bridge + engine crossfade)
 * - Lock screen metadata updates
 */

import { getEngine } from '../audio/engineInstance';
import { useAmbientStore } from '../../stores/ambientStore';
import { useActiveSessionStore } from '../../stores/activeSessionStore';
import { usePlayerStore } from '../../stores/playerStore';
import { ambientApi } from '../../api/ambient';
import { tracksApi } from '../../api';
import { getAmbientSynthBridge } from './ambientSynthBridge';
import { selectSnippetWindow } from './snippetSelection';
import { buildTransitionRecipe } from './transitionRecipes';
import { getOfflineCandidates, pickOfflineSurpriseSeed } from './offlineScoring';
import { useConnectivityStore } from '../../stores/connectivityStore';
import { createLogger } from '../../utils/logger';
import type { AudioEngine } from '../audio/types';
import type { EngineEvent } from '../audio/types';
import type {
  AmbientCandidate,
  AmbientDescriptor,
  AmbientSnippet,
} from './types';

const log = createLogger('AmbientCoordinator');

/** Snippet volume ceiling — keeps songs distant/background-like */
const SNIPPET_VOLUME = 0.35;

const sleep = (ms: number) => new Promise<void>(r => setTimeout(r, ms));

class AmbientCoordinator {
  private engine: AudioEngine | null = null;
  private unsubscribeEngine: (() => void) | null = null;
  private transitionTimer: ReturnType<typeof setTimeout> | null = null;
  private fadeInterval: ReturnType<typeof setInterval> | null = null;
  private advancing = false;
  private prefetching = false;

  /**
   * Attach to the audio engine. Called when the ambient screen mounts.
   */
  attach(): void {
    this.engine = getEngine();
  }

  /**
   * Detach from the audio engine. Called when the ambient screen unmounts.
   */
  detach(): void {
    this.unsubscribeEngine?.();
    this.unsubscribeEngine = null;
    this.clearTransitionTimer();
    this.clearFade();
  }

  // ==========================================================================
  // Session lifecycle
  // ==========================================================================

  async startSession(options: {
    trackId?: string;
    artist?: string;
    surpriseMe?: boolean;
  }): Promise<void> {
    const store = useAmbientStore.getState();
    const { filterPreset } = store.controls;

    store.setStatus('loading');
    store.setError(null);

    try {
      let seed: AmbientDescriptor;
      let initialCandidates: AmbientCandidate[];

      const isOffline = useConnectivityStore.getState().offlineModeActive;

      if (isOffline) {
        // Offline: use client-side seed + scoring
        if (options.surpriseMe) {
          const offlineSeed = await pickOfflineSurpriseSeed(filterPreset);
          if (!offlineSeed) throw new Error('No suitable offline tracks for ambient mode');
          seed = offlineSeed;
        } else if (options.trackId) {
          // Use the ambient API descriptor endpoint (might fail offline)
          // Fall back to a basic descriptor
          seed = await this.getDescriptorOfflineFallback(options.trackId);
        } else {
          throw new Error('Offline ambient mode requires a track or Surprise Me');
        }
        const result = await getOfflineCandidates(seed, filterPreset, store.controls.intensity, [], [], 10);
        if (result.error) throw new Error(result.error);
        initialCandidates = result.candidates;
        store.setPoolInfo(result.poolSize, result.poolCollapsed);
      } else {
        // Online: use backend API
        const response = await ambientApi.getSeed({
          track_id: options.trackId,
          artist: options.artist,
          surprise_me: options.surpriseMe,
          filter_preset: filterPreset,
        });
        seed = response.seed;
        initialCandidates = response.initial_candidates;
        store.setPoolInfo(response.pool_size, false);
      }

      store.setSeedDescriptor(seed);

      // Pause normal playback if active (preserve queue)
      const playerState = usePlayerStore.getState();
      if (playerState.isPlaying) {
        playerState.setIsPlaying(false);
      }

      // Take ownership of engine
      useActiveSessionStore.getState().setActiveSession('ambient');

      // Subscribe to engine events
      this.subscribeToEngine();

      // Build and play the seed snippet
      const seedSnippet = this.candidateToSnippet(
        { descriptor: seed, compatibility_score: 1, key_compatibility: 1, suggested_start_pct: 0.25, suggested_end_pct: 0.70 },
        store.controls.snippetLength,
      );

      store.setCurrentSnippet(seedSnippet);

      // Plan upcoming snippets
      const upcoming = initialCandidates.slice(0, 3).map(c =>
        this.candidateToSnippet(c, store.controls.snippetLength)
      );
      store.setUpcomingSnippets(upcoming);

      // Configure synth
      const synth = getAmbientSynthBridge();
      if (synth) {
        await synth.configure({
          droneVolume: 0.3,
          motifVolume: 0.2,
          reverbMix: 0.6,
          delayMix: 0.3,
          lowpassFreq: 2000,
        });
      }

      // Load and play the seed
      await this.playSnippet(seedSnippet);

      store.setStatus('playing');
    } catch (e) {
      log.error('Failed to start ambient session:', e);
      store.setError(e instanceof Error ? e.message : String(e));
      store.setStatus('error');
      useActiveSessionStore.getState().setActiveSession('normal');
    }
  }

  async stopSession(): Promise<void> {
    const store = useAmbientStore.getState();

    this.clearTransitionTimer();
    this.clearFade();

    // Stop synth with release
    const synth = getAmbientSynthBridge();
    if (synth) {
      try {
        await synth.stopWithRelease(2000);
      } catch (e) {
        log.warn('Synth stop failed:', e);
      }
    }

    // Stop engine
    this.engine?.stop();

    // Release ownership
    useActiveSessionStore.getState().setActiveSession('normal');

    // Unsubscribe
    this.unsubscribeEngine?.();
    this.unsubscribeEngine = null;

    store.reset();
  }

  pauseSession(): void {
    this.engine?.pause();
    this.clearTransitionTimer();
    useAmbientStore.getState().setStatus('paused');
  }

  async resumeSession(): Promise<void> {
    try {
      await this.engine?.play();
      this.scheduleTransition();
      useAmbientStore.getState().setStatus('playing');
    } catch (e) {
      log.error('Failed to resume ambient session:', e);
    }
  }

  async skipToNext(): Promise<void> {
    // Quick fade-out before switching (300ms)
    await this.fadeOut(300);
    await this.doAdvance(2000);
  }

  async skipToPrevious(): Promise<void> {
    const store = useAmbientStore.getState();
    const { currentSnippet, history, snippetCurrentTime } = store;

    // If more than 3s into snippet, restart it
    if (snippetCurrentTime > 3 && currentSnippet) {
      this.engine?.seek(currentSnippet.startTime);
      store.setSnippetCurrentTime(0);
      return;
    }

    // Otherwise go to previous from history
    if (history.length === 0) return;

    const prev = history[history.length - 1];

    // Push current back to upcoming
    if (currentSnippet) {
      store.setUpcomingSnippets([currentSnippet, ...store.upcomingSnippets]);
    }

    store.setCurrentSnippet(prev);
    // History was already sliced above; just play the prev snippet
    await this.playSnippet(prev);
  }

  // ==========================================================================
  // Private helpers
  // ==========================================================================

  private subscribeToEngine(): void {
    this.unsubscribeEngine?.();
    if (!this.engine) return;

    this.unsubscribeEngine = this.engine.on((event: EngineEvent) => {
      const activeSession = useActiveSessionStore.getState().activeSession;
      if (activeSession !== 'ambient') return;

      switch (event.type) {
        case 'timeUpdate': {
          const store = useAmbientStore.getState();
          const snippet = store.currentSnippet;
          if (!snippet) break;

          const snippetTime = event.currentTime - snippet.startTime;
          store.setSnippetCurrentTime(Math.max(0, snippetTime));

          // Check if snippet end reached
          const timeToEnd = snippet.endTime - event.currentTime;
          if (timeToEnd <= 4) {
            // Trigger transition to next
            this.advanceToNext();
          }
          break;
        }

        case 'ended':
          this.advanceToNext();
          break;

        case 'remotePlay':
          this.resumeSession();
          break;

        case 'remotePause':
          this.pauseSession();
          break;

        case 'remoteNext':
          this.skipToNext();
          break;

        case 'remotePrevious': {
          const store = useAmbientStore.getState();
          if (store.snippetCurrentTime > 3 && store.currentSnippet) {
            this.engine?.seek(store.currentSnippet.startTime);
            store.setSnippetCurrentTime(0);
          } else {
            this.skipToPrevious();
          }
          break;
        }
      }
    });
  }

  private async playSnippet(snippet: AmbientSnippet): Promise<void> {
    if (!this.engine) return;

    const trackId = snippet.descriptor.track_id;

    // Resolve URL
    let url: string;
    let isOffline = false;
    if (this.engine.resolveTrackUrl) {
      const resolved = await this.engine.resolveTrackUrl(trackId);
      url = resolved.url;
      isOffline = resolved.isOffline;
    } else {
      url = tracksApi.getStreamUrl(trackId);
    }

    await this.engine.load(trackId, url, { isOffline });
    this.engine.seek(snippet.startTime);
    await this.engine.play();

    // Update lock screen
    this.engine.updateNowPlaying({
      title: snippet.descriptor.title || 'Unknown',
      artist: snippet.descriptor.artist || 'Unknown',
      album: 'Ambient Mode',
      artworkUrl: tracksApi.getArtworkUrl(trackId),
    });

    // Sync pending tracks for lock screen
    this.syncLockScreenTracks();

    this.scheduleTransition();

    // Fade in the snippet
    this.fadeIn(4000);
  }

  private scheduleTransition(): void {
    this.clearTransitionTimer();

    const store = useAmbientStore.getState();
    const snippet = store.currentSnippet;
    if (!snippet || !this.engine) return;

    const currentTime = this.engine.getCurrentTime();
    const timeToEnd = (snippet.endTime - currentTime) * 1000; // ms

    if (timeToEnd > 0) {
      this.transitionTimer = setTimeout(() => {
        this.advanceToNext();
      }, Math.max(timeToEnd - 4000, 100)); // Start transition 4s before end
    }
  }

  private clearTransitionTimer(): void {
    if (this.transitionTimer) {
      clearTimeout(this.transitionTimer);
      this.transitionTimer = null;
    }
  }

  private clearFade(): void {
    if (this.fadeInterval) {
      clearInterval(this.fadeInterval);
      this.fadeInterval = null;
    }
  }

  private fadeIn(durationMs: number): void {
    this.clearFade();
    if (!this.engine) return;

    const stepMs = 50;
    const steps = Math.ceil(durationMs / stepMs);
    let step = 0;

    this.engine.setVolume(0);
    this.fadeInterval = setInterval(() => {
      step++;
      const vol = Math.min((step / steps) * SNIPPET_VOLUME, SNIPPET_VOLUME);
      this.engine?.setVolume(vol);
      if (step >= steps) {
        this.clearFade();
      }
    }, stepMs);
  }

  private fadeOut(durationMs: number): Promise<void> {
    this.clearFade();
    if (!this.engine) return Promise.resolve();

    const stepMs = 50;
    const steps = Math.ceil(durationMs / stepMs);
    let step = 0;

    return new Promise<void>((resolve) => {
      this.fadeInterval = setInterval(() => {
        step++;
        const vol = Math.max(SNIPPET_VOLUME * (1 - step / steps), 0);
        this.engine?.setVolume(vol);
        if (step >= steps) {
          this.clearFade();
          resolve();
        }
      }, stepMs);
    });
  }

  private async advanceToNext(): Promise<void> {
    if (this.advancing) return;
    this.advancing = true;
    this.clearTransitionTimer();
    try {
      // Fade out over 4s (transition fires before snippet end)
      await this.fadeOut(4000);
      await this.doAdvance();
    } finally {
      this.advancing = false;
    }
  }

  private async doAdvance(intermissionMs?: number): Promise<void> {
    // Default: random 10-20s; skips use a shorter explicit value
    const pause = intermissionMs ?? (10000 + Math.random() * 10000);
    const store = useAmbientStore.getState();
    const { currentSnippet, upcomingSnippets } = store;

    if (upcomingSnippets.length === 0) {
      log.warn('No upcoming snippets to advance to');
      return;
    }

    // Move current to history
    if (currentSnippet) {
      store.addToHistory(currentSnippet);
    }

    // Pop next from upcoming
    const [next, ...rest] = upcomingSnippets;
    store.setCurrentSnippet(next);
    store.setUpcomingSnippets(rest);

    // Trigger transition synth
    await this.executeTransition(currentSnippet, next);

    // Intermission: let the synth bridge breathe before next snippet
    await sleep(pause);

    // Play the next snippet (includes fade-in)
    await this.playSnippet(next);

    // Prefetch more candidates if running low
    if (rest.length < 2) {
      this.prefetchCandidates();
    }
  }

  private async executeTransition(
    current: AmbientSnippet | null,
    next: AmbientSnippet,
  ): Promise<void> {
    const synth = getAmbientSynthBridge();
    if (!synth || !current) return;

    const store = useAmbientStore.getState();
    const recipe = buildTransitionRecipe(current, next, store.controls.transitionDensity);

    try {
      await synth.startTransition(recipe);
    } catch (e) {
      log.warn('Transition synth failed:', e);
    }
  }

  private candidateToSnippet(
    candidate: AmbientCandidate,
    snippetLength: number,
  ): AmbientSnippet {
    const { descriptor } = candidate;
    const window = selectSnippetWindow(
      descriptor.duration_seconds || 180,
      snippetLength as 8 | 16 | 24,
      candidate.suggested_start_pct,
      candidate.suggested_end_pct,
      descriptor.energy_shape,
    );

    return {
      descriptor,
      startTime: window.startTime,
      endTime: window.endTime,
      compatibility_score: candidate.compatibility_score,
    };
  }

  private async prefetchCandidates(): Promise<void> {
    if (this.prefetching) return;
    this.prefetching = true;

    try {
      const store = useAmbientStore.getState();
      const current = store.currentSnippet;
      if (!current) return;

      const recentTrackIds = [
        current.descriptor.track_id,
        ...store.history.map(s => s.descriptor.track_id),
        ...store.upcomingSnippets.map(s => s.descriptor.track_id),
      ];
      const recentArtists = [
        ...new Set([
          current.descriptor.artist,
          ...store.history.map(s => s.descriptor.artist),
        ].filter(Boolean) as string[]),
      ];

      const isOffline = useConnectivityStore.getState().offlineModeActive;
      let newCandidates: AmbientCandidate[];

      if (isOffline) {
        const result = await getOfflineCandidates(
          current.descriptor,
          store.controls.filterPreset,
          store.controls.intensity,
          recentTrackIds,
          recentArtists,
          5,
        );
        newCandidates = result.candidates;
        store.setPoolInfo(result.poolSize, result.poolCollapsed);
      } else {
        const response = await ambientApi.getCandidates({
          current_track_id: current.descriptor.track_id,
          filter_preset: store.controls.filterPreset,
          intensity: store.controls.intensity,
          recent_track_ids: recentTrackIds,
          recent_artist_names: recentArtists,
          limit: 5,
        });
        newCandidates = response.candidates;
        store.setPoolInfo(response.pool_size, response.pool_collapsed);
      }

      const newSnippets = newCandidates.map(c =>
        this.candidateToSnippet(c, store.controls.snippetLength)
      );
      store.setUpcomingSnippets([...store.upcomingSnippets, ...newSnippets]);
    } catch (e) {
      log.warn('Prefetch candidates failed:', e);
    } finally {
      this.prefetching = false;
    }
  }

  private syncLockScreenTracks(): void {
    if (!this.engine?.syncPendingTracks) return;

    const store = useAmbientStore.getState();
    const upcoming = store.upcomingSnippets[0];
    const prev = store.history[store.history.length - 1];

    const toInfo = (s: AmbientSnippet | undefined) => {
      if (!s) return null;
      return {
        url: tracksApi.getStreamUrl(s.descriptor.track_id),
        trackId: s.descriptor.track_id,
        title: s.descriptor.title || 'Unknown',
        artist: s.descriptor.artist || 'Unknown',
        album: 'Ambient Mode',
        artworkUrl: tracksApi.getArtworkUrl(s.descriptor.track_id),
      };
    };

    this.engine.syncPendingTracks({
      next: toInfo(upcoming),
      previous: toInfo(prev),
    });
  }

  private async getDescriptorOfflineFallback(trackId: string): Promise<AmbientDescriptor> {
    try {
      return await ambientApi.getDescriptor(trackId);
    } catch {
      // Offline fallback: try IndexedDB (basic metadata only, no analysis features)
      const { db } = await import('../../db');
      const cached = await db.cachedTracks.get(trackId);
      if (cached) {
        return {
          track_id: trackId,
          title: cached.title ?? null,
          artist: cached.artist ?? null,
          album: cached.album ?? null,
          duration_seconds: cached.durationSeconds ?? null,
          key: null, bpm: null, energy: null, brightness: null,
          valence: null, instrumentalness: null, speechiness: null,
          dynamic_range_db: null, energy_shape: null, section_count: null,
          modal_character: null, acousticness: null,
        };
      }
      throw new Error('Track not available offline');
    }
  }
}

// Module-level singleton
export const ambientCoordinator = new AmbientCoordinator();
