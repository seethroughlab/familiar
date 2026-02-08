/**
 * usePreviewAudio - Audio preview hook for hovering over tracks/artists.
 *
 * Creates two audio elements for crossfade transitions.
 * Features debouncing, fade in/out, crossfade, and automatic timeout.
 */
import { useRef, useCallback, useEffect } from 'react';
import { tracksApi } from '../api/client';
import { usePlayerStore } from '../stores/playerStore';
import { createLogger } from '../utils/logger';

const log = createLogger('PreviewAudio');

// Configuration
const DEBOUNCE_MS = 400; // Wait before starting preview
const FADE_IN_MS = 200;
const FADE_OUT_MS = 300;
const CROSSFADE_MS = 300; // Crossfade duration when switching tracks
const START_POSITION_S = 5; // Skip intros
const MAX_DURATION_S = 15; // Auto-stop after this

interface AudioChannel {
  audio: HTMLAudioElement;
  fadeInterval: number | null;
  maxDurationTimer: number | null;
  trackId: string | null;
}

export function usePreviewAudio() {
  // Get volume from player store
  const volume = usePlayerStore((state) => state.volume);

  // Two audio channels for crossfade
  const channelARef = useRef<AudioChannel | null>(null);
  const channelBRef = useRef<AudioChannel | null>(null);
  const activeChannelRef = useRef<'A' | 'B' | null>(null);
  const debounceTimerRef = useRef<number | null>(null);

  // Create an audio channel
  const createChannel = useCallback((): AudioChannel => {
    const audio = new Audio();
    audio.crossOrigin = 'anonymous';
    audio.volume = 0;
    audio.preload = 'auto';

    // Set start position when audio is ready
    const handleCanPlay = () => {
      if (audio.currentTime < START_POSITION_S && audio.duration > START_POSITION_S + 5) {
        audio.currentTime = START_POSITION_S;
      }
    };
    audio.addEventListener('canplay', handleCanPlay);

    return {
      audio,
      fadeInterval: null,
      maxDurationTimer: null,
      trackId: null,
    };
  }, []);

  // Initialize audio channels on mount
  useEffect(() => {
    channelARef.current = createChannel();
    channelBRef.current = createChannel();

    return () => {
      // Cleanup
      [channelARef.current, channelBRef.current].forEach((channel) => {
        if (channel) {
          channel.audio.pause();
          channel.audio.src = '';
          if (channel.fadeInterval) clearInterval(channel.fadeInterval);
          if (channel.maxDurationTimer) clearTimeout(channel.maxDurationTimer);
        }
      });
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    };
  }, [createChannel]);

  // Sync volume changes to active channel in real-time
  useEffect(() => {
    const activeChannel =
      activeChannelRef.current === 'A'
        ? channelARef.current
        : activeChannelRef.current === 'B'
          ? channelBRef.current
          : null;

    if (activeChannel && !activeChannel.audio.paused && !activeChannel.fadeInterval) {
      // Only update if not currently fading (to avoid interfering with fade animations)
      activeChannel.audio.volume = volume;
    }
  }, [volume]);

  // Fade a channel's volume
  const fadeChannel = useCallback(
    (
      channel: AudioChannel,
      targetVolume: number,
      durationMs: number,
      onComplete?: () => void
    ) => {
      if (channel.fadeInterval) {
        clearInterval(channel.fadeInterval);
        channel.fadeInterval = null;
      }

      const startVolume = channel.audio.volume;
      const volumeDiff = targetVolume - startVolume;

      if (Math.abs(volumeDiff) < 0.01) {
        channel.audio.volume = targetVolume;
        onComplete?.();
        return;
      }

      const steps = Math.ceil(durationMs / 16); // ~60fps
      const volumeStep = volumeDiff / steps;
      let currentStep = 0;

      channel.fadeInterval = window.setInterval(() => {
        currentStep++;
        const newVolume = Math.max(0, Math.min(1, startVolume + volumeStep * currentStep));
        channel.audio.volume = newVolume;

        if (currentStep >= steps) {
          if (channel.fadeInterval) {
            clearInterval(channel.fadeInterval);
            channel.fadeInterval = null;
          }
          channel.audio.volume = targetVolume;
          onComplete?.();
        }
      }, 16);
    },
    []
  );

  // Stop a channel with fade out
  const stopChannel = useCallback(
    (channel: AudioChannel, fadeDuration: number = FADE_OUT_MS) => {
      if (channel.maxDurationTimer) {
        clearTimeout(channel.maxDurationTimer);
        channel.maxDurationTimer = null;
      }

      if (channel.audio.paused) {
        channel.trackId = null;
        return;
      }

      fadeChannel(channel, 0, fadeDuration, () => {
        channel.audio.pause();
        channel.trackId = null;
      });
    },
    [fadeChannel]
  );

  // Get the inactive channel
  const getInactiveChannel = useCallback((): AudioChannel | null => {
    if (activeChannelRef.current === 'A') {
      return channelBRef.current;
    } else if (activeChannelRef.current === 'B') {
      return channelARef.current;
    }
    // Neither is active, prefer A
    return channelARef.current;
  }, []);

  // Start preview with debounce and crossfade
  const startPreview = useCallback(
    (trackId: string) => {
      // Clear any pending debounce
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }

      // Check if same track is already playing on active channel
      const activeChannel =
        activeChannelRef.current === 'A'
          ? channelARef.current
          : activeChannelRef.current === 'B'
            ? channelBRef.current
            : null;

      if (
        activeChannel &&
        activeChannel.trackId === trackId &&
        !activeChannel.audio.paused
      ) {
        return; // Same track already playing
      }

      // Debounce the start
      debounceTimerRef.current = window.setTimeout(() => {
        const inactiveChannel = getInactiveChannel();
        if (!inactiveChannel) return;

        // Determine new active channel
        const newActiveChannel: 'A' | 'B' =
          inactiveChannel === channelARef.current ? 'A' : 'B';

        // Crossfade: fade out current active channel
        const currentActive =
          activeChannelRef.current === 'A'
            ? channelARef.current
            : activeChannelRef.current === 'B'
              ? channelBRef.current
              : null;

        if (currentActive && !currentActive.audio.paused) {
          stopChannel(currentActive, CROSSFADE_MS);
        }

        // Setup and play on inactive channel
        inactiveChannel.trackId = trackId;
        inactiveChannel.audio.volume = 0;
        inactiveChannel.audio.src = tracksApi.getStreamUrl(trackId);

        inactiveChannel.audio
          .play()
          .then(() => {
            // Fade in to player volume
            fadeChannel(inactiveChannel, volume, FADE_IN_MS);
            activeChannelRef.current = newActiveChannel;

            // Set max duration timer
            if (inactiveChannel.maxDurationTimer) {
              clearTimeout(inactiveChannel.maxDurationTimer);
            }
            inactiveChannel.maxDurationTimer = window.setTimeout(() => {
              fadeChannel(inactiveChannel, 0, FADE_OUT_MS, () => {
                inactiveChannel.audio.pause();
                if (activeChannelRef.current === newActiveChannel) {
                  activeChannelRef.current = null;
                }
              });
            }, MAX_DURATION_S * 1000);
          })
          .catch((err) => {
            // Autoplay blocked or other error - silently ignore
            log.debug('Preview play failed:', err.message);
          });
      }, DEBOUNCE_MS);
    },
    [fadeChannel, stopChannel, getInactiveChannel, volume]
  );

  // Stop all previews with fade out
  const stopPreview = useCallback(() => {
    // Clear debounce timer if preview hasn't started yet
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
      debounceTimerRef.current = null;
    }

    // Stop both channels
    if (channelARef.current) {
      stopChannel(channelARef.current);
    }
    if (channelBRef.current) {
      stopChannel(channelBRef.current);
    }
    activeChannelRef.current = null;
  }, [stopChannel]);

  return { startPreview, stopPreview };
}
