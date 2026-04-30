/**
 * Hooks around the /mixtapes list query.
 *
 * One shared react-query cache key is used by:
 *   - the Mix Tapes list view
 *   - the header MixTapeRenderIndicator
 *   - the contextual button on PlaylistDetail / SmartPlaylistDetail
 *
 * Refetches every 2s while at least one mixtape is in-flight, otherwise idle.
 */
import { useQuery } from '@tanstack/react-query';
import { mixtapesApi, type MixTape } from '../api';
import { queryKeys } from '../api/queryKeys';

const ACTIVE_REFETCH_MS = 2000;

function isInFlight(mt: MixTape): boolean {
  return mt.status === 'pending' || mt.status === 'rendering';
}

export function useMixtapesList() {
  return useQuery({
    queryKey: queryKeys.mixtapes.all,
    queryFn: () => mixtapesApi.list(),
    refetchInterval: (query) => {
      const data = query.state.data as MixTape[] | undefined;
      if (!data) return false;
      return data.some(isInFlight) ? ACTIVE_REFETCH_MS : false;
    },
  });
}

/**
 * The "current relevant mixtape" for a given source.
 *
 * Selection rules (in order):
 *   1. An in-flight render for this source wins — that's the most informative.
 *   2. Otherwise, the most recent mixtape for this source (any status).
 *   3. If nothing matches, returns null.
 */
export function useMixtapeForSource(
  kind: 'playlist' | 'smart_playlist',
  sourceId: string | null | undefined,
): MixTape | null {
  const { data } = useMixtapesList();
  if (!data || !sourceId) return null;

  const matches = data.filter((mt) =>
    kind === 'playlist'
      ? mt.source_playlist_id === sourceId
      : mt.source_smart_playlist_id === sourceId,
  );
  if (matches.length === 0) return null;

  const inFlight = matches.find(isInFlight);
  if (inFlight) return inFlight;

  // Already sorted newest-first by the backend, but be defensive.
  return [...matches].sort((a, b) =>
    b.created_at.localeCompare(a.created_at),
  )[0];
}

/** Friendly labels for the backend's render phases. */
export const PHASE_LABELS: Record<string, string> = {
  resolving_tracks: 'Resolving tracks',
  rendering_audio: 'Rendering audio',
  generating_cover: 'Generating cover',
  writing_tracklist: 'Writing tracklist',
  writing_tags: 'Writing tags',
  bundling: 'Bundling',
  ready: 'Ready',
  failed: 'Failed',
};
