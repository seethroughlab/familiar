/**
 * Mobile jump-fetch logic for alphabet bar navigation.
 *
 * When a letter is tapped on mobile, fetches just that page and renders from
 * there instead of loading all pages from 1 to N. Supports bidirectional
 * pagination (load more / load previous) and scroll position maintenance.
 */
import { useState, useCallback, useEffect, useLayoutEffect, useRef } from 'react';
import type { Track } from '../../../../types';
import { createLogger } from '../../../../utils/logger';

const log = createLogger('useMobileJumpFetch');

export interface MobileJumpState {
  letter: string;
  tracks: Track[];
  nextPage: number;
  hasMore: boolean;
  isLoading: boolean;
  prevPage: number;
  hasPrevious: boolean;
  isLoadingPrev: boolean;
}

interface UseMobileJumpFetchParams {
  letterIndex: Record<string, number> | null | undefined;
  pageSize: number;
  fetchTracksPage: (page: number) => Promise<{ items: Track[]; total: number; page: number }>;
  setActiveLetter: (letter: string) => void;
  /** Filter/sort dependencies that should reset the jump state */
  resetDeps: readonly unknown[];
}

interface UseMobileJumpFetchResult {
  mobileJump: MobileJumpState | null;
  prevSentinelReady: boolean;
  handleMobileJumpToLetter: (letter: string) => Promise<void>;
  handleMobileJumpLoadMore: () => Promise<void>;
  handleMobileJumpLoadPrevious: () => Promise<void>;
}

export function useMobileJumpFetch({
  letterIndex,
  pageSize,
  fetchTracksPage,
  setActiveLetter,
  resetDeps,
}: UseMobileJumpFetchParams): UseMobileJumpFetchResult {
  const [mobileJump, setMobileJump] = useState<MobileJumpState | null>(null);
  const [prevSentinelReady, setPrevSentinelReady] = useState(false);
  const prevLoadScrollRef = useRef<number | null>(null);

  const handleMobileJumpToLetter = useCallback(async (letter: string) => {
    if (!letterIndex || !(letter in letterIndex)) return;

    const targetIndex = letterIndex[letter];
    const targetPage = Math.floor(targetIndex / pageSize) + 1;

    setActiveLetter(letter);
    setPrevSentinelReady(false);
    setMobileJump(prev => ({
      letter,
      tracks: prev?.tracks ?? [],
      nextPage: targetPage + 1,
      hasMore: true,
      isLoading: true,
      prevPage: targetPage - 1,
      hasPrevious: targetPage > 1,
      isLoadingPrev: false,
    }));

    try {
      const result = await fetchTracksPage(targetPage);

      const totalPages = Math.ceil(result.total / pageSize);
      setMobileJump({
        letter,
        tracks: result.items,
        nextPage: targetPage + 1,
        hasMore: targetPage < totalPages,
        isLoading: false,
        prevPage: targetPage - 1,
        hasPrevious: targetPage > 1,
        isLoadingPrev: false,
      });

      // Scroll mobile view to top
      window.scrollTo({ top: 0 });
    } catch (err) {
      log.error('Failed to jump to letter:', err);
      setMobileJump(null);
    }
  }, [letterIndex, pageSize, fetchTracksPage, setActiveLetter]);

  const handleMobileJumpLoadMore = useCallback(async () => {
    if (!mobileJump || mobileJump.isLoading || !mobileJump.hasMore) return;

    setMobileJump(prev => prev ? { ...prev, isLoading: true } : null);

    try {
      const result = await fetchTracksPage(mobileJump.nextPage);

      const totalPages = Math.ceil(result.total / pageSize);
      setMobileJump(prev => prev ? {
        ...prev,
        tracks: [...prev.tracks, ...result.items],
        nextPage: prev.nextPage + 1,
        hasMore: prev.nextPage < totalPages,
        isLoading: false,
      } : null);
    } catch (err) {
      log.error('Failed to load more jump tracks:', err);
      setMobileJump(prev => prev ? { ...prev, isLoading: false } : null);
    }
  }, [mobileJump, pageSize, fetchTracksPage]);

  const handleMobileJumpLoadPrevious = useCallback(async () => {
    if (!mobileJump || mobileJump.isLoadingPrev || !mobileJump.hasPrevious) return;

    setMobileJump(prev => prev ? { ...prev, isLoadingPrev: true } : null);

    // Save scroll height before prepending so we can maintain position
    prevLoadScrollRef.current = document.documentElement.scrollHeight;

    try {
      const result = await fetchTracksPage(mobileJump.prevPage);

      setMobileJump(prev => prev ? {
        ...prev,
        tracks: [...result.items, ...prev.tracks],
        prevPage: prev.prevPage - 1,
        hasPrevious: prev.prevPage > 1,
        isLoadingPrev: false,
      } : null);
    } catch (err) {
      log.error('Failed to load previous jump tracks:', err);
      setMobileJump(prev => prev ? { ...prev, isLoadingPrev: false } : null);
    }
  }, [mobileJump, fetchTracksPage]);

  // After prepending tracks, adjust scroll position so user doesn't jump
  useLayoutEffect(() => {
    if (prevLoadScrollRef.current !== null) {
      const heightAfter = document.documentElement.scrollHeight;
      const diff = heightAfter - prevLoadScrollRef.current;
      if (diff > 0) window.scrollBy(0, diff);
      prevLoadScrollRef.current = null;
    }
  });

  // Arm the top sentinel only after user scrolls down past threshold (avoids
  // immediate trigger right after a jump scrolls to top)
  useEffect(() => {
    if (!mobileJump?.hasPrevious || prevSentinelReady) return;

    const handleScroll = () => {
      if (window.scrollY > 200) {
        setPrevSentinelReady(true);
      }
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, [mobileJump?.hasPrevious, prevSentinelReady]);

  // Reset mobileJump when filters/sort change
  useEffect(() => {
    setMobileJump(null);
    setPrevSentinelReady(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, resetDeps);

  return {
    mobileJump,
    prevSentinelReady,
    handleMobileJumpToLetter,
    handleMobileJumpLoadMore,
    handleMobileJumpLoadPrevious,
  };
}
