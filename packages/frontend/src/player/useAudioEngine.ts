import { useEffect, useCallback, useState, useRef } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { usePlayerStore } from './playerStore';
import { useAudioSettingsStore } from './audioSettingsStore';
import { tracksApi } from '../api';
import type { Track } from '../types';
import { showError } from '../stores/toastStore';
import { getEngine } from './audio/engineInstance';
import type { EngineEvent } from './audio/types';
import { useActiveSessionStore } from '../stores/activeSessionStore';
import { useFavorites } from '../hooks/useFavorites';
import { log } from './audio/platform';
import { useConnectivityStore } from '../stores/connectivityStore';
import { useOutputStore } from '../stores/outputStore';
import { prefetchService } from '../services/prefetchService';
import { radioController } from './radio/radioController';
import {
  getCrossfadeTrigger,
  getEffectiveCrossfadeDuration,
} from './audio/eventHandlers';

// (Module-level mutable state moved to store/refs — see playerStore._circuitBreakerTimestamps, queueTransitionRef, albumGainCacheRef)

type PlaybackErrorCategory = 'offline-unavailable' | 'network-unreachable' | 'media-decode' | 'other';

function classifyPlaybackError(error: unknown): PlaybackErrorCategory {
  const code = (error as { code?: string })?.code;
  const message = String((error as { message?: string })?.message ?? error ?? '').toLowerCase();

  if (code === 'offline-unavailable' || message.includes('unavailable while offline')) {
    return 'offline-unavailable';
  }

  if (
    message.includes('network request failed') ||
    message.includes('failed to fetch') ||
    message.includes('network connection was lost') ||
    message.includes('not connected to internet') ||
    message.includes('internet connection appears to be offline')
  ) {
    return 'network-unreachable';
  }

  if (message.includes('decode') || message.includes('media')) {
    return 'media-decode';
  }

  return 'other';
}


function getAlbumKey(track: Track): string | null {
  if (!track.album) return null;
  const artist = track.album_artist || track.artist;
  if (!artist) return null;
  return `${artist}::${track.album}`;
}

// ============================================================================
// Main Hook
// ============================================================================

