/**
 * Global keyboard shortcuts for the music player.
 */
import { useEffect, useCallback, useRef } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { usePlayerStore } from '../stores/playerStore';
import { getCurrentElement } from './audio/audioGraph';

interface ShortcutHandlers {
  onToggleFullPlayer?: () => void;
  onShowHelp?: () => void;
  onEscape?: () => void;
}

interface ShortcutDefinition {
  key: string;
  description: string;
  modifiers?: ('ctrl' | 'alt' | 'shift' | 'meta')[];
}

export const SHORTCUTS: Record<string, ShortcutDefinition> = {
  playPause: { key: 'Space', description: 'Play / Pause' },
  nextTrack: { key: 'ArrowRight', description: 'Next track' },
  prevTrack: { key: 'ArrowLeft', description: 'Previous track' },
  volumeUp: { key: 'ArrowUp', description: 'Volume up' },
  volumeDown: { key: 'ArrowDown', description: 'Volume down' },
  mute: { key: 'm', description: 'Mute / Unmute' },
  fullPlayer: { key: 'f', description: 'Toggle full player' },
  help: { key: '?', description: 'Show keyboard shortcuts', modifiers: ['shift'] },
  escape: { key: 'Escape', description: 'Close overlay' },
  seekForward: { key: 'l', description: 'Seek forward 10s' },
  seekBackward: { key: 'j', description: 'Seek backward 10s' },
  shuffle: { key: 's', description: 'Toggle shuffle' },
  repeat: { key: 'r', description: 'Cycle repeat mode' },
};

export function useKeyboardShortcuts(handlers: ShortcutHandlers = {}) {
  const { isPlaying, volume, currentTime, duration } = usePlayerStore(
    useShallow((s) => ({ isPlaying: s.isPlaying, volume: s.volume, currentTime: s.currentTime, duration: s.duration }))
  );
  const setIsPlaying = usePlayerStore((s) => s.setIsPlaying);
  const setVolume = usePlayerStore((s) => s.setVolume);
  const playNext = usePlayerStore((s) => s.playNext);
  const playPrevious = usePlayerStore((s) => s.playPrevious);
  const toggleShuffle = usePlayerStore((s) => s.toggleShuffle);
  const toggleRepeat = usePlayerStore((s) => s.toggleRepeat);

  // Store previous volume for mute toggle
  const previousVolumeRef = useRef(volume > 0 ? volume : 1);
  useEffect(() => {
    if (volume > 0) {
      previousVolumeRef.current = volume;
    }
  }, [volume]);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      // Don't handle shortcuts when typing in input fields
      const target = event.target as HTMLElement;
      if (
        target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.isContentEditable
      ) {
        // Allow Escape to blur inputs
        if (event.key === 'Escape') {
          target.blur();
        }
        return;
      }

      // Prevent default for handled keys
      const handled = () => {
        event.preventDefault();
        event.stopPropagation();
      };

      switch (event.key) {
        case ' ': // Space - Play/Pause
          handled();
          setIsPlaying(!isPlaying);
          break;

        case 'ArrowRight': // Next track
          if (!event.shiftKey && !event.ctrlKey && !event.altKey) {
            handled();
            playNext();
          }
          break;

        case 'ArrowLeft': // Previous track
          if (!event.shiftKey && !event.ctrlKey && !event.altKey) {
            handled();
            playPrevious();
          }
          break;

        case 'ArrowUp': // Volume up
          handled();
          setVolume(Math.min(1, volume + 0.1));
          break;

        case 'ArrowDown': // Volume down
          handled();
          setVolume(Math.max(0, volume - 0.1));
          break;

        case 'm': // Mute toggle
        case 'M':
          handled();
          if (volume > 0) {
            setVolume(0);
          } else {
            setVolume(previousVolumeRef.current);
          }
          break;

        case 'f': // Full player toggle
        case 'F':
          if (!event.ctrlKey && !event.metaKey) {
            handled();
            handlers.onToggleFullPlayer?.();
          }
          break;

        case '?': // Help
          handled();
          handlers.onShowHelp?.();
          break;

        case 'Escape': // Close overlays
          handled();
          handlers.onEscape?.();
          break;

        case 'l': // Seek forward 10s
        case 'L':
          handled();
          if (duration > 0) {
            const newTime = Math.min(duration, currentTime + 10);
            const el = getCurrentElement();
            if (el) el.currentTime = newTime;
            usePlayerStore.getState().setCurrentTime(newTime);
          }
          break;

        case 'j': // Seek backward 10s
        case 'J':
          handled();
          if (duration > 0) {
            const newTime = Math.max(0, currentTime - 10);
            const el = getCurrentElement();
            if (el) el.currentTime = newTime;
            usePlayerStore.getState().setCurrentTime(newTime);
          }
          break;

        case 's': // Shuffle toggle
        case 'S':
          if (!event.ctrlKey && !event.metaKey) {
            handled();
            toggleShuffle();
          }
          break;

        case 'r': // Repeat cycle
        case 'R':
          if (!event.ctrlKey && !event.metaKey) {
            handled();
            toggleRepeat();
          }
          break;
      }
    },
    [
      isPlaying,
      setIsPlaying,
      volume,
      setVolume,
      currentTime,
      duration,
      playNext,
      playPrevious,
      toggleShuffle,
      toggleRepeat,
      handlers,
    ]
  );

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);
}

/**
 * Get formatted shortcut key for display.
 */
export function formatShortcutKey(key: string): string {
  const keyMap: Record<string, string> = {
    Space: 'Space',
    ArrowUp: '↑',
    ArrowDown: '↓',
    ArrowLeft: '←',
    ArrowRight: '→',
    Escape: 'Esc',
  };
  return keyMap[key] || key.toUpperCase();
}
