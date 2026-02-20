/**
 * Hook for alphabet bar state and functionality.
 *
 * Manages letter index fetching, visibility logic, and jump-to-letter functionality.
 */
import { useMemo, useCallback, useState, useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { libraryApi } from '../../../api';

interface UseAlphabetBarOptions {
  entityType: 'tracks' | 'artists' | 'albums';
  sortField: string;
  filters: {
    search?: string;
    artist?: string;
    album?: string;
  };
  total: number;
  pageSize: number;
  fetchNextPage: () => Promise<unknown>;
  hasNextPage: boolean;
  loadedItemCount: number;
  /**
   * Optional callback for virtualized lists.
   * When provided, uses the virtualizer's scrollToIndex instead of DOM-based scrolling.
   * This allows jumping to any index, even if that item hasn't been loaded yet.
   */
  scrollToIndex?: (index: number) => void;
}

interface UseAlphabetBarResult {
  letterIndex: Record<string, number> | undefined;
  activeLetter: string | undefined;
  isVisible: boolean;
  isLoading: boolean;
  isJumping: boolean;
  jumpToLetter: (letter: string) => void;
  setActiveLetter: (letter: string | undefined) => void;
}

// Minimum items before showing alphabet bar
const MIN_ITEMS_THRESHOLD = 100;

// Safety cap: don't preload more than this many items for a single jump
const MAX_PRELOAD_ITEMS = 2000;

// Sort fields that support alphabetic navigation
const ALPHABETIC_SORT_FIELDS = ['artist', 'album', 'title', 'name'];

export function useAlphabetBar({
  entityType,
  sortField,
  filters,
  total,
  pageSize: _pageSize,
  fetchNextPage,
  hasNextPage,
  loadedItemCount,
  scrollToIndex,
}: UseAlphabetBarOptions): UseAlphabetBarResult {
  const [activeLetter, setActiveLetter] = useState<string | undefined>();
  const [pendingScrollIndex, setPendingScrollIndex] = useState<number | null>(null);
  const loadedItemCountRef = useRef(loadedItemCount);

  // Keep ref updated
  useEffect(() => {
    loadedItemCountRef.current = loadedItemCount;
  }, [loadedItemCount]);

  // Determine if the bar should be visible
  const isVisible = useMemo(() => {
    // Need enough items to justify alphabet nav
    if (total < MIN_ITEMS_THRESHOLD) return false;

    // Only show for alphabetic sort fields
    if (!ALPHABETIC_SORT_FIELDS.includes(sortField)) return false;

    // Don't show when viewing a single album (already filtered down)
    if (filters.album) return false;

    return true;
  }, [total, sortField, filters.album]);

  // Fetch letter index from API
  const { data: letterIndexData, isLoading } = useQuery({
    queryKey: ['letter-index', entityType, sortField, filters.search, filters.artist, filters.album],
    queryFn: () =>
      libraryApi.getLetterIndex({
        entity_type: entityType,
        sort_field: sortField,
        search: filters.search,
        artist: filters.artist,
        album: filters.album,
      }),
    enabled: isVisible,
    staleTime: 30000, // Cache for 30 seconds
  });

  const letterIndex = letterIndexData?.letters;

  // Scroll to element by index, with retry logic
  const scrollToElement = useCallback((targetIdx: number) => {
    const tryScroll = (attempts = 0): boolean => {
      const container = document.querySelector('[data-alphabet-scroll-container]');
      if (!container) return false;

      const items = container.querySelectorAll('[data-list-index]');
      const targetItem = Array.from(items).find(
        (el) => el.getAttribute('data-list-index') === String(targetIdx)
      );

      if (targetItem) {
        targetItem.scrollIntoView({ behavior: 'instant', block: 'start' });
        return true;
      }

      // Retry a few times with increasing delay
      if (attempts < 5) {
        setTimeout(() => tryScroll(attempts + 1), 100 * (attempts + 1));
      }
      return false;
    };

    tryScroll();
  }, []);

  // Effect to handle pending scroll after items are loaded
  useEffect(() => {
    if (pendingScrollIndex === null) return;

    // Check if we have enough items loaded
    if (loadedItemCount > pendingScrollIndex) {
      // Items are loaded, scroll to the element
      // Small delay to let React render
      setTimeout(() => {
        scrollToElement(pendingScrollIndex);
        setPendingScrollIndex(null);
      }, 50);
    }
  }, [loadedItemCount, pendingScrollIndex, scrollToElement]);

  // Jump to a letter - uses virtualizer's scrollToIndex if available, otherwise falls back to DOM-based approach
  const jumpToLetter = useCallback(
    (letter: string) => {
      if (!letterIndex || !(letter in letterIndex)) {
        return;
      }

      const targetIdx = letterIndex[letter];
      if (targetIdx === undefined) return;

      setActiveLetter(letter);

      // If we have a virtualizer scrollToIndex, use it directly
      // The virtualizer can scroll to any index mathematically without needing DOM elements
      if (scrollToIndex) {
        scrollToIndex(targetIdx);
        return;
      }

      // Fallback: DOM-based scrolling for non-virtualized lists
      // Check if we already have enough items loaded
      if (loadedItemCountRef.current > targetIdx) {
        // Already loaded, just scroll
        scrollToElement(targetIdx);
        return;
      }

      // Safety cap: don't try to preload too many items
      if (targetIdx > MAX_PRELOAD_ITEMS) {
        return;
      }

      // Set pending scroll index — the reactive effect below will progressively load pages
      setPendingScrollIndex(targetIdx);
    },
    [letterIndex, scrollToElement, scrollToIndex]
  );

  // Reactive effect to progressively load pages when pendingScrollIndex is set.
  // Unlike the old async while loop, this reads hasNextPage/loadedItemCount from
  // effect deps (always current) rather than stale closure captures.
  useEffect(() => {
    if (pendingScrollIndex === null || scrollToIndex) return;
    if (loadedItemCount > pendingScrollIndex) return;
    if (!hasNextPage) {
      setPendingScrollIndex(null);
      return;
    }
    const timer = setTimeout(() => { fetchNextPage(); }, 50);
    return () => clearTimeout(timer);
  }, [pendingScrollIndex, loadedItemCount, hasNextPage, fetchNextPage, scrollToIndex]);

  // Clear active letter when filters change
  useEffect(() => {
    setActiveLetter(undefined);
    setPendingScrollIndex(null);
  }, [filters.search, filters.artist, filters.album, sortField]);

  return {
    letterIndex,
    activeLetter,
    isVisible,
    isLoading,
    isJumping: pendingScrollIndex !== null,
    jumpToLetter,
    setActiveLetter,
  };
}
