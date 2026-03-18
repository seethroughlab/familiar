import { Sparkles, Library, Music2 } from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { appSettingsApi } from '../../api';
import { queryKeys } from '../../api/queryKeys';

/**
 * Settings for AI-powered playlist generation.
 * Controls whether playlists include suggested tracks not in the library.
 */
export function AISettings() {
  const queryClient = useQueryClient();

  const { data: settings, isLoading } = useQuery({
    queryKey: queryKeys.appSettings.all,
    queryFn: appSettingsApi.get,
  });

  const updateMutation = useMutation({
    mutationFn: appSettingsApi.update,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.appSettings.all });
    },
  });

  const discoveryMode = settings?.playlist_discovery_mode ?? 'suggest_missing';

  const handleModeChange = (mode: string) => {
    updateMutation.mutate({ playlist_discovery_mode: mode });
  };

  if (isLoading) {
    return (
      <div className="bg-zinc-800/50 dark:bg-zinc-800/50 light:bg-zinc-100 rounded-lg p-4">
        <div className="animate-pulse h-24 bg-zinc-700/50 rounded" />
      </div>
    );
  }

  return (
    <div className="bg-zinc-800/50 dark:bg-zinc-800/50 light:bg-zinc-100 rounded-lg p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Sparkles className="w-5 h-5 text-purple-400" />
        <div>
          <h4 className="font-medium text-white dark:text-white light:text-zinc-900">
            Playlist Discovery Mode
          </h4>
          <p className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
            Control how AI builds playlists for you
          </p>
        </div>
      </div>

      {/* Mode selection */}
      <div className="space-y-2">
        {/* Library Only option */}
        <label
          className={`flex items-start gap-3 p-3 rounded-lg cursor-pointer transition-colors ${
            discoveryMode === 'library_only'
              ? 'bg-purple-900/30 border border-purple-500/50'
              : 'bg-zinc-700/30 dark:bg-zinc-700/30 light:bg-zinc-200/50 border border-transparent hover:border-zinc-600'
          }`}
        >
          <input
            type="radio"
            name="discovery_mode"
            value="library_only"
            checked={discoveryMode === 'library_only'}
            onChange={() => handleModeChange('library_only')}
            disabled={updateMutation.isPending}
            className="mt-1 accent-purple-500"
          />
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <Library className="w-4 h-4 text-zinc-400" />
              <span className="font-medium text-white dark:text-white light:text-zinc-900">
                Library Only
              </span>
            </div>
            <p className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600 mt-1">
              Only use tracks from your local library. Good for offline use or when you want
              to stick to music you already own.
            </p>
          </div>
        </label>

        {/* Suggest Missing option */}
        <label
          className={`flex items-start gap-3 p-3 rounded-lg cursor-pointer transition-colors ${
            discoveryMode === 'suggest_missing'
              ? 'bg-purple-900/30 border border-purple-500/50'
              : 'bg-zinc-700/30 dark:bg-zinc-700/30 light:bg-zinc-200/50 border border-transparent hover:border-zinc-600'
          }`}
        >
          <input
            type="radio"
            name="discovery_mode"
            value="suggest_missing"
            checked={discoveryMode === 'suggest_missing'}
            onChange={() => handleModeChange('suggest_missing')}
            disabled={updateMutation.isPending}
            className="mt-1 accent-purple-500"
          />
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <Music2 className="w-4 h-4 text-purple-400" />
              <span className="font-medium text-white dark:text-white light:text-zinc-900">
                Include Suggestions
              </span>
              <span className="text-xs bg-purple-500/20 text-purple-300 px-2 py-0.5 rounded">
                Recommended
              </span>
            </div>
            <p className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600 mt-1">
              Include suggested tracks you might want to add to your collection.
              Playlists show both local tracks and discoverable "missing tracks" with previews.
            </p>
          </div>
        </label>
      </div>

      {/* Info text */}
      <p className="text-xs text-zinc-500 dark:text-zinc-500 light:text-zinc-500">
        When "Include Suggestions" is enabled, AI-generated playlists may include tracks
        you don't own yet. These appear as "missing tracks" with preview playback and
        links to purchase on Bandcamp.
      </p>
    </div>
  );
}
