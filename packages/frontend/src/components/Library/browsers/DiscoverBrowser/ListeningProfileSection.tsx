/**
 * ListeningProfileSection — "Albums you might want" on the Discover page.
 *
 * Reads from /api/v1/library/discover/external-albums. Seeded by the user's
 * top-played artists. Empty for new users with no play history.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Sparkles, Loader2 } from 'lucide-react';
import { externalAlbumsApi } from '../../../../api/discovery';
import { queryKeys } from '../../../../api/queryKeys';
import { STALE_TIME } from '../../../../api/queryDefaults';
import { showError } from '../../../../stores/toastStore';
import { ExternalAlbumCard } from '../../../Discovery/ExternalAlbumCard';

const SECTION_LIMIT = 12;

export function ListeningProfileSection() {
  const queryClient = useQueryClient();

  const listParams = { limit: SECTION_LIMIT };

  const listQuery = useQuery({
    queryKey: queryKeys.listeningProfileAlbums.list(listParams),
    queryFn: () => externalAlbumsApi.listeningProfile(listParams),
    staleTime: STALE_TIME.LONG,
  });

  const dismissMutation = useMutation({
    mutationFn: (id: string) => externalAlbumsApi.dismiss(id),
    onMutate: async (id) => {
      await queryClient.cancelQueries({
        queryKey: queryKeys.listeningProfileAlbums.list(listParams),
      });
      const previous = queryClient.getQueryData(
        queryKeys.listeningProfileAlbums.list(listParams),
      );
      queryClient.setQueryData(
        queryKeys.listeningProfileAlbums.list(listParams),
        (old: typeof listQuery.data) =>
          old
            ? { ...old, albums: old.albums.filter((a) => a.id !== id) }
            : old,
      );
      return { previous };
    },
    onError: (_err, _id, ctx) => {
      if (ctx?.previous) {
        queryClient.setQueryData(
          queryKeys.listeningProfileAlbums.list(listParams),
          ctx.previous,
        );
      }
      showError('Failed to dismiss. Try again.');
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.listeningProfileAlbums.all,
      });
    },
  });

  const albums = listQuery.data?.albums ?? [];

  return (
    <section>
      <div className="flex items-center gap-2 mb-3">
        <Sparkles className="w-5 h-5 text-zinc-400" />
        <h2 className="text-lg font-semibold text-zinc-100">
          Albums you might want
        </h2>
        {albums.length > 0 && (
          <span className="px-2 py-0.5 text-xs rounded-full bg-zinc-800 text-zinc-400">
            {albums.length}
          </span>
        )}
      </div>
      <p className="text-xs text-zinc-500 -mt-2 mb-3">
        Based on the artists you listen to most.
      </p>

      {listQuery.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-zinc-500 py-6">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading recommendations...
        </div>
      ) : albums.length === 0 ? (
        <div className="rounded-lg border border-dashed border-zinc-800 bg-zinc-900/40 p-6 text-center">
          <p className="text-sm text-zinc-300 mb-1">
            We'll suggest albums based on what you listen to.
          </p>
          <p className="text-xs text-zinc-500">
            Listen to some music first — recommendations build from your play history.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
          {albums.map((album) => (
            <ExternalAlbumCard
              key={album.id}
              album={album}
              contextLabel="RECOMMENDED"
              onDismiss={(id) => dismissMutation.mutate(id)}
              layout="grid"
            />
          ))}
        </div>
      )}
    </section>
  );
}
