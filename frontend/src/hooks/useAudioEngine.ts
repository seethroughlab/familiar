import { useEffect, useCallback, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { usePlayerStore } from '../stores/playerStore';
import { useAudioSettingsStore } from '../stores/audioSettingsStore';
import { tracksApi, externalTracksApi } from '../api/client';
import type { Track } from '../types';
import { revokeOfflineTrackUrl } from '../services/offlineService';
import { showError } from '../stores/toastStore';

import {
  initializeAudioGraph,
  getCurrentElement,
  getNextElement,
  getCurrentNormGain,
  getNextNormGain,
  getGlobalAudioContext,
  getGlobalMasterGain,
  getCrossfadeContext,
  getCurrentOfflineUrl,
  setCurrentOfflineUrl,
  setCurrentMasterVolume,
  getQueueTransition,
  setQueueTransition,
  getPreloadingTrackId,
  getWebAudioElementA,
  getWebAudioElementB,
  getDirectElementA,
  getDirectElementB,
  getCurrentElementIsA,
  setLoadedTrackId,
  getTrackUrl,
} from './audio/audioGraph';

import {
  preloadNextTrack as preloadNextTrackModule,
  executeCrossfade as executeCrossfadeModule,
  cancelCrossfade as cancelCrossfadeModule,
} from './audio/crossfade';

import {
  shouldHandleEnded,
  getErrorAction,
  getCrossfadeTrigger,
  getEffectiveCrossfadeDuration,
} from './audio/eventHandlers';

import {
  useDirectPlayback,
  useWebAudio,
  MOBILE_TRANSITION_OVERLAP,
  log,
} from './audio/platform';

// Module-level cache: albumKey -> { avgLufs, albumPeak }
const albumGainCache = new Map<string, { avgLufs: number; albumPeak: number | null }>();

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

  const { currentTrack, isPlaying, volume } = usePlayerStore(
    useShallow((s) => ({ currentTrack: s.currentTrack, isPlaying: s.isPlaying, volume: s.volume }))
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
    if (!useWebAudio) return;
    const normGain = isCurrent ? getCurrentNormGain() : getNextNormGain();
    if (!normGain) return;

    const albumKey = track ? getAlbumKey(track) : null;
    const albumData = albumKey ? albumGainCache.get(albumKey) : undefined;
    const linearGain = computeNormalizationGain(track, albumData);
    normGain.gain.value = linearGain;
  }, [computeNormalizationGain]);

  // --------------------------------------------------------------------------
  // Crossfade wrappers (delegate to extracted modules)
  // --------------------------------------------------------------------------

  const onCrossfadeComplete = useCallback(() => {
    setIsLoadingAudio(false);
  }, [setIsLoadingAudio]);

  const executeCrossfade = useCallback((duration: number, nextTrack: Track) => {
    applyNormalizationGain(nextTrack, false);
    executeCrossfadeModule(
      duration,
      nextTrack,
      advanceToNextTrack,
      setCrossfadeState,
      setNextTrackPreloaded,
      onCrossfadeComplete,
    );
  }, [advanceToNextTrack, setCrossfadeState, setNextTrackPreloaded, applyNormalizationGain, onCrossfadeComplete]);

  const cancelCrossfade = useCallback(() => {
    cancelCrossfadeModule(setCrossfadeState, setNextTrackPreloaded);
  }, [setCrossfadeState, setNextTrackPreloaded]);

  // --------------------------------------------------------------------------
  // Lifecycle & Initialization
  // --------------------------------------------------------------------------

  useEffect(() => {
    if (!isInitialized) {
      const ok = initializeAudioGraph();
      if (ok) setIsInitialized(true);
    }
  }, [isInitialized]);

  // Handle errors and ended events
  useEffect(() => {
    if (!isInitialized) return;

    const elements = [
      getWebAudioElementA(), getWebAudioElementB(),
      getDirectElementA(), getDirectElementB()
    ].filter((e): e is HTMLAudioElement => e !== null);

    const handleEnded = (e: Event) => {
      const target = e.target as HTMLAudioElement;
      if (shouldHandleEnded(
        target,
        getWebAudioElementA(),
        getDirectElementA(),
        getQueueTransition(),
        getCurrentElementIsA(),
        !!getCrossfadeContext()?.isActive,
      )) {
        playNext();
      }
    };

    const handleError = (e: Event) => {
      const target = e.target as HTMLAudioElement;
      const action = getErrorAction(
        target,
        getCurrentElement(),
        !!getCrossfadeContext()?.isActive,
        usePlayerStore.getState().isPlaying,
      );

      if (action === 'ignore') return;

      if (action === 'cancel-crossfade') {
        cancelCrossfadeModule(setCrossfadeState, setNextTrackPreloaded);
        return;
      }

      if (action === 'cancel-crossfade-and-stop') {
        cancelCrossfadeModule(setCrossfadeState, setNextTrackPreloaded);
      }

      // action is 'stop' or 'cancel-crossfade-and-stop'
      const state = usePlayerStore.getState();
      const mediaError = target.error;
      const trackName = state.currentTrack?.title || state.currentTrack?.file_path || 'Unknown track';
      log.error('Playback error for "%s":', trackName, mediaError);

      showError('Playback error', {
        description: `${trackName}: ${mediaError?.message || 'Failed to play track'}`
      });

      setIsPlaying(false);
      setIsLoadingAudio(false);
    };

    const handlePlaying = (e: Event) => {
      const target = e.target as HTMLAudioElement;
      if (target === getCurrentElement()) {
        setIsLoadingAudio(false);
      }
    };

    elements.forEach(el => {
      el.addEventListener('ended', handleEnded);
      el.addEventListener('error', handleError);
      el.addEventListener('playing', handlePlaying);
    });

    return () => {
      elements.forEach(el => {
        el.removeEventListener('ended', handleEnded);
        el.removeEventListener('error', handleError);
        el.removeEventListener('playing', handlePlaying);
      });
    };
  }, [isInitialized, playNext, setIsPlaying, setIsLoadingAudio]);

  // --------------------------------------------------------------------------
  // Update Media Session
  // --------------------------------------------------------------------------
  const updateMediaSession = useCallback(() => {
    if (!('mediaSession' in navigator) || !currentTrack) return;

    try {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: currentTrack.title || 'Unknown',
        artist: currentTrack.artist || 'Unknown',
        album: currentTrack.album || 'Unknown',
        artwork: currentTrack.id ? [{ src: tracksApi.getArtworkUrl(currentTrack.id), sizes: '512x512', type: 'image/jpeg' }] : [],
      });

      navigator.mediaSession.setActionHandler('play', () => setIsPlaying(true));
      navigator.mediaSession.setActionHandler('pause', () => setIsPlaying(false));
      navigator.mediaSession.setActionHandler('nexttrack', () => playNext());
      navigator.mediaSession.setActionHandler('previoustrack', () => usePlayerStore.getState().playPrevious());
      navigator.mediaSession.setActionHandler('seekto', (details) => {
        if (details.seekTime !== undefined) {
          seek(details.seekTime);
        }
      });
    } catch (e) {
      log.warn('Failed to update media session', e);
    }
  }, [currentTrack, setIsPlaying, playNext]);

  // --------------------------------------------------------------------------
  // Seek
  // --------------------------------------------------------------------------
  const seek = useCallback((time: number) => {
    const el = getCurrentElement();
    if (!el) return;

    if (getCrossfadeContext()?.isActive) {
      const effectiveCrossfade = getEffectiveCrossfadeDuration(
        crossfadeEnabled, crossfadeDuration, useDirectPlayback, MOBILE_TRANSITION_OVERLAP,
      );
      if (el.duration - time > effectiveCrossfade + 1) cancelCrossfade();
    }

    if (!Number.isFinite(time)) return;

    try {
      el.currentTime = time;
      setCurrentTime(time);
    } catch (e) {
      log.error('Seek failed', e);
    }
  }, [setCurrentTime, crossfadeEnabled, crossfadeDuration, cancelCrossfade]);

  // --------------------------------------------------------------------------
  // Toggle play/pause
  // --------------------------------------------------------------------------
  const togglePlayPause = useCallback(() => {
    setIsPlaying(!isPlaying);
  }, [isPlaying, setIsPlaying]);

  // --------------------------------------------------------------------------
  // Effect: Update Media Session when track changes
  // --------------------------------------------------------------------------
  useEffect(() => {
    updateMediaSession();
  }, [updateMediaSession]);

  // --------------------------------------------------------------------------
  // Effect: Handle Play/Pause State
  // --------------------------------------------------------------------------
  useEffect(() => {
    if (!isInitialized) return;

    const el = getCurrentElement();
    if (!el) return;

    if (isPlaying) {
      const ctx = getGlobalAudioContext();
      if (ctx && ctx.state === 'suspended') {
        ctx.resume().catch(e => log.error('Failed to resume audio context', e));
      }

      const playPromise = el.play();
      if (playPromise !== undefined) {
        playPromise.catch(e => {
          if (e.name === 'NotAllowedError') {
            log.warn('Auto-play blocked');
            setIsPlaying(false);
          } else if (e.name !== 'AbortError') {
            log.error('Play failed', e);
          }
        });
      }
    } else {
      el.pause();
    }
  }, [isPlaying, isInitialized, setIsPlaying]);

  // --------------------------------------------------------------------------
  // Effect: Handle Volume Changes
  // --------------------------------------------------------------------------
  useEffect(() => {
    if (!isInitialized) return;

    setCurrentMasterVolume(volume);

    if (useDirectPlayback) {
      if (!getCrossfadeContext()?.isActive) {
        const el = getCurrentElement();
        const nextEl = getNextElement();
        if (el) el.volume = Math.max(0, Math.min(1, volume));
        if (nextEl) nextEl.volume = 0;
      }
    } else {
      const masterGain = getGlobalMasterGain();
      if (masterGain) {
        masterGain.gain.setTargetAtTime(volume, getGlobalAudioContext()?.currentTime || 0, 0.1);
      }
    }
  }, [volume, isInitialized]);

  // --------------------------------------------------------------------------
  // Effect: Load track when currentTrack changes (Manual navigation)
  // --------------------------------------------------------------------------
  useEffect(() => {
    if (!isInitialized || !currentTrack) return;

    if (getCrossfadeContext()?.isActive) return;

    const el = getCurrentElement();
    if (!el) return;

    if (el.getAttribute('data-track-id') === currentTrack.id) {
      setIsLoadingAudio(false);
      return;
    }

    const loadTrack = async () => {
      try {
        setIsLoadingAudio(true);

        const state = usePlayerStore.getState();
        const currentQueueItem = state.queue[state.queueIndex];
        const externalInfo = currentQueueItem?.externalInfo;

        if (externalInfo && !useAudioSettingsStore.getState().playExternalPreviews) {
          log.info('External previews disabled, auto-advancing');
          setIsLoadingAudio(false);
          playNext();
          return;
        }

        let url: string;
        let isOffline = false;

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
          const trackUrl = await getTrackUrl(currentTrack.id);
          url = trackUrl.url;
          isOffline = trackUrl.isOffline;
        }

        if (usePlayerStore.getState().currentTrack?.id !== currentTrack.id) {
          setIsLoadingAudio(false);
          return;
        }
        if (getCrossfadeContext()?.isActive) {
          setIsLoadingAudio(false);
          return;
        }

        const oldOfflineUrl = getCurrentOfflineUrl();
        if (oldOfflineUrl) revokeOfflineTrackUrl(oldOfflineUrl);
        setCurrentOfflineUrl(isOffline ? url : null);

        el.src = url;
        el.setAttribute('data-track-id', currentTrack.id);
        el.load();
        setLoadedTrackId(currentTrack.id);

        if (isPlaying) {
          const p = el.play();
          if (p) p.then(() => setIsLoadingAudio(false)).catch(e => {
            if (e.name !== 'AbortError') log.error('Play failed after load', e);
          });
        }
      } catch (e) {
        log.error('Failed to load track', e);
        setIsLoadingAudio(false);
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
  // Animation/Update Loop
  // --------------------------------------------------------------------------
  useEffect(() => {
    let animationFrameId: number;
    let lastTimeUpdate = 0;

    const loop = () => {
      animationFrameId = requestAnimationFrame(loop);

      const now = performance.now();
      if (now - lastTimeUpdate < 250) return; // ~4Hz — sufficient for seek bar UI
      lastTimeUpdate = now;

      const el = getCurrentElement();
      if (el) {
        if (!el.paused) {
          setCurrentTime(el.currentTime);
        }

        if (Number.isFinite(el.duration) && el.duration > 0) {
          setDuration(el.duration);
        }

        if (!getCrossfadeContext()?.isActive && !getQueueTransition() && currentTrack) {
          const timeRemaining = el.duration - el.currentTime;
          const trigger = getCrossfadeTrigger(
            timeRemaining, crossfadeEnabled, crossfadeDuration, useDirectPlayback, MOBILE_TRANSITION_OVERLAP,
          );

          if (trigger === 'preload') {
            const nextTrackForPreload = usePlayerStore.getState().getNextTrack();
            if (nextTrackForPreload && nextTrackForPreload.id !== getPreloadingTrackId()) {
              preloadNextTrackModule(nextTrackForPreload.id);
            }
          }

          if (trigger === 'crossfade') {
            const nextTrack = usePlayerStore.getState().getNextTrack();
            if (nextTrack) {
              const nextEl = getNextElement();
              if (nextEl && nextEl.readyState > 0) {
                const effectiveDuration = getEffectiveCrossfadeDuration(
                  crossfadeEnabled, crossfadeDuration, useDirectPlayback, MOBILE_TRANSITION_OVERLAP,
                );
                setQueueTransition(true);
                executeCrossfade(effectiveDuration, nextTrack);
                setTimeout(() => { setQueueTransition(false); }, 1000);
              }
            }
          }
        }
      }
    };

    if (isPlaying) {
      loop();
    }

    return () => {
      if (animationFrameId) cancelAnimationFrame(animationFrameId);
    };
  }, [isPlaying, setCurrentTime, setDuration, executeCrossfade, crossfadeEnabled, crossfadeDuration, currentTrack]);

  return {
    executeCrossfade,
    togglePlayPause,
    seek,
  };
}
