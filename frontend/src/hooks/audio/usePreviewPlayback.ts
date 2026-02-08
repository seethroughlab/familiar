import { useEffect, useRef } from 'react';
import { usePlayerStore } from '../../stores/playerStore';
import { getCurrentElement, getCurrentMasterVolume } from './audioGraph';
import { log } from './platform';

// ============================================================================
// Preview Playback Hook (for external tracks with preview URLs)
// ============================================================================

export function usePreviewPlayback(
  isPlaying: boolean,
  volume: number,
  setDuration: (d: number) => void,
  setCurrentTime: (t: number) => void,
  playNext: () => void,
) {
  const previewElementRef = useRef<HTMLAudioElement | null>(null);
  const { isPreviewMode, previewTrack, stopPreview } = usePlayerStore();

  useEffect(() => {
    // Create preview element if needed
    if (!previewElementRef.current) {
      const el = new Audio();
      el.preload = 'auto';
      el.style.display = 'none';
      document.body.appendChild(el);
      previewElementRef.current = el;
    }

    const previewEl = previewElementRef.current;

    if (isPreviewMode && previewTrack?.previewUrl) {
      // Stop main playback
      const currentElement = getCurrentElement();
      if (currentElement) {
        currentElement.pause();
      }

      // Start preview playback
      previewEl.src = previewTrack.previewUrl;
      previewEl.volume = getCurrentMasterVolume();
      previewEl.load();

      const handleCanPlay = () => {
        previewEl.play().catch(err => log.error('Preview play failed:', err));
        setDuration(previewEl.duration || 30); // Previews are typically 30 seconds
        previewEl.removeEventListener('canplay', handleCanPlay);
      };

      const handleEnded = () => {
        // Preview ended - advance to next track
        stopPreview();
        playNext();
      };

      const handleTimeUpdate = () => {
        setCurrentTime(previewEl.currentTime);
      };

      previewEl.addEventListener('canplay', handleCanPlay);
      previewEl.addEventListener('ended', handleEnded);
      previewEl.addEventListener('timeupdate', handleTimeUpdate);

      return () => {
        previewEl.removeEventListener('canplay', handleCanPlay);
        previewEl.removeEventListener('ended', handleEnded);
        previewEl.removeEventListener('timeupdate', handleTimeUpdate);
      };
    } else {
      // Stop preview if it was playing
      previewEl.pause();
      previewEl.src = '';
    }
  }, [isPreviewMode, previewTrack, stopPreview, playNext, setDuration, setCurrentTime]);

  // Handle play/pause for preview mode
  useEffect(() => {
    const previewEl = previewElementRef.current;
    if (!previewEl || !isPreviewMode) return;

    if (isPlaying) {
      previewEl.play().catch(err => log.error('Preview play failed:', err));
    } else {
      previewEl.pause();
    }
  }, [isPlaying, isPreviewMode]);

  // Handle volume changes for preview mode
  useEffect(() => {
    const previewEl = previewElementRef.current;
    if (previewEl && isPreviewMode) {
      previewEl.volume = getCurrentMasterVolume();
    }
  }, [volume, isPreviewMode]);
}
