/**
 * Hook for detecting when an element enters the viewport.
 * Used for infinite scroll - triggers callback when sentinel element is visible.
 */
import { useEffect, useRef, useCallback } from 'react';

interface UseIntersectionObserverOptions {
  /** Callback when element becomes visible */
  onIntersect: () => void;
  /** Whether the observer is enabled */
  enabled?: boolean;
  /** Root margin for earlier triggering (e.g., "100px" to trigger 100px before visible) */
  rootMargin?: string;
  /** Visibility threshold (0-1) */
  threshold?: number;
}

export function useIntersectionObserver({
  onIntersect,
  enabled = true,
  rootMargin = '200px',
  threshold = 0,
}: UseIntersectionObserverOptions) {
  const targetRef = useRef<HTMLDivElement>(null);

  const handleIntersect = useCallback(
    (entries: IntersectionObserverEntry[]) => {
      const [entry] = entries;
      if (entry.isIntersecting && enabled) {
        onIntersect();
      }
    },
    [onIntersect, enabled]
  );

  useEffect(() => {
    const target = targetRef.current;
    if (!target || !enabled) return;

    const observer = new IntersectionObserver(handleIntersect, {
      rootMargin,
      threshold,
    });

    observer.observe(target);

    return () => {
      observer.unobserve(target);
      observer.disconnect();
    };
  }, [handleIntersect, enabled, rootMargin, threshold]);

  return targetRef;
}
