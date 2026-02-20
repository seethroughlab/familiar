import { RefreshCw } from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { appSettingsApi } from '../../api';

/**
 * Settings for automatic metadata enrichment from MusicBrainz.
 */
export function MetadataSettings() {
  const queryClient = useQueryClient();

  const { data: settings, isLoading } = useQuery({
    queryKey: ['app-settings'],
    queryFn: appSettingsApi.get,
  });

  const updateMutation = useMutation({
    mutationFn: appSettingsApi.update,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['app-settings'] });
    },
  });

  const autoEnrich = settings?.auto_enrich_metadata ?? true;
  const overwriteExisting = settings?.enrich_overwrite_existing ?? false;

  const handleAutoEnrichToggle = (enabled: boolean) => {
    updateMutation.mutate({ auto_enrich_metadata: enabled });
  };

  const handleOverwriteToggle = (enabled: boolean) => {
    updateMutation.mutate({ enrich_overwrite_existing: enabled });
  };

  if (isLoading) {
    return (
      <div className="bg-zinc-800/50 dark:bg-zinc-800/50 light:bg-zinc-100 rounded-lg p-4">
        <div className="animate-pulse h-16 bg-zinc-700/50 rounded" />
      </div>
    );
  }

  return (
    <div className="bg-zinc-800/50 dark:bg-zinc-800/50 light:bg-zinc-100 rounded-lg p-4 space-y-4">
      {/* Main toggle */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <RefreshCw className="w-5 h-5 text-purple-400" />
          <div>
            <h4 className="font-medium text-white dark:text-white light:text-zinc-900">
              Auto-enrich metadata
            </h4>
            <p className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
              Fetch missing metadata from MusicBrainz when playing tracks
            </p>
          </div>
        </div>

        <label className="relative inline-flex items-center cursor-pointer">
          <input
            type="checkbox"
            checked={autoEnrich}
            onChange={(e) => handleAutoEnrichToggle(e.target.checked)}
            disabled={updateMutation.isPending}
            className="sr-only peer"
          />
          <div className="w-11 h-6 bg-zinc-600 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-purple-500 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-purple-500 peer-disabled:opacity-50" />
        </label>
      </div>

      {/* Overwrite option (only shown when auto-enrich is enabled) */}
      {autoEnrich && (
        <div className="flex items-center justify-between pl-8 border-l-2 border-zinc-700">
          <div>
            <h4 className="font-medium text-white dark:text-white light:text-zinc-900 text-sm">
              Overwrite existing metadata
            </h4>
            <p className="text-xs text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
              Replace existing tags with MusicBrainz data (otherwise only fills blanks)
            </p>
          </div>

          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={overwriteExisting}
              onChange={(e) => handleOverwriteToggle(e.target.checked)}
              disabled={updateMutation.isPending}
              className="sr-only peer"
            />
            <div className="w-9 h-5 bg-zinc-600 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-purple-500 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-purple-500 peer-disabled:opacity-50" />
          </label>
        </div>
      )}

      {/* Info text */}
      <p className="text-xs text-zinc-500 dark:text-zinc-500 light:text-zinc-500">
        Uses audio fingerprinting (AcoustID) to identify tracks and fetches metadata including album artwork from MusicBrainz. Updates are written to ID3 tags in your files.
      </p>
    </div>
  );
}
