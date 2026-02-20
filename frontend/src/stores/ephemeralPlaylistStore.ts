/**
 * Ephemeral Playlist Store
 *
 * Stores LLM-generated playlists temporarily in browser memory.
 * These playlists are lost on page refresh by design - users must
 * explicitly "Save" to persist them to the database.
 */

import { create } from 'zustand';
import { useQueryClient } from '@tanstack/react-query';
import { playlistsApi } from '../api';

export interface EphemeralTrack {
  id: string;
  title: string;
  artist: string;
  album: string | null;
  duration_seconds: number | null;
}

export interface EphemeralPlaylist {
  id: string; // Local UUID for keying
  name: string;
  generationPrompt: string;
  tracks: EphemeralTrack[];
  trackIds: string[];
  createdAt: Date;
}

interface EphemeralPlaylistState {
  playlists: EphemeralPlaylist[];
}

interface EphemeralPlaylistActions {
  /** Add a new ephemeral playlist and return its local ID */
  addPlaylist: (playlist: Omit<EphemeralPlaylist, 'id' | 'createdAt'>) => string;
  /** Remove an ephemeral playlist by ID */
  removePlaylist: (id: string) => void;
  /** Clear all ephemeral playlists */
  clearAll: () => void;
  /** Save an ephemeral playlist to the database and remove from ephemeral store */
  savePlaylist: (id: string) => Promise<string>;
  /** Get a playlist by ID */
  getPlaylist: (id: string) => EphemeralPlaylist | undefined;
}

export const useEphemeralPlaylistStore = create<EphemeralPlaylistState & EphemeralPlaylistActions>(
  (set, get) => ({
    playlists: [],

    addPlaylist: (playlist) => {
      const id = crypto.randomUUID();
      const newPlaylist: EphemeralPlaylist = {
        ...playlist,
        id,
        createdAt: new Date(),
      };
      set((state) => ({
        playlists: [newPlaylist, ...state.playlists],
      }));
      return id;
    },

    removePlaylist: (id) => {
      set((state) => ({
        playlists: state.playlists.filter((p) => p.id !== id),
      }));
    },

    clearAll: () => {
      set({ playlists: [] });
    },

    savePlaylist: async (id) => {
      const playlist = get().playlists.find((p) => p.id === id);
      if (!playlist) {
        throw new Error('Playlist not found');
      }

      // Create playlist via API
      const saved = await playlistsApi.create({
        name: playlist.name,
        description: playlist.generationPrompt,
        track_ids: playlist.trackIds,
        is_auto_generated: true,
        generation_prompt: playlist.generationPrompt,
      });

      // Remove from ephemeral store
      get().removePlaylist(id);

      return saved.id;
    },

    getPlaylist: (id) => {
      return get().playlists.find((p) => p.id === id);
    },
  })
);

/**
 * Hook to save an ephemeral playlist with automatic query invalidation.
 * Use this in components where you have access to queryClient.
 */
export function useSaveEphemeralPlaylist() {
  const queryClient = useQueryClient();
  const savePlaylist = useEphemeralPlaylistStore((state) => state.savePlaylist);

  return async (id: string) => {
    const savedId = await savePlaylist(id);
    // Invalidate playlists query so the new playlist appears in the list
    queryClient.invalidateQueries({ queryKey: ['playlists'] });
    return savedId;
  };
}
