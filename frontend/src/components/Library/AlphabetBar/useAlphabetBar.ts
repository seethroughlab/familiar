/**
 * Hook for alphabet bar state and functionality.
 *
 * Manages letter index fetching, visibility logic, and jump-to-letter functionality.
 */
import { useMemo, useCallback, useState, useRef, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { libraryApi } from '../../../api/client';

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
  /** Callback to scroll to a specific index in the list */
  scrollToIndex?: (index: number) => void;
}

interface UseAlphabetBarResult {
  letterIndex: Record<string, number> | undefined;
  activeLetter: string | undefined;
  isVisible: boolean;
  isLoading: boolean;
  jumpToLetter: (letter: string) => Promise<void>;
  setActiveLetter: (letter: string | undefined) => void;
  /** The target index after jumping (for parent to handle scroll) */
  targetIndex: number | null;
}

// Minimum items before showing alphabet bar
const MIN_ITEMS_THRESHOLD = 100;

// Sort fields that support alphabetic navigation
const ALPHABETIC_SORT_FIELDS = ['artist', 'album', 'title', 'name'];

export function useAlphabetBar({
  entityType,
  sortField,
  filters,
  total,
  pageSize,
  fetchNextPage,
  hasNextPage,
  loadedItemCount,
  scrollToIndex,
}: UseAlphabetBarOptions): UseAlphabetBarResult {
  const [activeLetter, setActiveLetter] = useState<string | undefined>();
  const [targetIndex, setTargetIndex] = useState<number | null>(null);
  const isJumpingRef = useRef(false);

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

  // Jump to a letter - fetch pages as needed, then scroll to the item
  const jumpToLetter = useCallback(
    async (letter: string) => {
      if (!letterIndex || !(letter in letterIndex) || isJumpingRef.current) {
        return;
      }

      const targetIdx = letterIndex[letter];
      if (targetIdx === undefined) return;

      isJumpingRef.current = true;
      setActiveLetter(letter);
      setTargetIndex(targetIdx);

      try {
        // Calculate how many pages we need to load
        const targetPage = Math.floor(targetIdx / pageSize) + 1;
        const currentlyLoadedPages = Math.ceil(loadedItemCount / pageSize);

        // Fetch pages until we have the target item
        let pagesToFetch = targetPage - currentlyLoadedPages;
        while (pagesToFetch > 0 && hasNextPage) {
          await fetchNextPage();
          pagesToFetch--;
          // Small delay to let state update
          await new Promise((resolve) => setTimeout(resolve, 10));
        }

        // Wait a bit for React to render the new items
        await new Promise((resolve) => setTimeout(resolve, 100));

        // Call the scroll callback if provided
        if (scrollToIndex) {
          scrollToIndex(targetIdx);
        } else {
          // Fallback: try to scroll using DOM query
          // Look for track rows, artist cards, or album cards
          const container = document.querySelector('[data-alphabet-scroll-container]');
          if (container) {
            const items = container.querySelectorAll('[data-list-index]');
            const targetItem = Array.from(items).find(
              (el) => el.getAttribute('data-list-index') === String(targetIdx)
            );
            if (targetItem) {
              targetItem.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
          }
        }
      } finally {
        isJumpingRef.current = false;
      }
    },
    [letterIndex, pageSize, loadedItemCount, hasNextPage, fetchNextPage, scrollToIndex]
  );

  // Clear active letter when filters change
  useEffect(() => {
    setActiveLetter(undefined);
    setTargetIndex(null);
  }, [filters.search, filters.artist, filters.album, sortField]);

  return {
    letterIndex,
    activeLetter,
    isVisible,
    isLoading,
    jumpToLetter,
    setActiveLetter,
    targetIndex,
  };
}
