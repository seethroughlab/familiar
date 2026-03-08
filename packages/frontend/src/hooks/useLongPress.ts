/**
 * Custom hook for detecting long-press (touch-hold) gestures.
 *
 * Used for mobile context menus where right-click isn't available.
 * Cancels if the finger moves too far (to allow scrolling).
 */
import { useCallback, useRef } from 'react';

interface LongPressOptions {
  /** Delay in ms before triggering (default: 500ms) */
  delay?: number;
  /** Movement threshold in px to cancel (default: 10px) */
  threshold?: number;
  /** Enable haptic feedback via navigator.vibrate (default: true) */
  hapticFeedback?: boolean;
}

interface LongPressHandlers {
  onTouchStart: (e: React.TouchEvent) => void;
  onTouchEnd: (e: React.TouchEvent) => void;
  onTouchMove: (e: React.TouchEvent) => void;
  onClickCapture: (e: React.MouseEvent) => void;
}

export function useLongPress(
  onLongPress: (position: { x: number; y: number }) => void,
  options: LongPressOptions = {}
): LongPressHandlers {
  const { delay = 500, threshold = 10, hapticFeedback = true } = options;

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startPositionRef = useRef<{ x: number; y: number } | null>(null);
  const triggeredRef = useRef(false);
  const suppressClickRef = useRef(false);

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const onTouchStart = useCallback(
    (e: React.TouchEvent) => {
      const touch = e.touches[0];
      startPositionRef.current = { x: touch.clientX, y: touch.clientY };
      triggeredRef.current = false;
      suppressClickRef.current = false;

      timerRef.current = setTimeout(() => {
        if (startPositionRef.current) {
          // Trigger haptic feedback if supported
          if (hapticFeedback && navigator.vibrate) {
            navigator.vibrate(50);
          }

          triggeredRef.current = true;
          suppressClickRef.current = true;
          onLongPress(startPositionRef.current);
        }
      }, delay);
    },
    [onLongPress, delay, hapticFeedback]
  );

  const onTouchEnd = useCallback(
    (e: React.TouchEvent) => {
      clearTimer();

      // If long-press was triggered, prevent the subsequent click
      if (triggeredRef.current) {
        e.preventDefault();
      }

      startPositionRef.current = null;
    },
    [clearTimer]
  );

  const onTouchMove = useCallback(
    (e: React.TouchEvent) => {
      if (!startPositionRef.current) return;

      const touch = e.touches[0];
      const deltaX = Math.abs(touch.clientX - startPositionRef.current.x);
      const deltaY = Math.abs(touch.clientY - startPositionRef.current.y);

      // Cancel if finger moved too far (user is scrolling)
      if (deltaX > threshold || deltaY > threshold) {
        clearTimer();
        startPositionRef.current = null;
      }
    },
    [threshold, clearTimer]
  );

  const onClickCapture = useCallback((e: React.MouseEvent) => {
    if (!suppressClickRef.current) {
      return;
    }

    e.preventDefault();
    e.stopPropagation();
    suppressClickRef.current = false;
    triggeredRef.current = false;
  }, []);

  return {
    onTouchStart,
    onTouchEnd,
    onTouchMove,
    onClickCapture,
  };
}
