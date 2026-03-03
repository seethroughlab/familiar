/**
 * Client-side alphabet bar hook for playlist-type views.
 *
 * Unlike useAlphabetBar (which fetches from the backend API for paginated library browsers),
 * this hook computes the letter index directly from the in-memory sorted items array.
 * Used by PlaylistTrackList which already has all tracks loaded.
 */
import { useMemo, useCallback, useState } from 'react';
import { getColumnDef } from '../Library/columnDefinitions';
import type { Track } from '../../types';

// Minimum items before showing alphabet bar (matches library browser threshold)
const MIN_ITEMS_THRESHOLD = 30;

// Sort fields that support alphabetic navigation
const ALPHABETIC_SORT_FIELDS = ['artist', 'album', 'title', 'name'];

interface UseClientAlphabetBarOptions<T> {
  sortedItems: T[];
  getTrack: (item: T) => Track | null;
  sortBy: string | null;
}

interface UseClientAlphabetBarResult {
  letterIndex: Record<string, number> | undefined;
  activeLetter: string | undefined;
  isVisible: boolean;
  jumpToLetter: (letter: string) => void;
}

/** Get the sort field value from a track (mirrors useSortedTracks logic). */
function getSortValue(track: Track, sortBy: string): string | null {
  if (sortBy === 'title') return track.title ?? null;
  const colDef = getColumnDef(sortBy);
  if (!colDef) return null;
  const val = colDef.getValue(track);
  return val != null ? String(val) : null;
}

/** Map a character to its alphabet bar letter (A-Z or #). */
function charToLetter(ch: string): string {
  const upper = ch.toUpperCase();
  if (upper >= 'A' && upper <= 'Z') return upper;
  return '#';
}

export function useClientAlphabetBar<T>({
  sortedItems,
  getTrack,
  sortBy,
}: UseClientAlphabetBarOptions<T>): UseClientAlphabetBarResult {
  const [activeLetter, setActiveLetter] = useState<string | undefined>();

  const isVisible = useMemo(() => {
    if (sortedItems.length < MIN_ITEMS_THRESHOLD) return false;
    if (!sortBy || !ALPHABETIC_SORT_FIELDS.includes(sortBy)) return false;
    return true;
  }, [sortedItems.length, sortBy]);

  // Compute letter → first item index from the sorted array
  const letterIndex = useMemo(() => {
    if (!isVisible || !sortBy) return undefined;

    const index: Record<string, number> = {};
    for (let i = 0; i < sortedItems.length; i++) {
      const track = getTrack(sortedItems[i]);
      if (!track) continue;

      const val = getSortValue(track, sortBy);
      if (!val) continue;

      const letter = charToLetter(val[0]);
      if (!(letter in index)) {
        index[letter] = i;
      }
    }
    return index;
  }, [isVisible, sortBy, sortedItems, getTrack]);

  const jumpToLetter = useCallback((letter: string) => {
    if (!letterIndex || !(letter in letterIndex)) return;

    const targetIdx = letterIndex[letter];
    setActiveLetter(letter);

    const el = document.querySelector(`[data-list-index="${targetIdx}"]`);
    if (el) {
      el.scrollIntoView({ behavior: 'instant', block: 'start' });
    }
  }, [letterIndex]);

  return {
    letterIndex,
    activeLetter,
    isVisible,
    jumpToLetter,
  };
}