export function useAudioEngine() {
  const [isInitialized, setIsInitialized] = useState(false);
  const engine = getEngine();
  const { isFavorite, toggle: toggleFavorite } = useFavorites();

  const { currentTrack, isPlaying, volume, isLoadingAudio, crossfadeState, queueIndex, queueLength, historyLength } = usePlayerStore(
    useShallow((s) => ({
      currentTrack: s.currentTrack,
      isPlaying: s.isPlaying,
      volume: s.volume,
      isLoadingAudio: s.isLoadingAudio,
      crossfadeState: s.crossfadeState,
      queueIndex: s.queueIndex,
      queueLength: s.queue.length,
      historyLength: s.history.length,
    }))
  );
  const setCurrentTime = usePlayerStore((s) => s.setCurrentTime);
  const setDuration = usePlayerStore((s) => s.setDuration);
  const setIsPlaying = usePlayerStore((s) => s.setIsPlaying);
  const playNext = usePlayerStore((s) => s.playNext);
  const setCrossfadeState = usePlayerStore((s) => s.setCrossfadeState);
  const setNextTrackPreloaded = usePlayerStore((s) => s.setNextTrackPreloaded);
  const advanceToNextTrack = usePlayerStore((s) => s.advanceToNextTrack);
  const setIsLoadingAudio = usePlayerStore((s) => s.setIsLoadingAudio);
  const jumpToQueueIndex = usePlayerStore((s) => s.jumpToQueueIndex);

  // When a network output (WiiM/Sonos/…) is active, the local engine must stay silent —
  // it keeps running as the transport master so the queue advances and mirrors to the device.
  const activeOutputId = useOutputStore((s) => s.activeOutputId);

  const { crossfadeDuration, crossfadeEnabled, normalizationEnabled, normalizationMode, normalizationTargetLufs, normalizationPreamp, normalizationPreventClipping } = useAudioSettingsStore();
  const offlineModeActive = useConnectivityStore((s) => s.offlineModeActive);
  const offlineTrackIds = useConnectivityStore((s) => s.offlineTrackIds);
  const noteStreamLoadFailure = useConnectivityStore((s) => s.noteStreamLoadFailure);
  const noteStreamLoadSuccess = useConnectivityStore((s) => s.noteStreamLoadSuccess);
  const incrementConnectivityCounter = useConnectivityStore((s) => s.incrementCounter);
  const incrementConnectivityCounterBy = useConnectivityStore((s) => s.incrementCounterBy);
  const refreshOfflineTrackIds = useConnectivityStore((s) => s.refreshOfflineTrackIds);

  // Refs for stable access in event handler (avoids re-subscribing on every change)
  const crossfadeEnabledRef = useRef(crossfadeEnabled);
  const crossfadeDurationRef = useRef(crossfadeDuration);
  crossfadeEnabledRef.current = crossfadeEnabled;
  crossfadeDurationRef.current = crossfadeDuration;

  // Mirror activeOutputId into a ref so the timeUpdate event callback can read the
  // current value without re-subscribing. When a network output is active, crossfade
  // is suppressed so the device plays each track to its true end (no clipped tails).
  const activeOutputIdRef = useRef(activeOutputId);
  activeOutputIdRef.current = activeOutputId;

  // Queue transition flag — scoped to hook lifecycle (not module-level)
  const queueTransitionRef = useRef(false);

  // Pre-offline queue snapshot — restored when connectivity recovers
  const preOfflineQueueRef = useRef<{ tracks: Track[]; index: number; source: import('./playerStore.types').QueueSource | null } | null>(null);

  // Album gain cache — scoped to hook lifecycle
  const albumGainCacheRef = useRef(new Map<string, { avgLufs: number; albumPeak: number | null }>());

  // Track IDs that have already been retried once — prevents infinite retry loops
  const retriedTrackIdsRef = useRef(new Set<string>());

  // --------------------------------------------------------------------------
  // Normalization
  // --------------------------------------------------------------------------

  const shouldUseAlbumGain = useCallback((): boolean => {
    if (!normalizationEnabled) return false;
    if (normalizationMode === 'album') return true;
    if (normalizationMode === 'auto') {
      const source = usePlayerStore.getState().queueSource;
      return source?.type === 'album';
    }
    return false;
  }, [normalizationEnabled, normalizationMode]);

  const computeNormalizationGain = useCallback((
    track: Track | null,
    albumData?: { avgLufs: number; albumPeak: number | null } | null,
  ): number => {
    if (!normalizationEnabled) return 1;
    if (!track?.features?.loudness_lufs) return 1;

    const useAlbum = albumData && shouldUseAlbumGain();
    const lufs = useAlbum ? albumData.avgLufs : track.features.loudness_lufs;
    let gainDb = normalizationTargetLufs - lufs + normalizationPreamp;

    if (normalizationPreventClipping) {
      const peak = useAlbum ? albumData.albumPeak : track.features.track_peak;
      if (peak) {
        const maxGainDb = -20 * Math.log10(peak + 1e-10);
        gainDb = Math.min(gainDb, maxGainDb);
      }
    }

    return Math.pow(10, gainDb / 20);
  }, [normalizationEnabled, normalizationTargetLufs, normalizationPreamp, normalizationPreventClipping, shouldUseAlbumGain]);

  const applyNormalizationGain = useCallback((track: Track | null, isCurrent: boolean): void => {
    const albumKey = track ? getAlbumKey(track) : null;
    const albumData = albumKey ? albumGainCacheRef.current.get(albumKey) : undefined;
    const linearGain = computeNormalizationGain(track, albumData);

    if (isCurrent) {
      engine.setNormalizationGain(linearGain);
    } else {
      // Next track (for crossfade preload)
      engine.setNextNormalizationGain?.(linearGain);
    }
  }, [computeNormalizationGain, engine]);

  // --------------------------------------------------------------------------
  // Crossfade handler (ref for stable access in event callback)
  // --------------------------------------------------------------------------

  const executeCrossfadeRef = useRef<(duration: number, nextTrack: Track) => void>(() => {});

  const stopForCircuitBreaker = useCallback(() => {
    incrementConnectivityCounter('skip_storm_circuit_breaker_triggered');
    setIsPlaying(false);
    setIsLoadingAudio(false);
    showError('Playback paused', {
      description: 'Network instability triggered skip protection. Playback stopped cleanly.',
    });
  }, [incrementConnectivityCounter, setIsLoadingAudio, setIsPlaying]);

  const advanceToNextDownloadedTrack = useCallback(async (reason: PlaybackErrorCategory): Promise<boolean> => {
    await refreshOfflineTrackIds().catch(() => {});
    const connectivity = useConnectivityStore.getState();
    const state = usePlayerStore.getState();
    const queue = state.queue;
    if (queue.length === 0) return false;

    const startIdx = state.queueIndex >= 0 ? state.queueIndex : 0;
    const maxScan = queue.length;
    for (let step = 1; step <= maxScan; step++) {
      const idx = (startIdx + step) % queue.length;
      if (state.repeat !== 'all' && idx <= startIdx) break;
      const candidate = queue[idx];
      if (candidate && connectivity.offlineTrackIds.has(candidate.track.id)) {
        if (!usePlayerStore.getState().registerFailureAdvance()) {
          stopForCircuitBreaker();
          return true;
        }
        jumpToQueueIndex(idx, { reason: 'error' });
        return true;
      }
    }

    setIsPlaying(false);
    setIsLoadingAudio(false);
    showError('No downloaded tracks available', {
      description: reason === 'offline-unavailable'
        ? 'This track is not downloaded for offline playback.'
        : 'No downloaded tracks are available to continue playback.',
    });
    return false;
  }, [jumpToQueueIndex, refreshOfflineTrackIds, setIsLoadingAudio, setIsPlaying, stopForCircuitBreaker]);

  const executeCrossfade = useCallback((duration: number, nextTrack: Track) => {
    if (!engine.executeCrossfade) return;

    applyNormalizationGain(nextTrack, false);

    // Set crossfade state in store
    setCrossfadeState('crossfading');

    engine.executeCrossfade(duration, () => {
      // Crossfade complete: update store
      setCrossfadeState('idle');
      setNextTrackPreloaded(false);
      setIsLoadingAudio(false);
    });

    // Advance to next track in the store
    advanceToNextTrack(nextTrack, { reason: 'crossfade' });
  }, [engine, advanceToNextTrack, setCrossfadeState, setNextTrackPreloaded, applyNormalizationGain, setIsLoadingAudio]);

  executeCrossfadeRef.current = executeCrossfade;

  // --------------------------------------------------------------------------
  // Lifecycle & Initialization
  // --------------------------------------------------------------------------

  useEffect(() => {
    if (!isInitialized) {
      const ok = engine.initialize();
      if (ok) setIsInitialized(true);
    }
  }, [isInitialized, engine]);

  // Start/stop prefetch service with engine lifecycle
  useEffect(() => {
    if (!isInitialized) return;
    prefetchService.start();
    return () => prefetchService.stop();
  }, [isInitialized]);

  // Radio suggestions share the engine's lifecycle. Started but disabled by default —
  // nothing is inserted until the listener turns it on (ADR-0005).
  useEffect(() => {
    if (!isInitialized) return;
    radioController.start();
    return () => radioController.stop();
  }, [isInitialized]);

  // --------------------------------------------------------------------------
  // Engine Event Subscription
  // --------------------------------------------------------------------------

  useEffect(() => {
    if (!isInitialized) return;

    return engine.on((event: EngineEvent) => {
      // When ambient mode owns the engine, let the ambient coordinator handle events
      if (useActiveSessionStore.getState().activeSession === 'ambient') return;

      switch (event.type) {
        case 'ended': {
          if (queueTransitionRef.current) return;
          const state = usePlayerStore.getState();
          // Suppress only if the queue was already advanced externally (e.g. user pressed
          // next while the track was ending). Do NOT suppress when isLoadingAudio=true was
          // set by a transient 'waiting' stall on the current track — that scenario would
          // silently block playNext() and leave the player stuck in silence.
          const loadedId = engine.getLoadedTrackId();
          const currentId = state.currentTrack?.id;
          if (loadedId && currentId && loadedId !== currentId) {
            log.debug('ended ignored: queue already advanced', { currentId, loadedId });
            return;
          }
          log.debug('ended event', { trackId: currentId });
          playNext({ reason: 'ended' });
          break;
        }

        case 'error': {
          const state = usePlayerStore.getState();

          // If error during crossfade, roll back the store to the previous track
          if (state.crossfadeState === 'crossfading') {
            // Log the underlying reason — this branch returns before the general
            // error logging below, so the actual media error used to be discarded and
            // "Crossfade failed" was all that reached the logs.
            log.warn('Crossfade failed, rolling back to previous track', {
              reason: event.message,
              code: event.code,
              fromTrack: state.currentTrack?.title,
              rollbackTo: state.history[state.history.length - 1]?.title,
            });
            setCrossfadeState('idle');
            const prevTrack = state.history[state.history.length - 1];
            if (prevTrack) {
              state.setQueueByTrackId(state.queue.map(q => q.track), prevTrack.id, state.queueSource ?? undefined, { reason: 'error' });
            }
            setIsLoadingAudio(false);
            break;
          }

          const trackName = state.currentTrack?.title || state.currentTrack?.file_path || 'Unknown track';
          log.error('Playback error for "%s": %s', trackName, event.message);
          const category = classifyPlaybackError(event);

          const trackId = state.currentTrack?.id;
          if (trackId) {
            // Report error to backend (clears transcode cache if applicable)
            tracksApi.reportPlaybackError(trackId).catch(() => {});
          }

          if (category === 'network-unreachable' || category === 'offline-unavailable') {
            noteStreamLoadFailure(category);
            setIsLoadingAudio(false);
            advanceToNextDownloadedTrack(category).catch(() => {
              setIsPlaying(false);
              setIsLoadingAudio(false);
            });
            break;
          }

          // Single retry before skipping — cache may have been cleared by reportPlaybackError
          if (trackId && !retriedTrackIdsRef.current.has(trackId)) {
            retriedTrackIdsRef.current.add(trackId);
            log.info('Retrying playback for "%s" after error', trackName);
            setIsLoadingAudio(true);
            setTimeout(() => {
              // Re-trigger load by resetting the loaded track ID
              const currentState = usePlayerStore.getState();
              if (currentState.currentTrack?.id === trackId) {
                const url = tracksApi.getStreamUrl(trackId);
                engine.load(trackId, url).then(() => {
                  if (usePlayerStore.getState().currentTrack?.id === trackId) {
                    engine.play().catch(() => {});
                  }
                }).catch(() => {
                  // Retry failed — will hit this error handler again, but retriedTrackIds will prevent infinite loop
                });
              }
            }, 1500);
            break;
          }

          noteStreamLoadFailure('other');
          const hasNextTrack = !!state.getNextTrack();
          if (hasNextTrack) {
            if (!usePlayerStore.getState().registerFailureAdvance()) {
              stopForCircuitBreaker();
              break;
            }
            showError('Skipping track', { description: `${trackName}: ${event.message}` });
            setIsLoadingAudio(false);
            playNext({ reason: 'error' });
          } else {
            showError('Playback error', { description: `${trackName}: ${event.message}` });
            setIsPlaying(false);
            setIsLoadingAudio(false);
          }
          break;
        }

        case 'playing': {
          const state = usePlayerStore.getState();
          if (event.trackId === state.currentTrack?.id) {
            setIsLoadingAudio(false);
            // Clear retry state on successful playback
            retriedTrackIdsRef.current.delete(event.trackId);
          }
          break;
        }

        case 'waiting':
          setIsLoadingAudio(true);
          break;

        case 'canplay': {
          if (usePlayerStore.getState().isPlaying) {
            engine.play().catch(err => {
              if ((err as { name?: string })?.name !== 'AbortError') {
                log.warn('Stall recovery play() failed', err);
              }
            });
          }
          break;
        }

        case 'timeUpdate': {
          setCurrentTime(event.currentTime);
          if (event.duration > 0) setDuration(event.duration);

          // Crossfade timing (only for engines that support it)
          if (!engine.capabilities.crossfade) break;
          if (engine.isCrossfading?.() || queueTransitionRef.current) break;
          if (event.duration <= 0) break;

          const timeRemaining = event.duration - event.currentTime;
          const trigger = getCrossfadeTrigger(
            timeRemaining,
            crossfadeEnabledRef.current,
            crossfadeDurationRef.current,
            Boolean(activeOutputIdRef.current),
          );

          if (trigger === 'preload') {
            const nextTrack = usePlayerStore.getState().getNextTrack();
            if (nextTrack && nextTrack.id !== engine.getPreloadingTrackId?.()) {
              const urlPromise = engine.resolveTrackUrl
                ? engine.resolveTrackUrl(nextTrack.id)
                : Promise.resolve({ url: tracksApi.getStreamUrl(nextTrack.id), isOffline: false });
              urlPromise.then(({ url, isOffline }) => {
                engine.preloadNext?.(nextTrack.id, url, { isOffline });
              }).catch(e => log.error('Failed to preload next track:', e));
            }
          }

          if (trigger === 'crossfade') {
            const nextTrack = usePlayerStore.getState().getNextTrack();
            if (nextTrack && engine.isNextReady?.()) {
              const effectiveDuration = getEffectiveCrossfadeDuration(
                crossfadeEnabledRef.current,
                crossfadeDurationRef.current,
              );
              // Clamp to remaining time minus 0.5s buffer so the old track's
              // scheduleFile callback doesn't fire mid-crossfade
              const clampedDuration = Math.min(effectiveDuration, timeRemaining - 0.5);
              if (clampedDuration < 0.5) break; // not enough time for a meaningful crossfade
              queueTransitionRef.current = true;
              executeCrossfadeRef.current(clampedDuration, nextTrack);
              setTimeout(() => { queueTransitionRef.current = false; }, 1000);
            }
          }
          break;
        }

        case 'remotePlay':
          setIsPlaying(true);
          break;

        case 'remotePause':
          setIsPlaying(false);
          break;

        case 'remoteNext':
          playNext({ reason: 'user' });
          break;

        case 'nativeAutoAdvanced':
          playNext({ reason: 'native-auto' });
          break;

        case 'remotePrevious':
          if (event.nativeAction === 'restart') {
            // Native already seeked to 0 — just sync store state
            setCurrentTime(0);
          } else {
            usePlayerStore.getState().playPrevious();
          }
          break;

        case 'remoteSeek':
          setCurrentTime(event.time);
          break;

        case 'remoteFavoriteToggle':
          toggleFavorite(event.trackId);
          break;
      }
    });
  }, [
    isInitialized,
    engine,
    playNext,
    setIsPlaying,
    setIsLoadingAudio,
    setCurrentTime,
    setDuration,
    noteStreamLoadFailure,
    advanceToNextDownloadedTrack,
    stopForCircuitBreaker,
    setCrossfadeState,
    toggleFavorite,
  ]);

  useEffect(() => {
    const state = usePlayerStore.getState();

    if (!offlineModeActive) {
      // Restore pre-offline queue when connectivity recovers
      const saved = preOfflineQueueRef.current;
      if (saved && saved.tracks.length > 0) {
        const currentId = state.currentTrack?.id;
        const restoredIndex = currentId
          ? saved.tracks.findIndex((t) => t.id === currentId)
          : saved.index;
        state.setQueue(saved.tracks, Math.max(0, restoredIndex), saved.source ?? undefined, { preservePlaybackState: true });
        preOfflineQueueRef.current = null;
      }
      return;
    }

    if (state.queue.length === 0) return;

    const allTracks = state.queue.map((item) => item.track);
    const filteredTracks = allTracks.filter((track) => offlineTrackIds.has(track.id));
    if (filteredTracks.length === allTracks.length) return;

    // Save the full queue before filtering so we can restore on recovery
    if (!preOfflineQueueRef.current) {
      preOfflineQueueRef.current = {
        tracks: allTracks,
        index: state.queueIndex,
        source: state.queueSource,
      };
    }

    incrementConnectivityCounter('offline_queue_rebuild_count');
    const currentId = state.currentTrack?.id;
    const newIndex = currentId
      ? filteredTracks.findIndex((track) => track.id === currentId)
      : -1;

    if (newIndex >= 0) {
      state.setQueue(filteredTracks, newIndex, state.queueSource ?? undefined, { preservePlaybackState: true });
      return;
    }

    state.setQueue(filteredTracks, 0, state.queueSource ?? undefined, { preservePlaybackState: true });
    if (filteredTracks.length === 0) {
      setIsPlaying(false);
      setIsLoadingAudio(false);
    }
  }, [offlineModeActive, offlineTrackIds, incrementConnectivityCounter, setIsLoadingAudio, setIsPlaying]);

  // --------------------------------------------------------------------------
  // Effect: Update Media Session when track changes
  // --------------------------------------------------------------------------

  useEffect(() => {
    if (!currentTrack) return;
    engine.updateNowPlaying({
      title: currentTrack.title || 'Unknown',
      artist: currentTrack.artist || 'Unknown',
      album: currentTrack.album || 'Unknown',
      artworkUrl: currentTrack.id ? tracksApi.getArtworkUrl(currentTrack.id) : undefined,
      albumArtist: currentTrack.album_artist ?? undefined,
      trackNumber: currentTrack.track_number ?? undefined,
      discNumber: currentTrack.disc_number ?? undefined,
      year: currentTrack.year ?? undefined,
      isFavorite: isFavorite(currentTrack.id),
    });
  }, [currentTrack, engine, isFavorite]);

  // --------------------------------------------------------------------------
  // Effect: Sync media session action availability (Web only)
  // --------------------------------------------------------------------------

  useEffect(() => {
    if (!isInitialized || !currentTrack) return;
    if (!engine.updateMediaSessionActions) return;

    const state = usePlayerStore.getState();
    const canGoNext = !!state.getNextTrack();
    engine.updateMediaSessionActions({
      canGoNext,
      canGoPrevious: true, // always true — restarts current track if > 3s (matches iOS native)
    });
  }, [currentTrack?.id, queueIndex, queueLength, engine, isInitialized]);

  // --------------------------------------------------------------------------
  // Effect: Sync pending next/previous track info to native (lock screen controls)
  // --------------------------------------------------------------------------

  useEffect(() => {
    if (!isInitialized || !currentTrack) return;
    if (!engine.syncPendingTracks) return; // Only for CapacitorEngine

    const state = usePlayerStore.getState();
    const nextTrack = state.getNextTrack();
    const prevTrack = state.history[state.history.length - 1] ?? null;
    let cancelled = false;

    const toPendingTrack = async (track: Track | null) => {
      if (!track || !engine.resolveTrackUrl) return null;
      try {
        const resolved = await engine.resolveTrackUrl(track.id);
        return {
          url: resolved.url,
          trackId: track.id,
          title: track.title || 'Unknown',
          artist: track.artist || 'Unknown',
          album: track.album || 'Unknown',
          artworkUrl: track.id ? tracksApi.getArtworkUrl(track.id) : undefined,
        };
      } catch (error) {
        log.warn('pending track resolution failed', { trackId: track.id, error });
        return null;
      }
    };

    const isLikelyLocalUrl = (url: string): boolean => (
      url.startsWith('file://') ||
      url.startsWith('capacitor://') ||
      url.startsWith('content://') ||
      url.startsWith('/local/')
    );

    Promise.all([toPendingTrack(nextTrack), toPendingTrack(prevTrack)])
      .then(([next, previous]) => {
        if (cancelled) return;
        if ((!!nextTrack && !next) || (!!prevTrack && !previous)) {
          incrementConnectivityCounter('remote_command_enablement_mismatch');
        }
        if (offlineModeActive) {
          const candidates = [next, previous].filter((item): item is NonNullable<typeof item> => !!item);
          if (candidates.length > 0) {
            const localCount = candidates.filter((item) => isLikelyLocalUrl(item.url)).length;
            incrementConnectivityCounterBy('pending_sync_local_url_local', localCount);
            incrementConnectivityCounterBy('pending_sync_local_url_total', candidates.length);
          }
        }
        log.info('syncPendingTracks: next=%s(%s) prev=%s(%s)',
          next?.trackId ?? 'none',
          next ? (isLikelyLocalUrl(next.url) ? 'local' : 'remote') : '-',
          previous?.trackId ?? 'none',
          previous ? (isLikelyLocalUrl(previous.url) ? 'local' : 'remote') : '-',
        );
        engine.syncPendingTracks?.({ next, previous });
      })
      .catch((error) => {
        log.warn('syncPendingTracks preparation failed', { error });
      });

    return () => {
      cancelled = true;
    };
  }, [
    currentTrack?.id,
    queueIndex,
    queueLength,
    historyLength,
    offlineModeActive,
    engine,
    isInitialized,
    incrementConnectivityCounter,
    incrementConnectivityCounterBy,
  ]);

  // --------------------------------------------------------------------------
  // Effect: Handle Play/Pause State
  // --------------------------------------------------------------------------

  useEffect(() => {
    if (!isInitialized) return;

    if (isPlaying) {
      // Only call play() if the correct track is loaded
      if (!currentTrack || engine.getLoadedTrackId() !== currentTrack.id) {
        log.debug('play/pause effect — skipping play, wrong track loaded', {
          loadedTrackId: engine.getLoadedTrackId(),
          currentTrackId: currentTrack?.id,
        });
        return;
      }

      log.debug('play/pause effect — play', { trackId: currentTrack.id });
      engine.play().catch(e => {
        if (e?.name === 'NotAllowedError') {
          log.warn('Auto-play blocked');
          setIsPlaying(false);
        } else if (e?.name !== 'AbortError') {
          log.error('Play failed', e);
          setIsPlaying(false);
          setIsLoadingAudio(false);
        }
      });
    } else {
      log.debug('play/pause effect — pause', { trackId: currentTrack?.id });
      engine.pause();
    }
  }, [isPlaying, isInitialized, engine, setIsPlaying, setIsLoadingAudio]);

  // --------------------------------------------------------------------------
  // Effect: Handle Volume Changes
  // --------------------------------------------------------------------------

  useEffect(() => {
    if (!isInitialized) return;
    // Mute local output while casting to a network device (avoids double audio); restore on return.
    engine.setVolume(activeOutputId ? 0 : volume);
  }, [volume, activeOutputId, isInitialized, engine]);

  // --------------------------------------------------------------------------
  // Effect: Load track when currentTrack changes
  // --------------------------------------------------------------------------

  useEffect(() => {
    if (!isInitialized || !currentTrack) return;

    // Don't load during crossfade (crossfade handles track transition)
    if (engine.isCrossfading?.()) return;

    // Already loaded
    if (engine.getLoadedTrackId() === currentTrack.id) {
      setIsLoadingAudio(false);
      return;
    }

    const loadTrack = async () => {
      try {
        setIsLoadingAudio(true);

        // Resolve URL
        let url: string;
        let isOffline = false;

        if (engine.resolveTrackUrl) {
          // Engine supports offline URL resolution (WebAudioEngine)
          const trackUrl = await engine.resolveTrackUrl(currentTrack.id);
          url = trackUrl.url;
          isOffline = trackUrl.isOffline;
        } else {
          // Stream directly (CapacitorEngine)
          url = tracksApi.getStreamUrl(currentTrack.id);
        }

        // Race condition guard: track changed during async URL resolution
        if (usePlayerStore.getState().currentTrack?.id !== currentTrack.id) {
          setIsLoadingAudio(false);
          return;
        }

        log.debug('loadTrack', {
          trackId: currentTrack.id,
          trackTitle: currentTrack.title,
          isOffline,
          isPlaying,
        });

        await engine.load(currentTrack.id, url, { isOffline });
        noteStreamLoadSuccess();

        // Another race condition guard after load
        if (usePlayerStore.getState().currentTrack?.id !== currentTrack.id) {
          setIsLoadingAudio(false);
          return;
        }

        if (isPlaying) {
          try {
            await engine.play();
            noteStreamLoadSuccess();
            setIsLoadingAudio(false);

            // Eager preload: after a short delay, preload the next track
            if (engine.capabilities.crossfade) {
              const loadedId = currentTrack.id;
              setTimeout(() => {
                if (usePlayerStore.getState().currentTrack?.id !== loadedId) return;
                const nextTrack = usePlayerStore.getState().getNextTrack();
                if (nextTrack && nextTrack.id !== engine.getPreloadingTrackId?.()) {
                  const urlPromise = engine.resolveTrackUrl
                    ? engine.resolveTrackUrl(nextTrack.id)
                    : Promise.resolve({ url: tracksApi.getStreamUrl(nextTrack.id), isOffline: false });
                  urlPromise.then(({ url: nextUrl, isOffline: nextIsOffline }) => {
                    engine.preloadNext?.(nextTrack.id, nextUrl, { isOffline: nextIsOffline });
                  }).catch(e => log.error('Eager preload failed:', e));
                }
              }, 2000);
            }
          } catch (e: unknown) {
            const err = e as { name?: string };
            if (err.name !== 'AbortError') {
              log.error('Play failed after load', e);
              setIsLoadingAudio(false);
              setIsPlaying(false);
            }
          }
        } else {
          setIsLoadingAudio(false);
        }
      } catch (e) {
        log.error('Failed to load track', e);
        setIsLoadingAudio(false);
        const category = classifyPlaybackError(e);

        if (category === 'network-unreachable' || category === 'offline-unavailable') {
          noteStreamLoadFailure(category);
          await advanceToNextDownloadedTrack(category);
          return;
        }

        // Single retry before skipping
        if (currentTrack.id && !retriedTrackIdsRef.current.has(currentTrack.id)) {
          retriedTrackIdsRef.current.add(currentTrack.id);
          const trackName = currentTrack.title || 'Unknown track';
          log.info('Retrying load for "%s" after error', trackName);
          tracksApi.reportPlaybackError(currentTrack.id).catch(() => {});
          setIsLoadingAudio(true);
          await new Promise(r => setTimeout(r, 1500));
          // Re-check that this track is still current before retrying
          if (usePlayerStore.getState().currentTrack?.id === currentTrack.id) {
            const retryUrl = tracksApi.getStreamUrl(currentTrack.id);
            try {
              await engine.load(currentTrack.id, retryUrl);
              noteStreamLoadSuccess();
              if (isPlaying) {
                await engine.play();
              }
              setIsLoadingAudio(false);
              return;
            } catch {
              // Retry failed — fall through to skip
              log.error('Retry also failed for "%s"', trackName);
              setIsLoadingAudio(false);
            }
          }
        }

        // Auto-advance on error
        noteStreamLoadFailure('other');
        const state = usePlayerStore.getState();
        const hasNextTrack = !!state.getNextTrack();
        if (hasNextTrack) {
          if (!usePlayerStore.getState().registerFailureAdvance()) {
            stopForCircuitBreaker();
            return;
          }
          const trackName = currentTrack.title || 'Unknown track';
          showError('Skipping track', { description: `${trackName}: failed to load` });
          playNext({ reason: 'error' });
        }
      }
    };

    loadTrack();
  }, [currentTrack?.id, isInitialized, crossfadeState]);

  // --------------------------------------------------------------------------
  // Effect: Fetch album gain and apply normalization on track change
  // --------------------------------------------------------------------------

  useEffect(() => {
    if (!isInitialized || !currentTrack) return;

    let cancelled = false;

    const apply = async () => {
      if (shouldUseAlbumGain()) {
        const albumKey = getAlbumKey(currentTrack);
        if (albumKey && !albumGainCacheRef.current.has(albumKey)) {
          try {
            const resp = await tracksApi.getAlbumGain(currentTrack.id);
            if (!cancelled && resp.album_gain_db != null) {
              const avgLufs = -14.0 - resp.album_gain_db;
              albumGainCacheRef.current.set(albumKey, { avgLufs, albumPeak: resp.album_peak });
            }
          } catch (e) {
            log.warn('Failed to fetch album gain, falling back to track gain', e);
          }
        }
      }
      if (!cancelled) {
        applyNormalizationGain(currentTrack, true);
      }
    };

    apply();

    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentTrack?.id, normalizationMode, isInitialized, shouldUseAlbumGain, applyNormalizationGain]);

  // --------------------------------------------------------------------------
  // Effect: Loading watchdog — clear stuck loading state after 15s
  // --------------------------------------------------------------------------

  useEffect(() => {
    if (!isLoadingAudio) return;
    const timeout = setTimeout(() => {
      const state = usePlayerStore.getState();
      if (!state.isLoadingAudio) return;
      log.warn('Loading timeout - clearing stuck loading state', {
        trackId: state.currentTrack?.id,
        trackTitle: state.currentTrack?.title,
      });
      setIsLoadingAudio(false);
      // The engine should handle recovery internally
    }, 15000);
    return () => clearTimeout(timeout);
  }, [isLoadingAudio, setIsLoadingAudio]);
}
