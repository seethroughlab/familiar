/**
 * Custom hook that centralizes all window.addEventListener calls for the main App.
 *
 * Handles:
 * - Triple-tap recovery (mobile: closes all overlays)
 * - navigate-to-settings event
 * - show-playlist event (LLM creates a playlist)
 * - show-ephemeral-playlist event
 * - trigger-chat event (context menu "Make Playlist From This Track")
 *
 * Returns state (selectedPlaylistId, pendingChatMessage) + setters needed by App.tsx.
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { logger } from '../utils/logger';
import type { AppTab } from '../utils/urlParams';

interface OverlaySetters {
  setShowFullPlayer: (v: boolean) => void;
  setShowMobileChat: (v: boolean) => void;
  setShowChatPanel: (v: boolean | ((prev: boolean) => boolean)) => void;
  setShowShortcutsHelp: (v: boolean) => void;
  setRightPanelTab: (tab: AppTab) => void;
}

interface AppEventListenersResult {
  selectedPlaylistId: string | null;
  setSelectedPlaylistId: (id: string | null) => void;
  pendingChatMessage: string | null;
  setPendingChatMessage: (msg: string | null) => void;
}

export function useAppEventListeners(setters: OverlaySetters): AppEventListenersResult {
  const {
    setShowFullPlayer,
    setShowMobileChat,
    setShowChatPanel,
    setShowShortcutsHelp,
    setRightPanelTab,
  } = setters;

  const [selectedPlaylistId, setSelectedPlaylistId] = useState<string | null>(null);
  const [pendingChatMessage, setPendingChatMessage] = useState<string | null>(null);

  // Triple-tap recovery mechanism for mobile (closes all overlays)
  const tapCountRef = useRef(0);
  const lastTapTimeRef = useRef(0);
  useEffect(() => {
    const handleTripleTap = () => {
      const now = Date.now();
      if (now - lastTapTimeRef.current < 500) {
        tapCountRef.current++;
        if (tapCountRef.current >= 3) {
          // Triple tap detected - close all overlays
          logger.info('[AppContent] Triple-tap recovery triggered');
          setShowFullPlayer(false);
          setShowMobileChat(false);
          setShowChatPanel(false);
          setShowShortcutsHelp(false);
          tapCountRef.current = 0;
        }
      } else {
        tapCountRef.current = 1;
      }
      lastTapTimeRef.current = now;
    };

    // Only add on touch devices
    if ('ontouchstart' in window) {
      document.addEventListener('touchstart', handleTripleTap);
      return () => document.removeEventListener('touchstart', handleTripleTap);
    }
  }, [setShowFullPlayer, setShowMobileChat, setShowChatPanel, setShowShortcutsHelp]);

  // Listen for navigate-to-settings event from HealthIndicator
  useEffect(() => {
    const handleNavigateToSettings = () => {
      setRightPanelTab('settings');
    };
    window.addEventListener('navigate-to-settings', handleNavigateToSettings);
    return () => window.removeEventListener('navigate-to-settings', handleNavigateToSettings);
  }, [setRightPanelTab]);

  // Listen for show-playlist event from ChatPanel when LLM creates a playlist
  useEffect(() => {
    const handleShowPlaylist = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail?.playlistId) {
        setSelectedPlaylistId(detail.playlistId);
        setRightPanelTab('playlists');
      }
    };
    window.addEventListener('show-playlist', handleShowPlaylist);
    return () => window.removeEventListener('show-playlist', handleShowPlaylist);
  }, [setRightPanelTab]);

  // Listen for show-ephemeral-playlist event when LLM creates an ephemeral playlist
  useEffect(() => {
    const handleShowEphemeralPlaylist = () => {
      // Just switch to playlists tab - the unsaved section will show automatically
      setRightPanelTab('playlists');
    };
    window.addEventListener('show-ephemeral-playlist', handleShowEphemeralPlaylist);
    return () => window.removeEventListener('show-ephemeral-playlist', handleShowEphemeralPlaylist);
  }, [setRightPanelTab]);

  // Listen for trigger-chat event from context menus (e.g., "Make Playlist From This Track")
  useEffect(() => {
    const handleTriggerChat = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail?.message) {
        setPendingChatMessage(detail.message);
        // Open the appropriate chat panel based on viewport
        if (window.innerWidth >= 768) {
          setShowChatPanel(true);
        } else {
          setShowMobileChat(true);
        }
      }
    };
    window.addEventListener('trigger-chat', handleTriggerChat);
    return () => window.removeEventListener('trigger-chat', handleTriggerChat);
  }, [setShowChatPanel, setShowMobileChat]);

  return {
    selectedPlaylistId,
    setSelectedPlaylistId,
    pendingChatMessage,
    setPendingChatMessage: useCallback((msg: string | null) => setPendingChatMessage(msg), []),
  };
}
