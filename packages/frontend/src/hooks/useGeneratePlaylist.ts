import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';

import { playlistsApi, type GeneratePlaylistSeed } from '../api/playlists';
import { queryKeys } from '../api/queryKeys';
import { showError, showSuccess } from '../stores/toastStore';

/**
 * "Make a playlist", for every affordance that offers it (ADR-0048).
 *
 * **One hook rather than the call inlined at each site**, because there are *seven* of them —
 * `ArtistDetail`, `AlbumGrid`, `FullPlayer`, `VibeMap`, `QueueView`, `PlayerBar` and
 * `useTrackContextMenu`, the last shared by four more components. They previously each composed
 * their own English sentence, and the sentences had already drifted apart in wording. Seven copies
 * of "post, toast, invalidate, navigate" would drift the same way, and the drift would be invisible
 * because each one would still work.
 *
 * The ADR names four of those seven; the other three were found by grepping before editing. See its
 * Context.
 */
export function useGeneratePlaylist() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [isGenerating, setIsGenerating] = useState(false);

  const generate = useCallback(
    async (seed: GeneratePlaylistSeed) => {
      // Guards against a double-click producing two playlists. The request is not idempotent —
      // it saves — so the second one is a duplicate the listener then has to delete.
      if (isGenerating) return;
      setIsGenerating(true);

      try {
        const result = await playlistsApi.generate(seed);

        queryClient.invalidateQueries({ queryKey: queryKeys.playlists.all });
        showSuccess(`Created "${result.name}" — ${result.track_count} tracks`);

        // **Navigate, because point 6 says this saves rather than previews.** A button labelled
        // "Make a playlist" that silently added one to the sidebar with no acknowledgement would be
        // its own small version of the problem this ADR is fixing: an action whose result is not
        // where the listener is looking.
        navigate(`/playlists/${result.playlist_id}`);
        return result;
      } catch (error) {
        // The server distinguishes "that seed matched nothing" (404) from "nothing was close
        // enough" (422), and they need different words — the first is a mistake, the second is a
        // fact about the library. Anything else is unexpected and says so plainly.
        const status = (error as { response?: { status?: number } })?.response?.status;
        if (status === 404) {
          showError('Nothing in your library matched that.');
        } else if (status === 422) {
          showError('Nothing in your library was close enough to build a playlist from.');
        } else {
          showError('Could not make a playlist.');
        }
        return undefined;
      } finally {
        setIsGenerating(false);
      }
    },
    [isGenerating, navigate, queryClient],
  );

  return { generate, isGenerating };
}
