import { Database, Cloud, Upload } from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { appSettingsApi } from '../../api';
import { queryKeys } from '../../api/queryKeys';

export function CommunityCache() {
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

  if (isLoading) {
    return (
      <div className="bg-zinc-800/50 rounded-lg p-4">
        <div className="animate-pulse h-16 bg-zinc-700/50 rounded" />
      </div>
    );
  }

  return (
    <div className="bg-zinc-800/50 rounded-lg p-4 space-y-4">
      <div className="flex items-center gap-3">
        <Database className="w-5 h-5 text-accent" />
        <div>
          <h4 className="font-medium text-white">Community Cache</h4>
          <p className="text-sm text-zinc-400">
            Share analysis data with other Familiar users
          </p>
        </div>
      </div>

      {/* Lookup toggle */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Cloud className="w-5 h-5 text-blue-400" />
          <div>
            <p className="text-sm text-white">Use community cache</p>
            <p className="text-xs text-zinc-500">
              Look up pre-computed features and embeddings
            </p>
          </div>
        </div>
        <label className="relative inline-flex items-center cursor-pointer">
          <input
            type="checkbox"
            checked={settings?.community_cache_enabled ?? true}
            onChange={(e) => updateMutation.mutate({ community_cache_enabled: e.target.checked })}
            disabled={updateMutation.isPending}
            className="sr-only peer"
          />
          <div className="w-11 h-6 bg-zinc-600 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-blue-500 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-500 peer-disabled:opacity-50" />
        </label>
      </div>

      {/* Contribute toggle */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Upload className="w-5 h-5 text-success" />
          <div>
            <p className="text-sm text-white">Contribute to cache</p>
            <p className="text-xs text-zinc-500">
              Share your computed features and embeddings (anonymous)
            </p>
          </div>
        </div>
        <label className="relative inline-flex items-center cursor-pointer">
          <input
            type="checkbox"
            checked={settings?.community_cache_contribute ?? false}
            onChange={(e) => updateMutation.mutate({ community_cache_contribute: e.target.checked })}
            disabled={updateMutation.isPending}
            className="sr-only peer"
          />
          <div className="w-11 h-6 bg-zinc-600 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-success-strong rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-accent peer-disabled:opacity-50" />
        </label>
      </div>

      {/* Privacy note */}
      <p className="text-xs text-zinc-500">
        Only audio fingerprint hashes are shared — no filenames, metadata, or personal info.
        Helps speed up analysis for everyone in the community.
      </p>
    </div>
  );
}
