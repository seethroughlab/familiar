/**
 * useAmbientSession — thin React hook wrapper for AmbientCoordinator.
 *
 * Attaches coordinator to engine on mount, subscribes to ambientStore
 * for reactive UI, exposes actions. Mounted only in AmbientScreen.
 */

import { useEffect, useCallback } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { useAmbientStore } from '../../stores/ambientStore';
import { ambientCoordinator } from './AmbientCoordinator';
import type { AmbientControls } from './types';

export function useAmbientSession() {
  // Attach/detach coordinator on mount
  useEffect(() => {
    ambientCoordinator.attach();
    return () => ambientCoordinator.detach();
  }, []);

  // Subscribe to store
  const {
    status,
    controls,
    currentSnippet,
    snippetCurrentTime,
    upcomingSnippets,
    history,
    seedDescriptor,
    poolSize,
    poolCollapsed,
    error,
  } = useAmbientStore(
    useShallow((s) => ({
      status: s.status,
      controls: s.controls,
      currentSnippet: s.currentSnippet,
      snippetCurrentTime: s.snippetCurrentTime,
      upcomingSnippets: s.upcomingSnippets,
      history: s.history,
      seedDescriptor: s.seedDescriptor,
      poolSize: s.poolSize,
      poolCollapsed: s.poolCollapsed,
      error: s.error,
    })),
  );

  const updateControls = useAmbientStore((s) => s.updateControls);

  // Actions
  const startSession = useCallback(async (options: {
    trackId?: string;
    artist?: string;
    surpriseMe?: boolean;
  }) => {
    await ambientCoordinator.startSession(options);
  }, []);

  const stopSession = useCallback(async () => {
    await ambientCoordinator.stopSession();
  }, []);

  const pauseSession = useCallback(() => {
    ambientCoordinator.pauseSession();
  }, []);

  const resumeSession = useCallback(async () => {
    await ambientCoordinator.resumeSession();
  }, []);

  const skipToNext = useCallback(async () => {
    await ambientCoordinator.skipToNext();
  }, []);

  const skipToPrevious = useCallback(async () => {
    await ambientCoordinator.skipToPrevious();
  }, []);

  const handleControlChange = useCallback((updates: Partial<AmbientControls>) => {
    updateControls(updates);
  }, [updateControls]);

  return {
    // State
    status,
    controls,
    currentSnippet,
    snippetCurrentTime,
    upcomingSnippets,
    history,
    seedDescriptor,
    poolSize,
    poolCollapsed,
    error,

    // Actions
    startSession,
    stopSession,
    pauseSession,
    resumeSession,
    skipToNext,
    skipToPrevious,
    updateControls: handleControlChange,
  };
}
