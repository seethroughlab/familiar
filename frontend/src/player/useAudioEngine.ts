import { useEffect, useCallback, useState, useRef } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { usePlayerStore } from './playerStore';
import { useAudioSettingsStore } from './audioSettingsStore';
import { tracksApi, externalTracksApi } from '../api';
import type { Track } from '../types';
import { showError } from '../stores/toastStore';
import { getEngine, getWebEngine } from './audio/engineInstance';
import type { EngineEvent } from './audio/types';
import { log } from './audio/platform';
import {
  getCrossfadeTrigger,
  getEffectiveCrossfadeDuration,
} from './audio/eventHandlers';

// Module-level cache: albumKey -> { avgLufs, albumPeak }
const albumGainCache = new Map<string, { avgLufs: number; albumPeak: number | null }>();

// Queue transition flag — suppresses ended events during crossfade setup
let queueTransition = false;

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

  const { currentTrack, isPlaying, volume, isLoadingAudio } = usePlayerStore(
    useShallow((s) => ({ currentTrack: s.currentTrack, isPlaying: s.isPlaying, volume: s.volume, isLoadingAudio: s.isLoadingAudio }))
  );
  const setCurrentTime = usePlayerStore((s) => s.setCurrentTime);
  const setDuration = usePlayerStore((s) => s.setDuration);
  const setIsPlaying = usePlayerStore((s) => s.setIsPlaying);
  const playNext = usePlayerStore((s) => s.playNext);
  const setCrossfadeState = usePlayerStore((s) => s.setCrossfadeState);
  const setNextTrackPreloaded = usePlayerStore((s) => s.setNextTrackPreloaded);
  const advanceToNextTrack = usePlayerStore((s) => s.advanceToNextTrack);
  const setIsLoadingAudio = usePlayerStore((s) => s.setIsLoadingAudio);

  const { crossfadeDuration, crossfadeEnabled, normalizationEnabled, normalizationMode, normalizationTargetLufs, normalizationPreamp, normalizationPreventClipping } = useAudioSettingsStore();

  // Refs for stable access in event handler (avoids re-subscribing on every change)
  const crossfadeEnabledRef = useRef(crossfadeEnabled);
  const crossfadeDurationRef = useRef(crossfadeDuration);
  crossfadeEnabledRef.current = crossfadeEnabled;
  crossfadeDurationRef.current = crossfadeDuration;

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
    const albumData = albumKey ? albumGainCache.get(albumKey) : undefined;
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
    advanceToNextTrack(nextTrack);
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

  // --------------------------------------------------------------------------
  // Engine Event Subscription
  // --------------------------------------------------------------------------

  useEffect(() => {
    if (!isInitialized) return;

    return engine.on((event: EngineEvent) => {
      switch (event.type) {
        case 'ended': {
          if (queueTransition) return;
          const state = usePlayerStore.getState();
          log.debug('ended event', { trackId: state.currentTrack?.id });
          playNext();
          break;
        }

        case 'error': {
          const state = usePlayerStore.getState();
          const trackName = state.currentTrack?.title || state.currentTrack?.file_path || 'Unknown track';
          log.error('Playback error for "%s": %s', trackName, event.message);

          if (state.currentTrack?.id && state.currentTrack.track_type !== 'external') {
            tracksApi.reportPlaybackError(state.currentTrack.id).catch(() => {});
          }

          const hasNextTrack = !!state.getNextTrack();
          if (hasNextTrack) {
            showError('Skipping track', { description: `${trackName}: ${event.message}` });
            setIsLoadingAudio(false);
            playNext();
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
          }
          break;
        }

        case 'waiting':
          setIsLoadingAudio(true);
          break;

        case 'timeUpdate': {
          setCurrentTime(event.currentTime);
          if (event.duration > 0) setDuration(event.duration);

          // Crossfade timing (only for engines that support it)
          if (!engine.capabilities.crossfade) break;
          if (engine.isCrossfading?.() || queueTransition) break;
          if (event.duration <= 0) break;

          const timeRemaining = event.duration - event.currentTime;
          const trigger = getCrossfadeTrigger(
            timeRemaining,
            crossfadeEnabledRef.current,
            crossfadeDurationRef.current,
          );

          if (trigger === 'preload') {
            const webEngine = getWebEngine();
            const nextTrack = usePlayerStore.getState().getNextTrack();
            if (nextTrack && webEngine && nextTrack.id !== webEngine.getPreloadingTrackId()) {
              // Resolve URL and preload
              webEngine.resolveTrackUrl(nextTrack.id).then(({ url, isOffline }) => {
                webEngine.preloadNext(nextTrack.id, url, { isOffline });
              }).catch(e => log.error('Failed to preload next track:', e));
            }
          }

          if (trigger === 'crossfade') {
            const webEngine = getWebEngine();
            const nextTrack = usePlayerStore.getState().getNextTrack();
            if (nextTrack && webEngine?.isNextReady()) {
              const effectiveDuration = getEffectiveCrossfadeDuration(
                crossfadeEnabledRef.current,
                crossfadeDurationRef.current,
              );
              queueTransition = true;
              executeCrossfadeRef.current(effectiveDuration, nextTrack);
              setTimeout(() => { queueTransition = false; }, 1000);
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
          playNext();
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
      }
    });
  }, [isInitialized, engine, playNext, setIsPlaying, setIsLoadingAudio, setCurrentTime, setDuration]);

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
    });
  }, [currentTrack, engine]);

  // --------------------------------------------------------------------------
  // Effect: Sync pending next/previous track info to native (lock screen controls)
  // --------------------------------------------------------------------------

  useEffect(() => {
    if (!isInitialized || !currentTrack) return;
    if (!engine.syncPendingTracks) return; // Only for CapacitorEngine

    const state = usePlayerStore.getState();
    const nextTrack = state.getNextTrack();
    const prevTrack = state.history[state.history.length - 1] ?? null;

    engine.syncPendingTracks({
      next: nextTrack ? {
        url: tracksApi.getStreamUrl(nextTrack.id),
        trackId: nextTrack.id,
        title: nextTrack.title || 'Unknown',
        artist: nextTrack.artist || 'Unknown',
        album: nextTrack.album || 'Unknown',
        artworkUrl: nextTrack.id ? tracksApi.getArtworkUrl(nextTrack.id) : undefined,
      } : null,
      previous: prevTrack ? {
        url: tracksApi.getStreamUrl(prevTrack.id),
        trackId: prevTrack.id,
        title: prevTrack.title || 'Unknown',
        artist: prevTrack.artist || 'Unknown',
        album: prevTrack.album || 'Unknown',
        artworkUrl: prevTrack.id ? tracksApi.getArtworkUrl(prevTrack.id) : undefined,
      } : null,
    });
  }, [currentTrack?.id, engine, isInitialized]);

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
    engine.setVolume(volume);
  }, [volume, isInitialized, engine]);

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

        // Check external preview settings
        const state = usePlayerStore.getState();
        const currentQueueItem = state.queue[state.queueIndex];
        const externalInfo = currentQueueItem?.externalInfo;

        if (externalInfo && !useAudioSettingsStore.getState().playExternalPreviews) {
          log.info('External previews disabled, auto-advancing');
          setIsLoadingAudio(false);
          playNext();
          return;
        }

        // Resolve URL
        let url: string;
        let isOffline = false;
        const isExternal = !!externalInfo;

        if (externalInfo) {
          let previewUrl = externalInfo.previewUrl;
          if (!previewUrl && externalInfo.originalId) {
            try {
              const result = await externalTracksApi.resolvePreviewUrl(externalInfo.originalId);
              previewUrl = result.preview_url;
            } catch (e) {
              log.warn('Failed to resolve preview URL', e);
            }
          }
          if (!previewUrl) {
            log.info('No preview URL for external track, auto-advancing');
            setIsLoadingAudio(false);
            playNext();
            return;
          }
          url = previewUrl;
        } else {
          // Web engine: check offline storage. Native engine: stream directly.
          const webEngine = getWebEngine();
          if (webEngine) {
            const trackUrl = await webEngine.resolveTrackUrl(currentTrack.id);
            url = trackUrl.url;
            isOffline = trackUrl.isOffline;
          } else {
            url = tracksApi.getStreamUrl(currentTrack.id);
          }
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
          isExternal,
          isPlaying,
        });

        await engine.load(currentTrack.id, url, { isOffline, isExternal });

        // Another race condition guard after load
        if (usePlayerStore.getState().currentTrack?.id !== currentTrack.id) {
          setIsLoadingAudio(false);
          return;
        }

        if (isPlaying) {
          try {
            await engine.play();
            setIsLoadingAudio(false);

            // Eager preload: after a short delay, preload the next track
            if (engine.capabilities.crossfade) {
              const loadedId = currentTrack.id;
              const webEngine = getWebEngine();
              setTimeout(() => {
                if (usePlayerStore.getState().currentTrack?.id !== loadedId) return;
                const nextTrack = usePlayerStore.getState().getNextTrack();
                if (nextTrack && webEngine && nextTrack.id !== webEngine.getPreloadingTrackId()) {
                  webEngine.resolveTrackUrl(nextTrack.id).then(({ url: nextUrl, isOffline: nextIsOffline }) => {
                    webEngine.preloadNext(nextTrack.id, nextUrl, { isOffline: nextIsOffline });
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

        // Auto-advance on error
        const state = usePlayerStore.getState();
        const hasNextTrack = !!state.getNextTrack();
        if (hasNextTrack) {
          const trackName = currentTrack.title || 'Unknown track';
          showError('Skipping track', { description: `${trackName}: failed to load` });
          playNext();
        }
      }
    };

    loadTrack();

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentTrack?.id, isInitialized]);

  // --------------------------------------------------------------------------
  // Effect: Fetch album gain and apply normalization on track change
  // --------------------------------------------------------------------------

  useEffect(() => {
    if (!isInitialized || !currentTrack) return;

    let cancelled = false;

    const apply = async () => {
      if (shouldUseAlbumGain()) {
        const albumKey = getAlbumKey(currentTrack);
        if (albumKey && !albumGainCache.has(albumKey)) {
          try {
            const resp = await tracksApi.getAlbumGain(currentTrack.id);
            if (!cancelled && resp.album_gain_db != null) {
              const avgLufs = -14.0 - resp.album_gain_db;
              albumGainCache.set(albumKey, { avgLufs, albumPeak: resp.album_peak });
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
